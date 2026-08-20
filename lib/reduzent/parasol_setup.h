#ifndef PARASOL_SETUP_H
#define PARASOL_SETUP_H

#include "prsl.h"
#include "config.h"
#include "config_parser.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

// ── Actuator enum names ──────────────────────────────────────────
static const char *actuator_opts[][2] = {
    {"0", "Piezo"},
    {"1", "Solenoid"},
};

// ── Shared on_set callback ──────────────────────────────────────
// parasol does not update the store when a field registers on_set: the
// callback must validate the value, write it into the store, and mark the
// settings dirty so the browser's Save button appears and the save POST
// actually fires (the client only POSTs while the server reports dirty).
static inline esp_err_t parasol_on_field_change(const char* group_id, const char* key,
                                                const char* value) {
    if (config_reject_field(key, value) != 0) return ESP_ERR_INVALID_ARG;
    char path[64];
    snprintf(path, sizeof(path), "%s.%s", group_id, key);
    prsl_set_str(path, value);
    prsl_set_dirty(true);
    return ESP_OK;
}

// Store an integer as a string. prsl_get() only returns string-typed values,
// so values set via prsl_set_int() (JSON numbers) would read back as NULL in
// the save callback and silently fall back to compile-time defaults.
static inline void prsl_set_int_as_str(const char* path, int value) {
    char buf[16];
    snprintf(buf, sizeof(buf), "%d", value);
    prsl_set_str(path, buf);
}

// ── Leaf field registration ──────────────────────────────────────
static inline void parasol_register_leaf_fields(void) {
    // Network
    prsl_add_group("network", "Network");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "WiFi channel 1-14", .attrs = "{'min':1,'max':14}" };
      prsl_add_field(PRSL_NUMBER, "network", "espnow_channel", "ESP-NOW Channel", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "0-300 seconds; 0 = disabled", .attrs = "{'min':0,'max':300}" };
      prsl_add_field(PRSL_NUMBER, "network", "settings_window_sec", "Settings Window (s)", &o); }

    // Leaf identity
    prsl_add_group("leaf", "Leaf");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "0-254; 255 = unassigned", .attrs = "{'min':0,'max':254}" };
      prsl_add_field(PRSL_NUMBER, "leaf", "node_id", "Node ID", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "0-15", .attrs = "{'min':0,'max':15}" };
      prsl_add_field(PRSL_NUMBER, "leaf", "channel", "MIDI Channel", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change };
      prsl_add_field_opts(PRSL_SELECT, "leaf", "actuator", "Actuator Type",
          actuator_opts, 2, &o); }

    // GPIO
    prsl_add_group("gpio", "Pin Configuration");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "GPIO 0-28", .attrs = "{'min':0,'max':28}" };
      prsl_add_field(PRSL_NUMBER, "gpio", "gpio_piezo", "Piezo Pin", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "GPIO 0-28", .attrs = "{'min':0,'max':28}" };
      prsl_add_field(PRSL_NUMBER, "gpio", "gpio_solenoid", "Solenoid Pin", &o); }

    // Solenoid
    prsl_add_group("solenoid", "Solenoid");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "MIDI note 0-127", .attrs = "{'min':0,'max':127}" };
      prsl_add_field(PRSL_NUMBER, "solenoid", "solenoid_note", "Note Number", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "10-500 ms", .attrs = "{'min':10,'max':500}" };
      prsl_add_field(PRSL_NUMBER, "solenoid", "solenoid_hold_ms", "Hold Duration (ms)", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "PWM duty 0-255 at velocity 1", .attrs = "{'min':0,'max':255}" };
      prsl_add_field(PRSL_NUMBER, "solenoid", "solenoid_duty_min", "Min Duty", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "PWM duty 0-255 at velocity 127", .attrs = "{'min':0,'max':255}" };
      prsl_add_field(PRSL_NUMBER, "solenoid", "solenoid_duty_max", "Max Duty", &o); }

    // Piezo
    prsl_add_group("piezo", "Piezo");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "Semitones +/-", .attrs = "{'min':1,'max':24}" };
      prsl_add_field(PRSL_NUMBER, "piezo", "piezo_pitch_bend_range", "Pitch Bend Range", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .attrs = "{'min':0,'max':5000}" };
      prsl_add_field(PRSL_NUMBER, "piezo", "piezo_adsr_attack_ms", "Attack (ms)", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .attrs = "{'min':0,'max':5000}" };
      prsl_add_field(PRSL_NUMBER, "piezo", "piezo_adsr_decay_ms", "Decay (ms)", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .attrs = "{'min':0,'max':100}" };
      prsl_add_field(PRSL_NUMBER, "piezo", "piezo_adsr_sustain_pct", "Sustain (%)", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .attrs = "{'min':0,'max':5000}" };
      prsl_add_field(PRSL_NUMBER, "piezo", "piezo_adsr_release_ms", "Release (ms)", &o); }

    // System (underscore key = internal, not persisted to NVS). Group id must
    // NOT start with an underscore: parasol's browser filters those out.
    prsl_add_group("system", "System");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change };
      prsl_add_field(PRSL_SWITCH, "system", "_leave_settings", "Leave Settings Mode", &o); }
}

