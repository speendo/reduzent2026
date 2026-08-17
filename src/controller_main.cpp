#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_event.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

#include "espnow_frame.h"
#include "text_parser.h"

#define ESP_NOW_CHANNEL 13  // fixed WiFi channel; must match every leaf
#define LINE_BUF_LEN 64
#define LINE_QUEUE_LEN 4

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static QueueHandle_t line_q = NULL;     // completed text lines (copies, LINE_BUF_LEN each)
static SemaphoreHandle_t evt_sem = NULL;

static char line_buf[LINE_BUF_LEN];
static size_t line_len = 0;

// on_recv (WiFi task) may not do blocking serial I/O: buffer the frame, flag loop().
static volatile bool rx_pending = false;
static uint8_t rx_mac[6];
static int rx_len;
static espnow_frame_t rx_frame;

// No-op send callback: keeps ESP-NOW draining its send queue so esp_now_send
// does not stall once the buffer fills. Failed frames stay dropped (fire-and-forget).
static void on_send(const uint8_t* mac, esp_now_send_status_t status) {
    (void)mac;
    (void)status;
}

static void on_recv(const uint8_t* mac, const uint8_t* data, int len) {
    memcpy(rx_mac, mac, 6);
    rx_len = len;
    if (len == ESP_NOW_FRAME_SIZE) frame_unpack(data, &rx_frame);
    rx_pending = true;
    xSemaphoreGive(evt_sem);
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

// Called by the serial RX callback (task context for both HWCDC onEvent and
// classic UART onReceive) when a complete line is buffered. Copies the line
// into the queue and wakes loop(). A full queue drops the line; a line takes
// ~1 ms to arrive at 115200 baud, which loop() keeps up with easily.
static void on_line_complete(void) {
    xQueueSend(line_q, line_buf, 0);
    line_len = 0;
    xSemaphoreGive(evt_sem);
}

// Assemble buffered serial bytes into line_buf; hand completed lines to the
// queue. Runs in task context; touches only line_buf / line_len / the queue.
static void drain_serial(void) {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (line_len > 0) {
                line_buf[line_len] = '\0';
                on_line_complete();
            }
        } else if (line_len < LINE_BUF_LEN - 1) {
            line_buf[line_len++] = c;
        }
    }
}

#if ARDUINO_USB_CDC_ON_BOOT   // C3/S3: Serial is USB-CDC (HWCDC)
static void on_serial_event(void* arg, esp_event_base_t base, int32_t event_id, void* data) {
    (void)arg;
    (void)base;
    (void)data;
    if (event_id == ARDUINO_HW_CDC_RX_EVENT) drain_serial();
}
#else                                   // classic ESP32: Serial is UART0
static void on_serial_rx(void) { drain_serial(); }
#endif

void setup() {
    Serial.begin(115200);
    line_q = xQueueCreate(LINE_QUEUE_LEN, LINE_BUF_LEN);
    evt_sem = xSemaphoreCreateBinary();

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

#if ARDUINO_USB_CDC_ON_BOOT
    Serial.onEvent(ARDUINO_HW_CDC_RX_EVENT, on_serial_event);
#else
    Serial.onReceive(on_serial_rx);
#endif

    Serial.println("controller ready");
}

void loop() {
    // Block until a line or frame is ready, then handle it in task context.
    if (xSemaphoreTake(evt_sem, portMAX_DELAY) != pdTRUE) return;

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

    char line[LINE_BUF_LEN];
    while (xQueueReceive(line_q, line, 0) == pdTRUE) {
        handle_line(line);
    }
}
