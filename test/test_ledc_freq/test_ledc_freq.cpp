#include <unity.h>
#include "note_freq.h"
#include "ledc_freq.h"

void setUp(void) {}
void tearDown(void) {}

#define TEST_XTAL 40000000u

void test_every_midi_note_has_valid_resolution(void) {
    for (int n = 0; n < 128; n++) {
        uint8_t res = ledc_resolution_for(TEST_XTAL, note_to_freq((uint8_t)n));
        TEST_ASSERT_TRUE(res >= 8 && res <= 14);
    }
}

void test_resolution_boundaries(void) {
    // Lowest valid resolution wins: high notes use 8 bits (fine pitch), low
    // notes raise only as far as needed to fit the LEDC divider.
    TEST_ASSERT_EQUAL_UINT8(13, ledc_resolution_for(TEST_XTAL, 8));      // note 0
    TEST_ASSERT_EQUAL_UINT8(13, ledc_resolution_for(TEST_XTAL, 9));      // note 2
    TEST_ASSERT_EQUAL_UINT8(12, ledc_resolution_for(TEST_XTAL, 10));     // note 3
    TEST_ASSERT_EQUAL_UINT8(12, ledc_resolution_for(TEST_XTAL, 19));     // note 15
    TEST_ASSERT_EQUAL_UINT8(11, ledc_resolution_for(TEST_XTAL, 21));     // note 16
    TEST_ASSERT_EQUAL_UINT8(11, ledc_resolution_for(TEST_XTAL, 37));     // note 26
    TEST_ASSERT_EQUAL_UINT8(10, ledc_resolution_for(TEST_XTAL, 39));     // note 27
    TEST_ASSERT_EQUAL_UINT8(10, ledc_resolution_for(TEST_XTAL, 73));     // note 38
    TEST_ASSERT_EQUAL_UINT8(9,  ledc_resolution_for(TEST_XTAL, 78));     // note 39
    TEST_ASSERT_EQUAL_UINT8(9,  ledc_resolution_for(TEST_XTAL, 147));    // note 50
    TEST_ASSERT_EQUAL_UINT8(8,  ledc_resolution_for(TEST_XTAL, 156));    // note 51
    TEST_ASSERT_EQUAL_UINT8(8,  ledc_resolution_for(TEST_XTAL, 165));    // note 52
    TEST_ASSERT_EQUAL_UINT8(8,  ledc_resolution_for(TEST_XTAL, 2349));   // note 98
    TEST_ASSERT_EQUAL_UINT8(8,  ledc_resolution_for(TEST_XTAL, 12544));  // note 127
}

void test_zero_and_tiny_freq_return_zero(void) {
    TEST_ASSERT_EQUAL_UINT8(0, ledc_resolution_for(TEST_XTAL, 0));
    TEST_ASSERT_EQUAL_UINT8(0, ledc_resolution_for(TEST_XTAL, 1));
}

void test_duty_shift_never_hits_max_duty_quirk(void) {
    // C3 cannot reach 100% duty at max resolution; the shifted duty must stay
    // strictly below (1 << res). 127 << (res-7) must be <= (1 << res) - 1.
    for (int n = 0; n < 128; n++) {
        uint8_t res = ledc_resolution_for(TEST_XTAL, note_to_freq((uint8_t)n));
        uint32_t used = 127u << (res - 7);
        uint32_t max_duty = (1u << res) - 1u;
        TEST_ASSERT_TRUE(used <= max_duty);
    }
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_every_midi_note_has_valid_resolution);
    RUN_TEST(test_resolution_boundaries);
    RUN_TEST(test_zero_and_tiny_freq_return_zero);
    RUN_TEST(test_duty_shift_never_hits_max_duty_quirk);
    return UNITY_END();
}
