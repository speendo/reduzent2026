#ifndef SSID_H
#define SSID_H

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

// Build the settings-mode AP SSID into out (NUL-terminated, max len bytes).
// Controller (is_controller != 0): "reduzent-controller".
// Leaf: "reduzent-leaf-<node_id>" when node_id != 255, else
//       "reduzent-leaf-<MAC[4]><MAC[5]>" (uppercase hex) as a stable fallback
//       so an unassigned leaf still gets a unique AP name.
static inline void ssid_build(char* out, size_t len, int is_controller,
                              uint8_t node_id, const uint8_t mac[6]) {
    if (is_controller) {
        snprintf(out, len, "reduzent-controller");
    } else if (node_id != 255) {
        snprintf(out, len, "reduzent-leaf-%u", (unsigned)node_id);
    } else {
        snprintf(out, len, "reduzent-leaf-%02X%02X", mac[4], mac[5]);
    }
}

#endif
