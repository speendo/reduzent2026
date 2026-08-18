#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_system.h>
#include <esp32-hal-timer.h>

#include "espnow_frame.h"
#include "note_freq.h"
#include "envelope.h"
#include "voice.h"
#include "expression.h"
#include "mixer.h"
#include "solenoid.h"

#define MY_CHANNEL 0       // TODO: parasol config (later slice)
#define PIEZO_PIN 3
#define PWM_CHANNEL 0
#define PWM_RES 8
#define ESP_NOW_CHANNEL 13  // fixed WiFi channel; MUST stay 13 to match controller_main.cpp
#define HEARTBEAT_MS 10000
#define HEARTBEAT_JITTER_MS 1000

#define ARP_TICK_MS 16     // ~60 Hz: arpeggio index + frequency retune
#define PITCH_BEND_RANGE 2 // +/- semitones (leaf-spec default)
#define STUCK_NOTE_TIMEOUT_MS 3000
// Solenoid leaf (percussive; see docs/leaf-spec.md §Solenoid driver).
// GPIO 4 is a plain GPIO on the ESP32-C3 (piezo uses GPIO 3).
#define SOLENOID_PIN 4
#define SOLENOID_LEDC_CHANNEL 2  // (chan/2)%4 => channel 2 = timer 1, separate from piezo timer 0
#define SOLENOID_LEDC_TIMER 1
#define SOLENOID_FREQ 20000       // ~20 kHz carrier: duty controls coil current
#define SOLENOID_NOTE 36          // note that triggers this solenoid (parasol later)
#define SOLENOID_HOLD_MS 40       // strike window; exceeds pull-in time
#define SOLENOID_DUTY_MIN 40      // velocity 1 (0-255)
#define SOLENOID_DUTY_MAX 220     // velocity 127 (0-255)
#define NUM_NOTES 128         // MIDI note count; poly_pressure table size

// Render paths: B = 1-bit 32 kHz mixer, A = LEDC arpeggio, M = LEDC monophonic.
typedef enum { RENDER_1BIT = 0, RENDER_ARPEGGIO = 1, RENDER_MONO = 2 } render_path_t;

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static voice_table_t voices;
static solenoid_t solenoid;

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

// Drive LEDC duty from a 0-127 amplitude, scaled by channel x poly aftertouch.
static void set_duty(uint16_t level, uint8_t chan_p, uint8_t poly_p) {
    uint8_t aftertouch = scale_level(chan_p, poly_p); // compose channel x poly
    uint8_t scaled = scale_level((uint8_t)level, aftertouch);
    ledcWrite(PWM_CHANNEL, (uint32_t)scaled << 1); // 7-bit -> 8-bit, max 254
}

// Retune the LEDC frequency for a note (pitch bend + vibrato applied).
static void retune_ledc(uint32_t now_ms, uint8_t note) {
    int16_t cents = pitch_bend_cents(pitch_bend, PITCH_BEND_RANGE)
                  + vibrato_cents(now_ms, cc1_vibrato);
    uint16_t freq = cents_to_freq(note_to_freq(note), cents);
    ledcChangeFrequency(PWM_CHANNEL, freq, PWM_RES);
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
    digitalWrite(PIEZO_PIN, mix_voices(&voices, phase_inc));
}

// Path B: recompute per-voice phase increments (note + pitch bend + vibrato).
static void mixer_update_incs(uint32_t now_ms) {
    for (int i = 0; i < MAX_VOICES; i++) {
        voice_t* v = &voices.voices[i];
        if (!voice_is_active(v)) { phase_inc[i] = 0; continue; }
        int16_t cents = pitch_bend_cents(pitch_bend, PITCH_BEND_RANGE)
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
    ledcDetachPin(PIEZO_PIN);
    pinMode(PIEZO_PIN, OUTPUT);
    digitalWrite(PIEZO_PIN, 0);
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
    ledcAttachPin(PIEZO_PIN, PWM_CHANNEL);
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
    if (frame.channel != MY_CHANNEL && frame.channel != ESP_NOW_CHANNEL_BROADCAST) return;

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
            voice_table_init(&voices, &ENVELOPE_DEFAULT);
            arp_index = -1;
            mono_note = 0xFF;
            ledcWrite(PWM_CHANNEL, 0);
            break;
        default:
            break;
    }
}

void setup() {
    Serial.begin(115200);
    for (int i = 0; i < NUM_NOTES; i++) poly_pressure[i] = 127;

    voice_table_init(&voices, &ENVELOPE_DEFAULT);

    ledcSetup(PWM_CHANNEL, 1000, PWM_RES);
    ledcAttachPin(PIEZO_PIN, PWM_CHANNEL);
    ledcWrite(PWM_CHANNEL, 0);

    ledcSetup(SOLENOID_LEDC_CHANNEL, SOLENOID_FREQ, PWM_RES);
    ledcAttachPin(SOLENOID_PIN, SOLENOID_LEDC_CHANNEL);
    ledcWrite(SOLENOID_LEDC_CHANNEL, 0);
    solenoid_init(&solenoid, SOLENOID_NOTE, SOLENOID_DUTY_MIN, SOLENOID_DUTY_MAX, SOLENOID_HOLD_MS);

    WiFi.mode(WIFI_STA);
    esp_wifi_set_ps(WIFI_PS_NONE);  // never modem-sleep; don't miss broadcasts
    esp_wifi_set_channel(ESP_NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
        return;
    }
    esp_now_register_recv_cb(on_recv);

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = ESP_NOW_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("add_peer failed");
    }

    Serial.println("leaf ready");
}

void loop() {
    uint32_t now = millis();

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
    delay(1); // yield so the CPU idles instead of spinning
}
