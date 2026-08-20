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
#include "held_notes.h"
#include "mode.h"
#include "ssid.h"
#include "wifi_ap.h"
#include <ESPAsyncWebServer.h>
#include "parasol_setup.h"
#include "config.h"
#include "config_parser.h"

#define KEEPALIVE_INTERVAL_MS 750  // X / Y (3000 / 4)
#define LINE_BUF_LEN 64
#define LINE_QUEUE_LEN 4

static const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static QueueHandle_t line_q = NULL;     // completed text lines (copies, LINE_BUF_LEN each)
static SemaphoreHandle_t evt_sem = NULL;

static char line_buf[LINE_BUF_LEN];
static size_t line_len = 0;
static held_notes_t held;
static controller_config_t cfg;   // loaded from NVS in setup(); defaults if none
static mode_state_t dev_mode;          // settings/live state machine
static char ap_ssid[32];               // settings-mode AP SSID
static device_mode_t last_hw_mode = MODE_LIVE;  // WiFi/ESP-NOW state matching dev_mode.mode
static AsyncWebServer server(80);
static bool parasol_initialized = false;
static volatile bool leave_settings_request = false;

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

static void transmit_redundant(const espnow_frame_t* f, int copies) {
    for (int i = 0; i < copies; i++) transmit(f);
}

static void handle_line(const char* line) {
    char out[128];
    cfg_action_t action = config_handle_line(line, &cfg, out, sizeof(out));
    if (action != CFG_NONE) {
        if (action == CFG_SAVE && config_save("ctrl_cfg", &cfg) != 0) {
            snprintf(out, sizeof(out), "error: save failed\n");
        }
        Serial.print(out);
        return;
    }

    espnow_frame_t frame;
    if (!parse_command(line, &frame)) return;

    switch (frame.type) {
        case EVENT_NOTE:
            if (frame.value == 0) held_clear(&held, frame.channel, frame.note);
            else held_set(&held, frame.channel, frame.note, frame.value);
            transmit(&frame);
            break;
        case EVENT_PANIC:
        case EVENT_NOTES_OFF:
            if (frame.channel == ESP_NOW_CHANNEL_BROADCAST) held_clear_all(&held);
            else held_clear_channel(&held, frame.channel);
            transmit_redundant(&frame, 3);
            break;
        case EVENT_ENTER_SETTINGS:
            transmit(&frame);           // broadcast/target leaves (was the default case)
            mode_enter_settings(&dev_mode, millis());
            break;
        default:
            transmit(&frame);
            break;
    }

    Serial.printf("[%lu] tx ch=%d type=%d note=%d value=%d\n",
                  millis(), frame.channel, frame.type, frame.note, frame.value);
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

// WiFi AP client tracking — feeds mode_set_clients for timeout pausing.
static void on_wifi_event(void* arg, esp_event_base_t base, int32_t id, void* data) {
    if (base == WIFI_EVENT && (id == WIFI_EVENT_AP_STACONNECTED || id == WIFI_EVENT_AP_STADISCONNECTED)) {
        mode_set_clients(&dev_mode, WiFi.softAPgetStationNum(), millis());
    }
}

// parasol save callback: check the _leave_settings switch, then save config.
static esp_err_t ctrl_save_with_leave(void) {
    const char *v = prsl_get("_system._leave_settings");
    if (v && strcmp(v, "1") == 0) leave_settings_request = true;
    return parasol_save_controller_to_nvs();
}

// Live -> Settings: bring up the controller's own settings AP.
static void enter_settings_mode(void) {
    wifi_ap_start(ap_ssid, cfg.espnow_channel);
    esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_AP_STACONNECTED, on_wifi_event, NULL);
    esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_AP_STADISCONNECTED, on_wifi_event, NULL);
    if (!parasol_initialized) {
        parasol_register_controller_fields();
        prsl_init(&server, ctrl_save_with_leave, parasol_load_controller_from_nvs, NULL);
        parasol_initialized = true;
    }
    parasol_load_controller_from_nvs();
    prsl_start();
}

