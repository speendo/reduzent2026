#ifndef CONFIG_PARSER_H
#define CONFIG_PARSER_H

#include <stdio.h>
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
