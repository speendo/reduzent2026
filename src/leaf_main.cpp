#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_system.h>
#include <esp32-hal-timer.h>

#include "espnow_frame.h"
#include "note_freq.h"
#include "ledc_freq.h"
#include "envelope.h"
#include "voice.h"
#include "expression.h"
#include "mixer.h"
#include "solenoid.h"
#include "mode.h"
#include "ssid.h"
#include "wifi_ap.h"
#include "config.h"

#define PWM_CHANNEL 0
#define PWM_RES 8
#define LEDC_XTAL_CLK_HZ 40000000  // C3 crystal; matches core's LEDC_USE_XTAL_CLK
#define HEARTBEAT_MS 10000
#define HEARTBEAT_JITTER_MS 1000

#define ARP_TICK_MS 16     // ~60 Hz: arpeggio index + frequency retune
#define STUCK_NOTE_TIMEOUT_MS 3000
// Solenoid leaf (percussive; see docs/leaf-spec.md §Solenoid driver).
// GPIO 4 is a plain GPIO on the ESP32-C3 (piezo uses GPIO 3).
#define SOLENOID_LEDC_CHANNEL 2  // (chan/2)%4 => channel 2 = timer 1, separate from piezo timer 0
#define SOLENOID_LEDC_TIMER 1
#define SOLENOID_FREQ 20000       // ~20 kHz carrier: duty controls coil current
#define NUM_NOTES 128         // MIDI note count; poly_pressure table size

// Render paths: B = 1-bit 32 kHz mixer, A = LEDC arpeggio, M = LEDC monophonic.
typedef enum { RENDER_1BIT = 0, RENDER_ARPEGGIO = 1, RENDER_MONO = 2 } render_path_t;

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static voice_table_t voices;
static solenoid_t solenoid;
static leaf_config_t cfg;          // loaded from NVS in setup(); defaults if none
static mode_state_t dev_mode;          // settings/live state machine
static char ap_ssid[32];               // settings-mode AP SSID
static device_mode_t last_hw_mode = MODE_LIVE;  // WiFi/ESP-NOW state matching dev_mode.mode
static envelope_params_t env;      // ADSR params built from cfg at boot

static render_path_t render_path = RENDER_1BIT;
static uint16_t pitch_bend = PITCH_BEND_CENTER;
static uint8_t chan_pressure = 127;      // 127 = full amplitude
static uint8_t cc1_vibrato = 0;
static uint8_t poly_pressure[NUM_NOTES]; // per-note aftertouch, 127 = full

static int arp_index = -1;               // current arpeggiated voice, -1 = none
static uint32_t last_arp_ms = 0;

static hw_timer_t* mix_timer = NULL;     // path B 32 kHz sample timer
static uint32_t phase_inc[MAX_VOICES];   // path B per-voice phase increments
static int mono_note = 0xFF;             // path M note currently driving LEDC

static uint32_t last_note_millis = 0;    // 0 = never played
static bool played_since_hb = false;

static uint8_t pwm_res = PWM_RES; // current LEDC duty resolution (bits); set by retune_ledc

// Drive LEDC duty from a 0-127 amplitude, scaled by channel x poly aftertouch.
static void set_duty(uint16_t level, uint8_t chan_p, uint8_t poly_p) {
    uint8_t aftertouch = scale_level(chan_p, poly_p); // compose channel x poly
    uint8_t scaled = scale_level((uint8_t)level, aftertouch);
    ledcWrite(PWM_CHANNEL, (uint32_t)scaled << (pwm_res - 7)); // 7-bit -> pwm_res-bit
}

// Retune the LEDC frequency for a note (pitch bend + vibrato applied), picking
// the duty resolution that can represent it. Without this, notes below ~51
// (147 Hz) overflow the LEDC divider and keep the previous note's frequency.
static void retune_ledc(uint32_t now_ms, uint8_t note) {
    int16_t cents = pitch_bend_cents(pitch_bend, cfg.piezo_pitch_bend_range)
                  + vibrato_cents(now_ms, cc1_vibrato);
    uint16_t freq = cents_to_freq(note_to_freq(note), cents);
    uint8_t res = ledc_resolution_for(LEDC_XTAL_CLK_HZ, freq);
    if (res == 0) res = PWM_RES; // safety fallback if no resolution fits
    pwm_res = res;
    ledcChangeFrequency(PWM_CHANNEL, freq, res);
}

