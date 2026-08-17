#include <unity.h>
#include "mixer.h"

void setUp(void) {}
void tearDown(void) {}

void test_phase_increment(void) {
    TEST_ASSERT_EQUAL_UINT32(59055800u, phase_increment(440, 32000));   // A4
    TEST_ASSERT_EQUAL_UINT32(0u, phase_increment(0, 32000));
    TEST_ASSERT_EQUAL_UINT32(2147483648u, phase_increment(16000, 32000)); // Nyquist
    TEST_ASSERT_EQUAL_UINT32(134217u, phase_increment(1, 32000));       // (1<<32)/32000
}

void test_voice_sample_bit_level_zero_is_off(void) {
    voice_t v = {0};
    v.level = 0;
    TEST_ASSERT_EQUAL_UINT8(0, voice_sample_bit(&v, 100));
    TEST_ASSERT_EQUAL_UINT8(0, voice_sample_bit(&v, 100));
}

void test_voice_sample_bit_duty(void) {
    voice_t v = {0};
    v.level = 127;
    v.phase = 0;
    TEST_ASSERT_EQUAL_UINT8(1, voice_sample_bit(&v, 100)); // 100 < 127<<24 -> high
    v.phase = (uint32_t)127 << 24;                          // at threshold
    TEST_ASSERT_EQUAL_UINT8(0, voice_sample_bit(&v, 1));    // threshold+1 -> low
}

void test_mix_no_voices_is_zero(void) {
    voice_table_t vt;
    voice_table_init(&vt, &ENVELOPE_DEFAULT);
    uint32_t inc[MAX_VOICES] = {0};
    TEST_ASSERT_EQUAL_UINT8(0, mix_voices(&vt, inc));
}

void test_mix_single_voice(void) {
    voice_table_t vt;
    voice_table_init(&vt, &ENVELOPE_DEFAULT);
    uint32_t inc[MAX_VOICES] = {0};
    voice_note_on(&vt, 60, 127, 0);
    vt.voices[0].level = 127; // full amplitude
    inc[0] = phase_increment(440, 32000);
    TEST_ASSERT_EQUAL_UINT8(1, mix_voices(&vt, inc)); // phase 0 -> inc, below threshold
}

void test_mix_two_identical_voices_xor_to_zero(void) {
    voice_table_t vt;
    voice_table_init(&vt, &ENVELOPE_DEFAULT);
    uint32_t inc[MAX_VOICES] = {0};
    voice_note_on(&vt, 60, 127, 0);
    voice_note_on(&vt, 64, 127, 0);
    vt.voices[0].level = 127;
    vt.voices[1].level = 127;
    inc[0] = phase_increment(440, 32000);
    inc[1] = phase_increment(440, 32000);
    TEST_ASSERT_EQUAL_UINT8(0, mix_voices(&vt, inc)); // identical bits XOR to 0
}

void test_mix_ignores_idle_voices(void) {
    voice_table_t vt;
    voice_table_init(&vt, &ENVELOPE_DEFAULT);
    uint32_t inc[MAX_VOICES] = {0};
    // no notes: every voice is idle; mix must be 0 even with nonzero inc
    for (int i = 0; i < MAX_VOICES; i++) inc[i] = phase_increment(440, 32000);
    TEST_ASSERT_EQUAL_UINT8(0, mix_voices(&vt, inc));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_phase_increment);
    RUN_TEST(test_voice_sample_bit_level_zero_is_off);
    RUN_TEST(test_voice_sample_bit_duty);
    RUN_TEST(test_mix_no_voices_is_zero);
    RUN_TEST(test_mix_single_voice);
    RUN_TEST(test_mix_two_identical_voices_xor_to_zero);
    RUN_TEST(test_mix_ignores_idle_voices);
    return UNITY_END();
}