// Settings -> Live: tear down the AP and restore ESP-NOW for live operation.
static void exit_settings_mode(void) {
    server.end();
    WiFi.mode(WIFI_OFF);
    wifi_ap_stop();
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
    }
    esp_now_register_send_cb(on_send);
    esp_now_register_recv_cb(on_recv);
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = cfg.espnow_channel;
    peer.ifidx = WIFI_IF_STA;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("esp_now_add_peer failed");
    }
}

void setup() {
    Serial.begin(115200);
    config_defaults(&cfg);
    config_load("ctrl_cfg", &cfg);
    line_q = xQueueCreate(LINE_QUEUE_LEN, LINE_BUF_LEN);
    evt_sem = xSemaphoreCreateBinary();

    WiFi.mode(WIFI_STA);
    wifi_set_country("EU");
    esp_wifi_set_ps(WIFI_PS_NONE);  // never modem-sleep; keep broadcasts flowing
    esp_wifi_set_channel(cfg.espnow_channel, WIFI_SECOND_CHAN_NONE);
    if (esp_now_init() != ESP_OK) {
        Serial.println("esp_now_init failed");
        return;
    }
    esp_now_register_send_cb(on_send);
    esp_now_register_recv_cb(on_recv);

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, BROADCAST_MAC, 6);
    peer.channel = cfg.espnow_channel;
    peer.ifidx = WIFI_IF_STA;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("add_peer failed");
    }

#if ARDUINO_USB_CDC_ON_BOOT
    Serial.onEvent(ARDUINO_HW_CDC_RX_EVENT, on_serial_event);
#else
    Serial.onReceive(on_serial_rx);
#endif

    held_notes_init(&held);
    mode_init(&dev_mode, (uint32_t)cfg.settings_window_sec * 1000);
    uint8_t mac[6];
    WiFi.macAddress(mac);
    ssid_build(ap_ssid, sizeof(ap_ssid), 1, 0, mac);
    if (mode_boot(&dev_mode, millis())) enter_settings_mode();
    last_hw_mode = dev_mode.mode;

    Serial.println("controller ready");
}

static void send_keepalive(void) {
    espnow_frame_t frame;
    frame.type = EVENT_NOTE_HOLD;
    frame.value_hi = 0;
    uint16_t cursor = 0;
    uint8_t ch, note, vel;
    while (held_next(&held, &cursor, &ch, &note, &vel)) {
        frame.channel = ch;
        frame.note = note;
        frame.value = vel;
        transmit(&frame);
    }
}

void loop() {
    // Wake on any event, or at least every KEEPALIVE_INTERVAL_MS so the
    // held-note keepalive fires even while the link is idle. Without the
    // timeout, loop() never wakes during a silently held note and the leaf
    // watchdog would cut it off.
    xSemaphoreTake(evt_sem, pdMS_TO_TICKS(KEEPALIVE_INTERVAL_MS));

    static uint32_t next_keepalive = 0; // first keepalive fires at boot (no-op)
    uint32_t now = millis();
    if (leave_settings_request && mode_is_settings(&dev_mode)) {
        mode_request_exit(&dev_mode);
        leave_settings_request = false;
    }
    mode_tick(&dev_mode, now);
    if (dev_mode.mode != last_hw_mode) {
        if (mode_is_settings(&dev_mode)) enter_settings_mode();
        else exit_settings_mode();
        last_hw_mode = dev_mode.mode;
    }

    if (!mode_is_settings(&dev_mode)) {
        if ((int32_t)(now - next_keepalive) >= 0) {
            send_keepalive();
            next_keepalive = now + KEEPALIVE_INTERVAL_MS;
        }

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
    }

    char line[LINE_BUF_LEN];
    while (xQueueReceive(line_q, line, 0) == pdTRUE) {
        handle_line(line);
    }
}