// Path A: advance ADSR every control tick and keep duty on the arpeggiated voice.
static void render_arpeggio_ctrl(uint32_t now_ms) {
    voice_tick(&voices, now_ms);
    if (arp_index >= 0 && voice_is_active(&voices.voices[arp_index])) {
        voice_t* v = &voices.voices[arp_index];
        set_duty(v->level, chan_pressure, poly_pressure[v->note]);
    } else {
        ledcWrite(PWM_CHANNEL, 0);
    }
}

// Path A: advance the arpeggio index and retune LEDC frequency every ~16 ms.
static void render_arpeggio_advance(uint32_t now_ms) {
    int next = voice_arpeggio_step(&voices, arp_index);
    if (next >= 0) {
        arp_index = next;
        retune_ledc(now_ms, voices.voices[arp_index].note);
    } else {
        arp_index = -1;
        ledcWrite(PWM_CHANNEL, 0);
    }
}

// Path M: last-note-wins monophonic. ADSR + duty + retune-on-note-change every
// ~1 ms; continuous pitch bend/vibrato retunes on the shared ~60 Hz tick.
static void render_mono_ctrl(uint32_t now_ms) {
    voice_tick(&voices, now_ms);
    int idx = voice_mono_current(&voices);
    if (idx >= 0) {
        voice_t* v = &voices.voices[idx];
        set_duty(v->level, chan_pressure, poly_pressure[v->note]);
        if (v->note != mono_note) {
            mono_note = v->note;
            retune_ledc(now_ms, v->note);
        }
    } else {
        mono_note = 0xFF;
        ledcWrite(PWM_CHANNEL, 0);
    }
}

// Path B: 32 kHz ISR — XOR all active voices into the piezo GPIO. No float
// math here: phase increments were precomputed by mixer_update_incs.
static void IRAM_ATTR on_mixer_sample(void) {
    digitalWrite(cfg.gpio_piezo, mix_voices(&voices, phase_inc));
}

// Path B: recompute per-voice phase increments (note + pitch bend + vibrato).
static void mixer_update_incs(uint32_t now_ms) {
    for (int i = 0; i < MAX_VOICES; i++) {
        voice_t* v = &voices.voices[i];
        if (!voice_is_active(v)) { phase_inc[i] = 0; continue; }
        int16_t cents = pitch_bend_cents(pitch_bend, cfg.piezo_pitch_bend_range)
                      + vibrato_cents(now_ms, cc1_vibrato);
        uint16_t freq = cents_to_freq(note_to_freq(v->note), cents);
        phase_inc[i] = phase_increment(freq, MIXER_SAMPLE_RATE);
    }
}

// Path B control (decimated ~1 kHz): ADSR + expression -> phase increments.
static void render_1bit_ctrl(uint32_t now_ms) {
    voice_tick(&voices, now_ms);
    mixer_update_incs(now_ms);
}

// Detach LEDC and start the 32 kHz GPIO mixer (path B).
static void enter_1bit(void) {
    ledcDetachPin(cfg.gpio_piezo);
    pinMode(cfg.gpio_piezo, OUTPUT);
    digitalWrite(cfg.gpio_piezo, 0);
    mix_timer = timerBegin(0, 2, true);        // 80 MHz APB / 2 = 40 MHz tick (C3)
    timerAttachInterrupt(mix_timer, &on_mixer_sample, false);
    timerAlarmWrite(mix_timer, 1250, true);    // 40e6 / 1250 = 32 kHz
    timerAlarmEnable(mix_timer);
}

// Stop the mixer (if running) and re-attach the pin to LEDC (paths A/M).
static void enter_ledc(void) {
    if (mix_timer) {
        timerAlarmDisable(mix_timer);
        timerDetachInterrupt(mix_timer);
        mix_timer = NULL;
    }
    ledcAttachPin(cfg.gpio_piezo, PWM_CHANNEL);
    ledcWrite(PWM_CHANNEL, 0);
    arp_index = -1;
    mono_note = 0xFF;
}

