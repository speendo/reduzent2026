#ifndef CONFIG_PARSER_H
#define CONFIG_PARSER_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "config.h"

// What a parsed cfg* command asks the caller to do.
typedef enum {
    CFG_NONE = 0,  // not a cfg* command; caller may try another parser
    CFG_GET,       // cfgget  — out already holds the key=value dump
    CFG_SET,       // cfgset  — applied to cfg; out holds confirmation/error
    CFG_SAVE,      // cfgsave — caller must persist cfg to NVS
    CFG_RESET,     // cfgreset — cfg reset to defaults; out holds the dump
} cfg_action_t;

// Validate a single config field value. Returns 0 if valid, -1 if invalid
// key or out-of-range value. Used by both cfgset and parasol save callback.
static inline int config_validate_field(const char* key, const char* value) {
    char* end;
    long v = strtol(value, &end, 10);
    if (*end != '\0' && *end != '\n' && *end != ' ') return -1;  // not a number

    if (strcmp(key, "espnow_channel") == 0) {
        return (v >= 1 && v <= 14) ? 0 : -1;
    } else if (strcmp(key, "settings_window_sec") == 0) {
        return (v >= 0 && v <= 300) ? 0 : -1;
    } else if (strcmp(key, "channel") == 0) {
        return (v >= 0 && v <= 15) ? 0 : -1;
    } else if (strcmp(key, "actuator") == 0) {
        return (v == 0 || v == 1) ? 0 : -1;
    } else if (strcmp(key, "node_id") == 0) {
        return (v >= 0 && v <= 254) ? 0 : -1;
    } else if (strcmp(key, "gpio_piezo") == 0 || strcmp(key, "gpio_solenoid") == 0) {
        return (v >= 0 && v <= 28) ? 0 : -1;
    } else if (strcmp(key, "solenoid_note") == 0) {
        return (v >= 0 && v <= 127) ? 0 : -1;
    } else if (strcmp(key, "solenoid_hold_ms") == 0) {
        return (v >= 10 && v <= 500) ? 0 : -1;
    } else if (strcmp(key, "solenoid_duty_min") == 0 || strcmp(key, "solenoid_duty_max") == 0) {
        return (v >= 0 && v <= 255) ? 0 : -1;
    } else if (strcmp(key, "piezo_pitch_bend_range") == 0) {
        return (v >= 1 && v <= 24) ? 0 : -1;
    } else if (strcmp(key, "piezo_adsr_attack_ms") == 0 || strcmp(key, "piezo_adsr_decay_ms") == 0 ||
               strcmp(key, "piezo_adsr_release_ms") == 0) {
        return (v >= 0 && v <= 5000) ? 0 : -1;
    } else if (strcmp(key, "piezo_adsr_sustain_pct") == 0) {
        return (v >= 0 && v <= 100) ? 0 : -1;
    }
    return -1;  // unknown key
}

// Handle one serial line. If `line` is a cfg* command, apply its effect to
// `cfg` and write the response (key=value lines or an error) into `out`,
// returning the action. Non-cfg lines return CFG_NONE and touch nothing.
static inline cfg_action_t config_handle_line(const char* line,
                                              controller_config_t* cfg,
                                              char* out, size_t out_len) {
    if (!line || !cfg || !out || out_len == 0) return CFG_NONE;

    if (line[0] == 'c' && line[1] == 'f' && line[2] == 'g' && line[3] == 'g' &&
        line[4] == 'e' && line[5] == 't' &&
        (line[6] == '\0' || line[6] == '\n')) {
        snprintf(out, out_len, "espnow_channel=%u\nsettings_window_sec=%u\n",
                 (unsigned)cfg->espnow_channel, (unsigned)cfg->settings_window_sec);
        return CFG_GET;
    }

    if (line[0] == 'c' && line[1] == 'f' && line[2] == 'g' && line[3] == 's' &&
        line[4] == 'a' && line[5] == 'v' && line[6] == 'e' &&
        (line[7] == '\0' || line[7] == '\n')) {
        snprintf(out, out_len, "saved\n");
        return CFG_SAVE;
    }

    if (line[0] == 'c' && line[1] == 'f' && line[2] == 'g' && line[3] == 'r' &&
        line[4] == 'e' && line[5] == 's' && line[6] == 'e' && line[7] == 't' &&
        (line[8] == '\0' || line[8] == '\n')) {
        config_defaults(cfg);
        snprintf(out, out_len, "espnow_channel=%u\nsettings_window_sec=%u\n",
                 (unsigned)cfg->espnow_channel, (unsigned)cfg->settings_window_sec);
        return CFG_RESET;
    }

    if (line[0] == 'c' && line[1] == 'f' && line[2] == 'g' && line[3] == 's' &&
        line[4] == 'e' && line[5] == 't' &&
        (line[6] == '\0' || line[6] == '\n' || line[6] == ' ')) {
        if (line[6] != ' ') {
            snprintf(out, out_len, "error: missing argument\n");
            return CFG_SET;
        }
        char key[24];
        long value;
        if (sscanf(line, "cfgset %23s %ld", key, &value) != 2) {
            snprintf(out, out_len, "error: missing argument\n");
            return CFG_SET;
        }
        if (strcmp(key, "espnow_channel") == 0) {
            if (value < 1 || value > 14) {
                snprintf(out, out_len, "error: value out of range\n");
            } else {
                cfg->espnow_channel = (uint8_t)value;
                snprintf(out, out_len, "espnow_channel=%u\n",
                         (unsigned)cfg->espnow_channel);
            }
            return CFG_SET;
        }
        if (strcmp(key, "settings_window_sec") == 0) {
            if (value < 0 || value > 300) {
                snprintf(out, out_len, "error: value out of range\n");
            } else {
                cfg->settings_window_sec = (uint16_t)value;
                snprintf(out, out_len, "settings_window_sec=%u\n",
                         (unsigned)cfg->settings_window_sec);
            }
            return CFG_SET;
        }
        snprintf(out, out_len, "error: unknown key\n");
        return CFG_SET;
    }

    return CFG_NONE;
}

#endif