// ── Controller field registration ────────────────────────────────
static inline void parasol_register_controller_fields(void) {
    prsl_add_group("network", "Network");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "WiFi channel 1-14", .attrs = "{'min':1,'max':14}" };
      prsl_add_field(PRSL_NUMBER, "network", "espnow_channel", "ESP-NOW Channel", &o); }
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change, .help = "0-300 seconds; 0 = skip at boot", .attrs = "{'min':0,'max':300}" };
      prsl_add_field(PRSL_NUMBER, "network", "settings_window_sec", "Settings Window (s)", &o); }

    // System (underscore key = internal, not persisted to NVS)
    prsl_add_group("system", "System");
    { static const prsl_field_opts_t o = { .on_set = parasol_on_field_change };
      prsl_add_field(PRSL_SWITCH, "system", "_leave_settings", "Leave Settings Mode", &o); }
}

// ── NVS save callback (leaf) ─────────────────────────────────────
// Reads parasol field values, validates, writes to config struct, persists.
static inline esp_err_t parasol_save_leaf_to_nvs(void) {
    leaf_config_t cfg;
    config_defaults(&cfg);

    const char *v;
    v = prsl_get("network.espnow_channel");     if (v) { if (config_validate_field("espnow_channel", v) != 0) return ESP_ERR_INVALID_ARG; cfg.espnow_channel = (uint8_t)atoi(v); }
    v = prsl_get("network.settings_window_sec"); if (v) { if (config_validate_field("settings_window_sec", v) != 0) return ESP_ERR_INVALID_ARG; cfg.settings_window_sec = (uint16_t)atoi(v); }
    v = prsl_get("leaf.node_id");               if (v) { if (config_validate_field("node_id", v) != 0) return ESP_ERR_INVALID_ARG; cfg.node_id = (uint8_t)atoi(v); }
    v = prsl_get("leaf.channel");               if (v) { if (config_validate_field("channel", v) != 0) return ESP_ERR_INVALID_ARG; cfg.channel = (uint8_t)atoi(v); }
    v = prsl_get("leaf.actuator");              if (v) { if (config_validate_field("actuator", v) != 0) return ESP_ERR_INVALID_ARG; cfg.actuator = (uint8_t)atoi(v); }
    v = prsl_get("gpio.gpio_piezo");            if (v) { if (config_validate_field("gpio_piezo", v) != 0) return ESP_ERR_INVALID_ARG; cfg.gpio_piezo = (uint8_t)atoi(v); }
    v = prsl_get("gpio.gpio_solenoid");         if (v) { if (config_validate_field("gpio_solenoid", v) != 0) return ESP_ERR_INVALID_ARG; cfg.gpio_solenoid = (uint8_t)atoi(v); }
    v = prsl_get("solenoid.solenoid_note");      if (v) { if (config_validate_field("solenoid_note", v) != 0) return ESP_ERR_INVALID_ARG; cfg.solenoid_note = (uint16_t)atoi(v); }
    v = prsl_get("solenoid.solenoid_hold_ms");   if (v) { if (config_validate_field("solenoid_hold_ms", v) != 0) return ESP_ERR_INVALID_ARG; cfg.solenoid_hold_ms = (uint16_t)atoi(v); }
    v = prsl_get("solenoid.solenoid_duty_min");  if (v) { if (config_validate_field("solenoid_duty_min", v) != 0) return ESP_ERR_INVALID_ARG; cfg.solenoid_duty_min = (uint8_t)atoi(v); }
    v = prsl_get("solenoid.solenoid_duty_max");  if (v) { if (config_validate_field("solenoid_duty_max", v) != 0) return ESP_ERR_INVALID_ARG; cfg.solenoid_duty_max = (uint8_t)atoi(v); }
    v = prsl_get("piezo.piezo_pitch_bend_range"); if (v) { if (config_validate_field("piezo_pitch_bend_range", v) != 0) return ESP_ERR_INVALID_ARG; cfg.piezo_pitch_bend_range = (uint8_t)atoi(v); }
    v = prsl_get("piezo.piezo_adsr_attack_ms");  if (v) { if (config_validate_field("piezo_adsr_attack_ms", v) != 0) return ESP_ERR_INVALID_ARG; cfg.piezo_adsr_attack_ms = (uint16_t)atoi(v); }
    v = prsl_get("piezo.piezo_adsr_decay_ms");   if (v) { if (config_validate_field("piezo_adsr_decay_ms", v) != 0) return ESP_ERR_INVALID_ARG; cfg.piezo_adsr_decay_ms = (uint16_t)atoi(v); }
    v = prsl_get("piezo.piezo_adsr_sustain_pct"); if (v) { if (config_validate_field("piezo_adsr_sustain_pct", v) != 0) return ESP_ERR_INVALID_ARG; cfg.piezo_adsr_sustain_pct = (uint8_t)atoi(v); }
    v = prsl_get("piezo.piezo_adsr_release_ms"); if (v) { if (config_validate_field("piezo_adsr_release_ms", v) != 0) return ESP_ERR_INVALID_ARG; cfg.piezo_adsr_release_ms = (uint16_t)atoi(v); }

    return config_save("leaf_cfg", &cfg) == 0 ? ESP_OK : ESP_FAIL;
}

