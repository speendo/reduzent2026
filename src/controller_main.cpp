#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "espnow_frame.h"
#include "text_parser.h"

#define ESP_NOW_CHANNEL 1  // fixed WiFi channel; must match every leaf

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static char line_buf[64];
static size_t line_len = 0;

static void transmit(const espnow_frame_t* f) {
    uint8_t buf[ESP_NOW_FRAME_SIZE];
    frame_pack(f, buf);
    if (esp_now_send(BROADCAST_MAC, buf, sizeof(buf)) != ESP_OK) {
        Serial.println("send failed");
    }
}

static void handle_line(const char* line) {
    espnow_frame_t frame;
    if (parse_command(line, &frame)) {
        transmit(&frame);
        Serial.printf("[%lu] tx ch=%d type=%d note=%d value=%d\n",
                      millis(), frame.channel, frame.type, frame.note, frame.value);
    }
}

void setup() {
    Serial.begin(115200);

    WiFi.mode(WIFI_STA);
    esp_wifi_set_channel(ESP_NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
        return;
    }

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = ESP_NOW_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("add_peer failed");
    }

    Serial.println("controller ready");
}

void loop() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (line_len > 0) {
                line_buf[line_len] = '\0';
                handle_line(line_buf);
                line_len = 0;
            }
        } else if (line_len < sizeof(line_buf) - 1) {
            line_buf[line_len++] = c;
        }
    }
    delay(1); // yield so the CPU idles between polls instead of spinning
}
