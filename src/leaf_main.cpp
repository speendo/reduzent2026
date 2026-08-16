#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_system.h>

#include "espnow_frame.h"
#include "note_freq.h"
#include "envelope.h"
#include "voice.h"
#include "expression.h"

#define MY_CHANNEL 0       // TODO: parasol config (later slice)
#define PIEZO_PIN 3
#define PWM_CHANNEL 0
#define PWM_RES 8
#define ESP_NOW_CHANNEL 1  // fixed WiFi channel; must match the controller
#define HEARTBEAT_MS 10000
#define HEARTBEAT_JITTER_MS 1000

#define ARP_TICK_MS 16     // ~60 Hz: arpeggio index + frequency retune
#define PITCH_BEND_RANGE 2 // +/- semitones (leaf-spec default)

// Render path seam: path A (arpeggio) is implemented here; path B (1-bit mixer)
// is the next slice and reuses voice.h/envelope.h/expression.h unchanged.
typedef enum { RENDER_ARPEGGIO = 0, RENDER_1BIT = 1 } render_path_t;

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static voice_table_t voices;

static render_path_t render_path = RENDER_ARPEGGIO;
static uint16_t pitch_bend = PITCH_BEND_CENTER;
static uint8_t chan_pressure = 127;      // 127 = full amplitude
static uint8_t cc1_vibrato = 0;
static uint8_t poly_pressure[128];       // per-note aftertouch, 127 = full

static int arp_index = -1;               // current arpeggiated voice, -1 = none
static uint32_t last_arp_ms = 0;

static uint32_t last_note_millis = 0;    // 0 = never played
static bool played_since_hb = false;

// Drive LEDC duty from a 0-127 amplitude, scaled by channel x poly aftertouch.
static void set_duty(uint16_t level, uint8_t chan_p, uint8_t poly_p) {
    uint8_t aftertouch = scale_level(chan_p, poly_p); // compose channel x poly
    uint8_t scaled = scale_level((uint8_t)level, aftertouch);
    ledcWrite(PWM_CHANNEL, (uint32_t)scaled << 1); // 7-bit -> 8-bit, max 254
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
        voice_t* v = &voices.voices[arp_index];
        int16_t cents = pitch_bend_cents(pitch_bend, PITCH_BEND_RANGE)
                      + vibrato_cents(now_ms, cc1_vibrato);
        uint16_t freq = cents_to_freq(note_to_freq(v->note), cents);
        ledcChangeFrequency(PWM_CHANNEL, freq, PWM_RES);
    } else {
        arp_index = -1;
        ledcWrite(PWM_CHANNEL, 0);
    }
}

static volatile int hb_tx_status = -1; // -1 = none, else esp_now_send_status_t

static void on_send(const uint8_t* mac, esp_now_send_status_t status) {
    (void)mac;
    hb_tx_status = (int)status;
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
    esp_err_t err = esp_now_send(BROADCAST_MAC, buf, sizeof(buf));
    if (err != ESP_OK) {
        Serial.printf("hb esp_now_send err=%d\n", (int)err);
    }
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
            if (frame.value == 0) {
                voice_note_off(&voices, frame.note, now);
            } else {
                voice_note_on(&voices, frame.note, frame.value, now);
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
        case EVENT_PROGRAM_CHANGE:
            // 0 = arpeggio (path A); 1 = 1-bit mixer (path B, next slice).
            render_path = (frame.value == 1) ? RENDER_1BIT : RENDER_ARPEGGIO;
            if (render_path == RENDER_1BIT) {
                // Path B leaves the piezo silent: kill any sounding note so
                // LEDC does not keep its last frequency/duty humming.
                arp_index = -1;
                ledcWrite(PWM_CHANNEL, 0);
            }
            break;
        case EVENT_PANIC:
            voice_table_init(&voices, &ENVELOPE_DEFAULT);
            arp_index = -1;
            ledcWrite(PWM_CHANNEL, 0);
            break;
        default:
            break;
    }
}

void setup() {
    Serial.begin(115200);
    for (int i = 0; i < 128; i++) poly_pressure[i] = 127;

    voice_table_init(&voices, &ENVELOPE_DEFAULT);

    ledcSetup(PWM_CHANNEL, 1000, PWM_RES);
    ledcAttachPin(PIEZO_PIN, PWM_CHANNEL);
    ledcWrite(PWM_CHANNEL, 0);

    WiFi.mode(WIFI_STA);
    esp_wifi_set_ps(WIFI_PS_NONE);  // never modem-sleep; don't miss broadcasts
    esp_wifi_set_channel(ESP_NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
        return;
    }
    esp_now_register_recv_cb(on_recv);
    esp_now_register_send_cb(on_send);

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

    if (render_path == RENDER_ARPEGGIO) {
        render_arpeggio_ctrl(now); // ADSR + duty every ~1 ms
        if ((int32_t)(now - last_arp_ms) >= ARP_TICK_MS) {
            last_arp_ms = now;
            render_arpeggio_advance(now); // arpeggio + frequency every ~16 ms
        }
    }
    // RENDER_1BIT is unimplemented until the next slice; the leaf stays silent.

    static uint32_t next_hb = 0; // first heartbeat fires immediately at boot
    if ((int32_t)(now - next_hb) >= 0) {
        send_heartbeat();
        next_hb = now + HEARTBEAT_MS + (esp_random() % HEARTBEAT_JITTER_MS);
    }
    if (hb_tx_status >= 0) {
        Serial.printf("hb tx %s\n",
                      hb_tx_status == ESP_NOW_SEND_SUCCESS ? "ok" : "FAIL");
        hb_tx_status = -1;
    }
    delay(1); // yield so the CPU idles instead of spinning
}
