#ifndef TEXT_PARSER_H
#define TEXT_PARSER_H

#include <stdint.h>
#include <stdio.h>
#include "espnow_frame.h"

// Parse one newline-terminated text command into a frame.
// Returns 1 and fills *out on success; 0 if blank/unrecognized/out of range.
static inline int parse_command(const char* line, espnow_frame_t* out) {
    if (!line || !out) return 0;

    if (line[0] == 'p' && line[1] == 'a' && line[2] == 'n' &&
        line[3] == 'i' && line[4] == 'c') {
        out->channel = ESP_NOW_CHANNEL_BROADCAST;
        out->type = EVENT_PANIC;
        out->note = 0;
        out->value = 0;
        out->value_hi = 0;
        return 1;
    }

    if (line[0] == 'n') {
        int ch, note, vel;
        if (sscanf(line, "n %d %d %d", &ch, &note, &vel) != 3) return 0;
        if (ch < 0 || ch > 15 || note < 0 || note > 127 || vel < 0 || vel > 127) return 0;
        out->channel = (uint8_t)ch;
        out->type = EVENT_NOTE;
        out->note = (uint8_t)note;
        out->value = (uint8_t)vel;
        out->value_hi = 0;
        return 1;
    }

    if (line[0] == 'x') {
        int ch, note;
        if (sscanf(line, "x %d %d", &ch, &note) != 2) return 0;
        if (ch < 0 || ch > 15 || note < 0 || note > 127) return 0;
        out->channel = (uint8_t)ch;
        out->type = EVENT_NOTE;
        out->note = (uint8_t)note;
        out->value = 0; // note off
        out->value_hi = 0;
        return 1;
    }

    return 0;
}

#endif
