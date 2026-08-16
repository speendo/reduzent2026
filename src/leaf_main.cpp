#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_system.h>

#include "espnow_frame.h"
#include "note_freq.h"

#define MY_CHANNEL 0       // TODO: parasol config (later slice)
#define PIEZO_PIN 3
#define PWM_CHANNEL 0
#define PWM_RES 8
#define ESP_NOW_CHANNEL 1  // fixed WiFi channel; must match the controller
#define LEAF_DEBUG 0       // 1 = serial note logging; 0 = silent (battery)
#define HEARTBEAT_MS 10000
#define HEARTBEAT_JITTER_MS 1000

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static uint8_t current_note = 0xFF;
static bool note_active = false;
static uint32_t last_note_millis = 0;  // 0 = never played (so value = uptime until first note)
static bool played_since_hb = false;

static void note_on(uint8_t note, uint8_t velocity) {
    current_note = note;
    note_active = true;
    last_note_millis = millis();
    played_since_hb = true;
    ledcChangeFrequency(PWM_CHANNEL, note_to_freq(note), PWM_RES);
    ledcWrite(PWM_CHANNEL, (uint32_t)velocity << 1); // 7-bit -> 8-bit, max 254 < 256
#if LEAF_DEBUG
    Serial.printf("[%lu] on %d (%u Hz) vel %d\n", millis(), note, note_to_freq(note), velocity);
#endif
}

static void note_off(uint8_t note) {
    if (note != current_note) return; // monophonic: ignore offs for other notes
    note_active = false;
    current_note = 0xFF;
    ledcWrite(PWM_CHANNEL, 0);
#if LEAF_DEBUG
    Serial.printf("[%lu] off %d\n", millis(), note);
#endif
}

// Fire-and-forget liveness ping. `played` = did this leaf sound a note since
// the last heartbeat; `value` = seconds since the last note (or boot).
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
    switch (frame.type) {
        case EVENT_NOTE:
            if (frame.value == 0) note_off(frame.note);
            else note_on(frame.note, frame.value);
            break;
        case EVENT_PANIC:
            note_off(current_note);
            break;
        default:
            break;
    }
}

void setup() {
    Serial.begin(115200);
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
    static uint32_t next_hb = 0; // first heartbeat fires immediately at boot
    uint32_t now = millis();
    if ((int32_t)(now - next_hb) >= 0) {
        send_heartbeat();
        next_hb = now + HEARTBEAT_MS + (esp_random() % HEARTBEAT_JITTER_MS);
    }
    delay(1); // yield so the CPU idles instead of spinning
}
