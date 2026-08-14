#ifndef TEXT_PARSER_H
#define TEXT_PARSER_H

#include <stdint.h>
#include <stdio.h>
#include "espnow_frame.h"

// Parse one newline-terminated text command into a frame.
// Returns 1 and fills *out on success; 0 if blank/unrecognized/out of range.
// Commands: n <ch> <note> <vel> | x <ch> <note> | p <ch> <bend>
//           a <ch> <pressure> | pa <ch> <note> <pressure>
//           g <ch> <program> | v <ch> <depth> | panic | settings [<id>]
// Order matters: "panic" and "pa" are checked before "p".
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

    if (line[0] == 's' && line[1] == 'e' && line[2] == 't' &&
        line[3] == 't' && line[4] == 'i' && line[5] == 'n' &&
        line[6] == 'g' && line[7] == 's') {
        int id;
        out->channel = ESP_NOW_CHANNEL_BROADCAST; // always broadcast
        out->type = EVENT_ENTER_SETTINGS;
        out->note = 0xFF;   // target leaf id; 0xFF = all leaves
        out->value = 0;
        out->value_hi = 0;
        if (sscanf(line, "settings %d", &id) == 1) {
            if (id < 0 || id > 254) return 0;
            out->note = (uint8_t)id;
        }
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

    if (line[0] == 'p' && line[1] == 'a') {
        int ch, note, pressure;
        if (sscanf(line, "pa %d %d %d", &ch, &note, &pressure) != 3) return 0;
        if (ch < 0 || ch > 15 || note < 0 || note > 127 || pressure < 0 || pressure > 127) return 0;
        out->channel = (uint8_t)ch;
        out->type = EVENT_POLY_AFTERTOUCH;
        out->note = (uint8_t)note;
        out->value = (uint8_t)pressure;
        out->value_hi = 0;
        return 1;
    }

    if (line[0] == 'p') {
        int ch, bend;
        if (sscanf(line, "p %d %d", &ch, &bend) != 2) return 0;
        if (ch < 0 || ch > 15 || bend < 0 || bend > 16383) return 0;
        out->channel = (uint8_t)ch;
        out->type = EVENT_PITCH_BEND;
        out->note = 0;
        out->value = (uint8_t)(bend & 0x7F);
        out->value_hi = (uint8_t)((bend >> 7) & 0x7F);
        return 1;
    }

    if (line[0] == 'a') {
        int ch, pressure;
        if (sscanf(line, "a %d %d", &ch, &pressure) != 2) return 0;
        if (ch < 0 || ch > 15 || pressure < 0 || pressure > 127) return 0;
        out->channel = (uint8_t)ch;
        out->type = EVENT_CHANNEL_AFTERTOUCH;
        out->note = 0;
        out->value = (uint8_t)pressure;
        out->value_hi = 0;
        return 1;
    }

    if (line[0] == 'g') {
        int ch, program;
        if (sscanf(line, "g %d %d", &ch, &program) != 2) return 0;
        if (ch < 0 || ch > 15 || program < 0 || program > 127) return 0;
        out->channel = (uint8_t)ch;
        out->type = EVENT_PROGRAM_CHANGE;
        out->note = 0;
        out->value = (uint8_t)program;
        out->value_hi = 0;
        return 1;
    }

    if (line[0] == 'v') {
        int ch, depth;
        if (sscanf(line, "v %d %d", &ch, &depth) != 2) return 0;
        if (ch < 0 || ch > 15 || depth < 0 || depth > 127) return 0;
        out->channel = (uint8_t)ch;
        out->type = EVENT_CC1_VIBRATO;
        out->note = 0;
        out->value = (uint8_t)depth;
        out->value_hi = 0;
        return 1;
    }

    return 0;
}

#endif
