#ifndef WIFI_AP_H
#define WIFI_AP_H

#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>

// Enter settings mode: stop ESP-NOW first (the recv callback stops firing after
// deinit), switch to AP, and serve the settings UI on the given channel.
// MUST run in loop()/task context, never inside an ESP-NOW callback.
static inline void wifi_ap_start(const char* ssid, uint8_t channel) {
    esp_now_deinit();
    WiFi.mode(WIFI_AP);
    WiFi.softAP(ssid, NULL, channel);
}

// Leave settings mode: stop the AP, return to STA mode for ESP-NOW, and
// re-apply the ESP-NOW channel. A fresh STA start resets the radio to the
// default channel (1); without re-applying the channel, esp_now_send fails
// with "Peer channel is not equal to the home channel" because the broadcast
// peer is re-added with channel != 1. The country code and power-save setting
// persist across start/stop; the channel does not.
// Re-init of ESP-NOW (callbacks + broadcast peer) is the caller's job.
static inline void wifi_ap_stop(uint8_t channel) {
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    if (esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE) != ESP_OK) {
        Serial.println("set_channel failed");
    }
}

// Enable channels up to 13. The C3's default "world-safe" country code blocks
// active use of channel 13; must run after the WiFi stack is initialized.
static inline void wifi_set_country(const char* country_code) {
    esp_wifi_set_country_code(country_code, false);
}

#endif