// ── NVS save callback (controller) ───────────────────────────────
static inline esp_err_t parasol_save_controller_to_nvs(void) {
    controller_config_t cfg;
    config_defaults(&cfg);

    const char *v;
    v = prsl_get("network.espnow_channel");     if (v) { if (config_validate_field("espnow_channel", v) != 0) return ESP_ERR_INVALID_ARG; cfg.espnow_channel = (uint8_t)atoi(v); }
    v = prsl_get("network.settings_window_sec"); if (v) { if (config_validate_field("settings_window_sec", v) != 0) return ESP_ERR_INVALID_ARG; cfg.settings_window_sec = (uint16_t)atoi(v); }

    return config_save("ctrl_cfg", &cfg) == 0 ? ESP_OK : ESP_FAIL;
}

// ── NVS load callback (leaf) ─────────────────────────────────────
// Loads from NVS and pushes values into parasol fields. Values are stored as
// strings (prsl_set_str) because prsl_get() only returns string values.
static inline esp_err_t parasol_load_leaf_from_nvs(void) {
    leaf_config_t cfg;
    config_defaults(&cfg);
    config_load("leaf_cfg", &cfg);

    prsl_set_int_as_str("network.espnow_channel", cfg.espnow_channel);
    prsl_set_int_as_str("network.settings_window_sec", cfg.settings_window_sec);
    prsl_set_int_as_str("leaf.node_id", cfg.node_id);
    prsl_set_int_as_str("leaf.channel", cfg.channel);
    prsl_set_int_as_str("leaf.actuator", cfg.actuator);
    prsl_set_int_as_str("gpio.gpio_piezo", cfg.gpio_piezo);
    prsl_set_int_as_str("gpio.gpio_solenoid", cfg.gpio_solenoid);
    prsl_set_int_as_str("solenoid.solenoid_note", cfg.solenoid_note);
    prsl_set_int_as_str("solenoid.solenoid_hold_ms", cfg.solenoid_hold_ms);
    prsl_set_int_as_str("solenoid.solenoid_duty_min", cfg.solenoid_duty_min);
    prsl_set_int_as_str("solenoid.solenoid_duty_max", cfg.solenoid_duty_max);
    prsl_set_int_as_str("piezo.piezo_pitch_bend_range", cfg.piezo_pitch_bend_range);
    prsl_set_int_as_str("piezo.piezo_adsr_attack_ms", cfg.piezo_adsr_attack_ms);
    prsl_set_int_as_str("piezo.piezo_adsr_decay_ms", cfg.piezo_adsr_decay_ms);
    prsl_set_int_as_str("piezo.piezo_adsr_sustain_pct", cfg.piezo_adsr_sustain_pct);
    prsl_set_int_as_str("piezo.piezo_adsr_release_ms", cfg.piezo_adsr_release_ms);

    prsl_set_dirty(false);  // values now match NVS (covers parasol Reset)
    prsl_push();
    return ESP_OK;
}

// ── NVS load callback (controller) ───────────────────────────────
static inline esp_err_t parasol_load_controller_from_nvs(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    config_load("ctrl_cfg", &cfg);

    prsl_set_int_as_str("network.espnow_channel", cfg.espnow_channel);
    prsl_set_int_as_str("network.settings_window_sec", cfg.settings_window_sec);

    prsl_set_dirty(false);  // values now match NVS (covers parasol Reset)
    prsl_push();
    return ESP_OK;
}

#endif
