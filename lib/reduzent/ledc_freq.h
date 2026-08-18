#ifndef LEDC_FREQ_H
#define LEDC_FREQ_H

#include <stdint.h>

// ESP32-C3 LEDC timer limits (IDF 4.4.7 driver, ledc.c):
// - divider register is 18 bits wide (max 0x3FFFF) with 8 fractional bits
// - a divider is valid iff: 255 < div <= 0x3FFFF
// - div = ((src_clk << 8) + rounding) / (freq * precision), precision = 2^res
// Higher duty resolution lowers the divider for the same frequency, so low
// notes need HIGH resolution and high notes need LOW resolution. We pick the
// LOWEST resolution that still fits the divider: the divider is then largest,
// so divider rounding perturbs the frequency least (finest pitch accuracy).
// Duty amplitude is 7-bit anyway (set_duty shifts a 0-127 level), so nothing
// audible is lost by keeping resolution as small as possible.
#define LEDC_DIV_FRACTIONAL_BITS 8
#define LEDC_DIV_MIN 255
#define LEDC_DIV_MAX 0x3FFFFu
#define LEDC_RES_MIN 8
#define LEDC_RES_MAX 14  // ESP32-C3 max duty resolution (SOC_LEDC_TIMER_BIT_WIDE_NUM)

// Lowest duty resolution (bits) at which `freq_hz` can be produced from
// `src_clk_hz` without overflowing the LEDC divider field. Returns 0 if no
// resolution in [LEDC_RES_MIN, LEDC_RES_MAX] works.
static inline uint8_t ledc_resolution_for(uint32_t src_clk_hz, uint32_t freq_hz) {
    if (freq_hz == 0) return 0;
    for (uint8_t res = LEDC_RES_MIN; res <= LEDC_RES_MAX; res++) {
        uint64_t precision = 1u << res;
        uint64_t num = ((uint64_t)src_clk_hz << LEDC_DIV_FRACTIONAL_BITS)
                     + ((uint64_t)freq_hz * precision) / 2;
        uint64_t den = (uint64_t)freq_hz * precision;
        uint64_t div = num / den;
        if (div > LEDC_DIV_MIN && div <= LEDC_DIV_MAX) return res;
    }
    return 0;
}

#endif
