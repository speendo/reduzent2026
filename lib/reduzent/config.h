#ifndef CONFIG_H
#define CONFIG_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Per-leaf settings. Loaded from NVS at boot; defaults if none stored.
typedef struct {
    uint8_t  channel;                 // MIDI channel 0-15 this leaf listens to
    uint8_t  actuator;                // 0 = piezo, 1 = solenoid
    uint8_t  gpio_piezo;              // piezo output pin
    uint8_t  gpio_solenoid;           // solenoid output pin
    uint16_t solenoid_note;           // MIDI note that triggers this solenoid
    uint16_t solenoid_hold_ms;        // coil energize duration (ms)
    uint8_t  solenoid_duty_min;       // duty at velocity 1
    uint8_t  solenoid_duty_max;       // duty at velocity 127
    uint8_t  piezo_pitch_bend_range;  // +/- semitones
    uint16_t piezo_adsr_attack_ms;    // ADSR attack (ms)
    uint16_t piezo_adsr_decay_ms;     // ADSR decay (ms)
    uint8_t  piezo_adsr_sustain_pct;  // ADSR sustain (0-100)
    uint16_t piezo_adsr_release_ms;   // ADSR release (ms)
    uint8_t  node_id;                 // 0-254, 255 = unassigned
    uint16_t settings_window_sec;     // settings-mode timeout; 0 = disabled
    uint8_t  espnow_channel;          // WiFi channel 1-14
} leaf_config_t;

// Controller settings. Loaded from NVS at boot; defaults if none stored.
typedef struct {
    uint8_t  espnow_channel;          // WiFi channel 1-14
    uint16_t settings_window_sec;     // boot settings window; 0 = skip
} controller_config_t;

// Simple byte-sum CRC. Appended as one trailing byte to every NVS blob so
// partial writes / flash wear are caught on load.
static inline uint8_t config_crc(const void* data, size_t len) {
    const uint8_t* b = (const uint8_t*)data;
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++) sum = (uint8_t)(sum + b[i]);
    return sum;
}

// Fill a config struct with the compile-time defaults. Dispatches on size:
// sizeof(leaf_config_t) or sizeof(controller_config_t); any other size is a
// no-op. The macro config_defaults(cfg) fills in the size from the argument;
// call sites write config_defaults(&cfg) to match the specs.
static inline void config_defaults_impl(void* cfg, size_t size) {
    if (size == sizeof(leaf_config_t)) {
        leaf_config_t* c = (leaf_config_t*)cfg;
        c->channel = 0;
        c->actuator = 0;
        c->gpio_piezo = 3;
        c->gpio_solenoid = 4;
        c->solenoid_note = 36;
        c->solenoid_hold_ms = 40;
        c->solenoid_duty_min = 40;
        c->solenoid_duty_max = 220;
        c->piezo_pitch_bend_range = 2;
        c->piezo_adsr_attack_ms = 5;
        c->piezo_adsr_decay_ms = 100;
        c->piezo_adsr_sustain_pct = 70;
        c->piezo_adsr_release_ms = 100;
        c->node_id = 255;
        c->settings_window_sec = 30;
        c->espnow_channel = 13;
    } else if (size == sizeof(controller_config_t)) {
        controller_config_t* c = (controller_config_t*)cfg;
        c->espnow_channel = 13;
        c->settings_window_sec = 30;
    }
}

#define config_defaults(cfg) config_defaults_impl((cfg), sizeof(*(cfg)))

#ifndef NATIVE_BUILD
#include <Preferences.h>

#define CONFIG_BLOB_MAX 64  // largest struct + CRC byte; both structs fit

static inline int config_load_impl(const char* key, void* cfg, size_t size) {
    uint8_t blob[CONFIG_BLOB_MAX];
    if (size + 1 > sizeof(blob)) return -1;
    Preferences p;
    if (!p.begin("instrument", true)) return -1;
    size_t got = p.getBytes(key, blob, size + 1);
    p.end();
    if (got != size + 1) return -1;              // missing or wrong size
    if (blob[size] != config_crc(blob, size)) return -1;  // CRC mismatch
    memcpy(cfg, blob, size);
    return 0;
}

static inline int config_save_impl(const char* key, const void* cfg, size_t size) {
    uint8_t blob[CONFIG_BLOB_MAX];
    if (size + 1 > sizeof(blob)) return -1;
    memcpy(blob, cfg, size);
    blob[size] = config_crc(cfg, size);
    Preferences p;
    if (!p.begin("instrument", false)) return -1;
    size_t written = p.putBytes(key, blob, size + 1);
    p.end();
    return written == size + 1 ? 0 : -1;
}

// Callers write config_load("leaf_cfg", &cfg); the macro fills in the size.
#define config_load(key, cfg) config_load_impl((key), (cfg), sizeof(*(cfg)))
#define config_save(key, cfg) config_save_impl((key), (cfg), sizeof(*(cfg)))
#endif

#endif