// Select render path; switches the pin driver (LEDC <-> GPIO) as needed.
static void set_render_path(render_path_t next) {
    if (next == render_path) return;
    if (next == RENDER_1BIT) enter_1bit();
    else if (render_path == RENDER_1BIT) enter_ledc();
    else { arp_index = -1; mono_note = 0xFF; } // A <-> M: both LEDC, just reset
    render_path = next;
}

static void send_heartbeat() {
    uint8_t buf[ESP_NOW_FRAME_SIZE];
    espnow_frame_t frame;
    frame.channel = ESP_NOW_CHANNEL_BROADCAST;
    frame.type = EVENT_HEARTBEAT;
    frame.note = played_since_hb ? 1 : 0;
    uint32_t secs = (millis() - last_note_millis) / 1000;
    frame.value = (uint8_t)(secs > 255 ? 255 : secs);
    frame.value_hi = 0;
    frame_pack(&frame, buf);
    esp_now_send(BROADCAST_MAC, buf, sizeof(buf));
    played_since_hb = false;
}

static void on_recv(const uint8_t* mac, const uint8_t* data, int len) {
    (void)mac;
    if (len != ESP_NOW_FRAME_SIZE) return;
    espnow_frame_t frame;
    frame_unpack(data, &frame);
    if (frame.channel != cfg.channel && frame.channel != ESP_NOW_CHANNEL_BROADCAST) return;

    uint32_t now = millis();
    switch (frame.type) {
        case EVENT_NOTE:
            frame.note &= 0x7F; // clamp untrusted radio value to 0-127
            if (solenoid_note_on(&solenoid, frame.note, frame.value, now)) {
                ledcWrite(SOLENOID_LEDC_CHANNEL, solenoid.active_duty);
                last_note_millis = now;
                played_since_hb = true;
            }
            break;
        case EVENT_PITCH_BEND:
            pitch_bend = ((uint16_t)frame.value_hi << 7) | frame.value;
            break;
        case EVENT_CHANNEL_AFTERTOUCH:
            chan_pressure = frame.value;
            break;
        case EVENT_POLY_AFTERTOUCH:
            frame.note &= 0x7F; // poly_pressure is a 128-entry table
            poly_pressure[frame.note] = frame.value;
            break;
        case EVENT_CC1_VIBRATO:
            cc1_vibrato = frame.value;
            break;
        case EVENT_PROGRAM_CHANGE: {
            // 0 = 1-bit mixer (path B); 1 = arpeggio (path A); 2 = monophonic (path M).
            render_path_t next = (frame.value == 1) ? RENDER_ARPEGGIO
                               : (frame.value == 2) ? RENDER_MONO
                               : RENDER_1BIT;
            set_render_path(next);
            break;
        }
        case EVENT_NOTE_HOLD:
            frame.note &= 0x7F;
            voice_note_hold(&voices, frame.note, frame.value, now);
            break;
        case EVENT_NOTES_OFF:
            voice_all_notes_off(&voices, now);
            break;
        case EVENT_RESET_CONTROLLERS:
            pitch_bend = PITCH_BEND_CENTER;
            cc1_vibrato = 0;
            chan_pressure = 127;
            for (int i = 0; i < NUM_NOTES; i++) poly_pressure[i] = 127;
            break;
        case EVENT_PANIC:
            voice_table_init(&voices, &env);
            arp_index = -1;
            mono_note = 0xFF;
            ledcWrite(PWM_CHANNEL, 0);
            break;
        case EVENT_ENTER_SETTINGS:
            // All leaves (0xFF) or a leaf whose node_id matches the target.
            if (frame.note == ESP_NOW_CHANNEL_BROADCAST || frame.note == cfg.node_id) {
                mode_enter_settings(&dev_mode, millis());
            }
            break;
        default:
            break;
    }
}

// Live -> Settings: silence audio and bring up the settings AP.
static void enter_settings_mode(void) {
    enter_ledc();                       // stop 1-bit mixer if active; silence piezo LEDC
    ledcWrite(SOLENOID_LEDC_CHANNEL, 0);
    wifi_ap_start(ap_ssid, cfg.espnow_channel);
}

