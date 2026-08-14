#include <unity.h>
#include "note_freq.h"

void setUp(void) {}
void tearDown(void) {}

void test_note_freq_known_values(void) {
    TEST_ASSERT_EQUAL_UINT16(440, note_to_freq(69));    // A4
    TEST_ASSERT_EQUAL_UINT16(262, note_to_freq(60));    // C4
    TEST_ASSERT_EQUAL_UINT16(8, note_to_freq(0));
    TEST_ASSERT_EQUAL_UINT16(12544, note_to_freq(127));
    TEST_ASSERT_EQUAL_UINT16(28, note_to_freq(21));     // A0 = 27.5 -> 28
}

void test_note_freq_monotonic(void) {
    for (int n = 0; n < 127; n++) {
        TEST_ASSERT_TRUE(note_to_freq(n) <= note_to_freq(n + 1));
    }
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_note_freq_known_values);
    RUN_TEST(test_note_freq_monotonic);
    return UNITY_END();
}
