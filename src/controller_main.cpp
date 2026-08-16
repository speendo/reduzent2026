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

// Received-frame data buffered by on_recv (WiFi task) and flushed by loop():
// blocking serial I/O from the ESP-NOW callback is forbidden (docs + C3 USB CDC).
static volatile bool rx_pending = false;
static uint8_t rx_mac[6];
static int rx_len;
static espnow_frame_t rx_frame;

// No-op: registering a send callback keeps ESP-NOW draining its send queue,
// so esp_now_send does not stall once the buffer fills. Failed frames stay
// dropped (fire-and-forget).
static void on_send(const uint8_t* mac, esp_now_send_status_t status) {
    (void)mac;
    (void)status;
}

// Leaf heartbeats arrive here. The sender MAC is the leaf's identity for now.
static void on_recv(const uint8_t* mac, const uint8_t* data, int len) {
    memcpy(rx_mac, mac, 6);
    rx_len = len;
    if (len == ESP_NOW_FRAME_SIZE) {
        frame_unpack(data, &rx_frame);
    }
    rx_pending = true;
}

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
    esp_wifi_set_ps(WIFI_PS_NONE);  // never modem-sleep; keep broadcasts flowing
    esp_wifi_set_channel(ESP_NOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
        return;
    }
    esp_now_register_send_cb(on_send);
    esp_now_register_recv_cb(on_recv);

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
    if (rx_pending) {
        rx_pending = false;
        if (rx_len == ESP_NOW_FRAME_SIZE && rx_frame.type == EVENT_HEARTBEAT) {
            Serial.printf("hb %02x:%02x:%02x:%02x:%02x:%02x played=%u last=%us\n",
                          rx_mac[0], rx_mac[1], rx_mac[2], rx_mac[3], rx_mac[4], rx_mac[5],
                          (unsigned)rx_frame.note, (unsigned)rx_frame.value);
        } else {
            Serial.printf("rx len=%d type=%d mac=%02x:%02x:%02x:%02x:%02x:%02x\n",
                          rx_len,
                          rx_len == ESP_NOW_FRAME_SIZE ? rx_frame.type : -1,
                          rx_mac[0], rx_mac[1], rx_mac[2], rx_mac[3], rx_mac[4], rx_mac[5]);
        }
    }
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
