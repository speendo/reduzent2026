#include <unity.h>
#include "held_notes.h"

void setUp(void) {}
void tearDown(void) {}

void test_init_all_free(void) {
    held_notes_t h;
    held_notes_init(&h);
    uint16_t cur = 0; uint8_t ch, note, vel;
    TEST_ASSERT_EQUAL(0, held_next(&h, &cur, &ch, &note, &vel));
}

void test_set_and_next(void) {
    held_notes_t h;
    held_notes_init(&h);
    held_set(&h, 3, 60, 100);
    held_set(&h, 5, 72, 80);
    uint16_t cur = 0; uint8_t ch, note, vel;
    TEST_ASSERT_EQUAL(1, held_next(&h, &cur, &ch, &note, &vel));
    TEST_ASSERT_EQUAL_UINT8(3, ch);
    TEST_ASSERT_EQUAL_UINT8(60, note);
    TEST_ASSERT_EQUAL_UINT8(100, vel);
    TEST_ASSERT_EQUAL(1, held_next(&h, &cur, &ch, &note, &vel));
    TEST_ASSERT_EQUAL_UINT8(5, ch);
    TEST_ASSERT_EQUAL_UINT8(72, note);
    TEST_ASSERT_EQUAL_UINT8(80, vel);
    TEST_ASSERT_EQUAL(0, held_next(&h, &cur, &ch, &note, &vel));
}

void test_clear_single(void) {
    held_notes_t h;
    held_notes_init(&h);
    held_set(&h, 3, 60, 100);
    held_set(&h, 3, 61, 90);
    held_clear(&h, 3, 60);
    uint16_t cur = 0; uint8_t ch, note, vel;
    TEST_ASSERT_EQUAL(1, held_next(&h, &cur, &ch, &note, &vel));
    TEST_ASSERT_EQUAL_UINT8(61, note);
    TEST_ASSERT_EQUAL(0, held_next(&h, &cur, &ch, &note, &vel));
}

void test_clear_channel(void) {
    held_notes_t h;
    held_notes_init(&h);
    held_set(&h, 2, 60, 100);
    held_set(&h, 2, 61, 90);
    held_set(&h, 4, 60, 100);
    held_clear_channel(&h, 2);
    uint16_t cur = 0; uint8_t ch, note, vel;
    TEST_ASSERT_EQUAL(1, held_next(&h, &cur, &ch, &note, &vel));
    TEST_ASSERT_EQUAL_UINT8(4, ch);
    TEST_ASSERT_EQUAL(0, held_next(&h, &cur, &ch, &note, &vel));
}

void test_clear_all(void) {
    held_notes_t h;
    held_notes_init(&h);
    held_set(&h, 2, 60, 100);
    held_set(&h, 9, 61, 90);
    held_clear_all(&h);
    uint16_t cur = 0; uint8_t ch, note, vel;
    TEST_ASSERT_EQUAL(0, held_next(&h, &cur, &ch, &note, &vel));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_init_all_free);
    RUN_TEST(test_set_and_next);
    RUN_TEST(test_clear_single);
    RUN_TEST(test_clear_channel);
    RUN_TEST(test_clear_all);
    return UNITY_END();
}
