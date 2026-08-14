#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "espnow_frame.h"
#include "note_freq.h"

#define MY_CHANNEL 0       // TODO: parasol config (later slice)
#define PIEZO_PIN 2
#define PWM_CHANNEL 0
#define PWM_RES 8
#define ESP_NOW_CHANNEL 1  // fixed WiFi channel; must match the controller
#define LEAF_DEBUG 0       // 1 = serial note logging; 0 = silent (battery)

static uint8_t current_note = 0xFF;
static bool note_active = false;

static void note_on(uint8_t note, uint8_t velocity) {
    current_note = note;
    note_active = true;
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
    esp_wifi_set_channel(ESP_NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
        return;
    }
    esp_now_register_recv_cb(on_recv);

    // Register the broadcast peer so broadcast frames are received.
    static const uint8_t broadcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, broadcast, 6);
    peer.channel = ESP_NOW_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("add_peer failed");
    }

    Serial.println("leaf ready");
}

void loop() {
    delay(1); // yield so the CPU idles instead of spinning
}
