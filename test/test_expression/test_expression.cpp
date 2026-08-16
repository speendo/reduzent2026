#include <unity.h>
#include "expression.h"

void setUp(void) {}
void tearDown(void) {}

void test_pitch_bend_cents(void) {
    TEST_ASSERT_EQUAL_INT16(0, pitch_bend_cents(8192, 2));
    TEST_ASSERT_EQUAL_INT16(-200, pitch_bend_cents(0, 2));
    TEST_ASSERT_EQUAL_INT16(199, pitch_bend_cents(16383, 2));
    TEST_ASSERT_EQUAL_INT16(100, pitch_bend_cents(12288, 2)); // +1 semitone
    TEST_ASSERT_EQUAL_INT16(0, pitch_bend_cents(8192, 12));   // range-independent center
}

void test_pitch_bend_range_scales(void) {
    TEST_ASSERT_EQUAL_INT16(-1200, pitch_bend_cents(0, 12));   // 12 semitones
    TEST_ASSERT_EQUAL_INT16(600, pitch_bend_cents(12288, 12)); // +6 semitones
}

void test_cents_to_freq(void) {
    TEST_ASSERT_EQUAL_UINT16(440, cents_to_freq(440, 0));
    TEST_ASSERT_EQUAL_UINT16(880, cents_to_freq(440, 1200));
    TEST_ASSERT_EQUAL_UINT16(220, cents_to_freq(440, -1200));
    TEST_ASSERT_EQUAL_UINT16(466, cents_to_freq(440, 100)); // A#4
    TEST_ASSERT_EQUAL_UINT16(1, cents_to_freq(1, -12000));  // clamp to >= 1
}

void test_vibrato_zero_when_no_cc(void) {
    for (uint32_t t = 0; t < 1000; t += 37) {
        TEST_ASSERT_EQUAL_INT16(0, vibrato_cents(t, 0));
    }
}

void test_vibrato_zero_at_t0(void) {
    TEST_ASSERT_EQUAL_INT16(0, vibrato_cents(0, 127));
}

void test_vibrato_bounded_and_sign(void) {
    for (uint32_t t = 0; t < 1000; t += 7) {
        int16_t v = vibrato_cents(t, 127);
        TEST_ASSERT_TRUE(v >= -50 && v <= 50);
    }
    TEST_ASSERT_TRUE(vibrato_cents(20, 127) > 0);   // rising first quarter
    TEST_ASSERT_TRUE(vibrato_cents(104, 127) < 0);  // second half of cycle
}

void test_scale_level(void) {
    TEST_ASSERT_EQUAL_UINT8(127, scale_level(127, 127));
    TEST_ASSERT_EQUAL_UINT8(0, scale_level(0, 127));
    TEST_ASSERT_EQUAL_UINT8(64, scale_level(64, 127));
    TEST_ASSERT_EQUAL_UINT8(0, scale_level(127, 0));
    TEST_ASSERT_EQUAL_UINT8(50, scale_level(100, 64));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_pitch_bend_cents);
    RUN_TEST(test_pitch_bend_range_scales);
    RUN_TEST(test_cents_to_freq);
    RUN_TEST(test_vibrato_zero_when_no_cc);
    RUN_TEST(test_vibrato_zero_at_t0);
    RUN_TEST(test_vibrato_bounded_and_sign);
    RUN_TEST(test_scale_level);
    return UNITY_END();
}