// Settings -> Live: tear down the AP, restore ESP-NOW and the render path.
static void exit_settings_mode(void) {
    wifi_ap_stop();
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
    }
    esp_now_register_recv_cb(on_recv);
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = cfg.espnow_channel;
    peer.ifidx = WIFI_IF_STA;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("esp_now_add_peer failed");
    }
    if (render_path == RENDER_1BIT) enter_1bit();
}

void setup() {
    Serial.begin(115200);
    config_defaults(&cfg);
    config_load("leaf_cfg", &cfg);
    env.attack_ms = cfg.piezo_adsr_attack_ms;
    env.decay_ms = cfg.piezo_adsr_decay_ms;
    env.sustain_pct = cfg.piezo_adsr_sustain_pct;
    env.release_ms = cfg.piezo_adsr_release_ms;
    for (int i = 0; i < NUM_NOTES; i++) poly_pressure[i] = 127;

    voice_table_init(&voices, &env);

    ledcSetup(PWM_CHANNEL, 1000, PWM_RES);
    ledcAttachPin(cfg.gpio_piezo, PWM_CHANNEL);
    ledcWrite(PWM_CHANNEL, 0);

    ledcSetup(SOLENOID_LEDC_CHANNEL, SOLENOID_FREQ, PWM_RES);
    ledcAttachPin(cfg.gpio_solenoid, SOLENOID_LEDC_CHANNEL);
    ledcWrite(SOLENOID_LEDC_CHANNEL, 0);
    solenoid_init(&solenoid, cfg.solenoid_note, cfg.solenoid_duty_min, cfg.solenoid_duty_max, cfg.solenoid_hold_ms);

    WiFi.mode(WIFI_STA);
    wifi_set_country("EU");
    esp_wifi_set_ps(WIFI_PS_NONE);  // never modem-sleep; don't miss broadcasts
    esp_wifi_set_channel(cfg.espnow_channel, WIFI_SECOND_CHAN_NONE);
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
        return;
    }
    esp_now_register_recv_cb(on_recv);

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = cfg.espnow_channel;
    peer.ifidx = WIFI_IF_STA;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("add_peer failed");
    }

    mode_init(&dev_mode, (uint32_t)cfg.settings_window_sec * 1000);
    uint8_t mac[6];
    WiFi.macAddress(mac);
    ssid_build(ap_ssid, sizeof(ap_ssid), 0, cfg.node_id, mac);
    last_hw_mode = dev_mode.mode;   // leaf boots to live; never the boot window

    Serial.println("leaf ready");
}

void loop() {
    uint32_t now = millis();
    mode_tick(&dev_mode, now);
    if (dev_mode.mode != last_hw_mode) {
        if (mode_is_settings(&dev_mode)) enter_settings_mode();
        else exit_settings_mode();
        last_hw_mode = dev_mode.mode;
    }

    if (!mode_is_settings(&dev_mode)) {
        // Percussive: release the coil once the strike window closes.
        if (solenoid_tick(&solenoid, now) == 0) {
            ledcWrite(SOLENOID_LEDC_CHANNEL, 0);
        }

        voice_watchdog(&voices, now, STUCK_NOTE_TIMEOUT_MS);

        if (render_path == RENDER_ARPEGGIO) {
            render_arpeggio_ctrl(now); // ADSR + duty every ~1 ms
            if ((int32_t)(now - last_arp_ms) >= ARP_TICK_MS) {
                last_arp_ms = now;
                render_arpeggio_advance(now); // arpeggio + frequency every ~16 ms
            }
        } else if (render_path == RENDER_MONO) {
            render_mono_ctrl(now); // ADSR + duty + retune-on-change every ~1 ms
            if ((int32_t)(now - last_arp_ms) >= ARP_TICK_MS && mono_note != 0xFF) {
                last_arp_ms = now;
                retune_ledc(now, mono_note); // pitch bend + vibrato at ~60 Hz
            }
        } else {
            render_1bit_ctrl(now); // ADSR + phase increments at ~1 kHz; ISR mixes at 32 kHz
        }

        static uint32_t next_hb = 0; // first heartbeat fires immediately at boot
        if ((int32_t)(now - next_hb) >= 0) {
            send_heartbeat();
            next_hb = now + HEARTBEAT_MS + (esp_random() % HEARTBEAT_JITTER_MS);
        }
    }
    delay(1); // yield so the CPU idles instead of spinning
}
