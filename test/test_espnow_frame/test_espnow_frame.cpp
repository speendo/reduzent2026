#include <unity.h>
#include "espnow_frame.h"

void setUp(void) {}
void tearDown(void) {}

void test_frame_size_and_constants(void) {
    TEST_ASSERT_EQUAL(5, ESP_NOW_FRAME_SIZE);
    TEST_ASSERT_EQUAL(0xFF, ESP_NOW_CHANNEL_BROADCAST);
    TEST_ASSERT_EQUAL(0, EVENT_NOTE);
    TEST_ASSERT_EQUAL(6, EVENT_PANIC);
}

void test_pack_unpack_round_trip(void) {
    espnow_frame_t in = {3, EVENT_NOTE, 60, 100, 0};
    uint8_t buf[ESP_NOW_FRAME_SIZE];
    espnow_frame_t out;
    frame_pack(&in, buf);
    frame_unpack(buf, &out);
    TEST_ASSERT_EQUAL_UINT8(in.channel, out.channel);
    TEST_ASSERT_EQUAL_UINT8(in.type, out.type);
    TEST_ASSERT_EQUAL_UINT8(in.note, out.note);
    TEST_ASSERT_EQUAL_UINT8(in.value, out.value);
    TEST_ASSERT_EQUAL_UINT8(in.value_hi, out.value_hi);
}

void test_pack_byte_layout(void) {
    // channel-first layout: a leaf filters on buf[0].
    espnow_frame_t f = {12, EVENT_PITCH_BEND, 0, 0x34, 0x12};
    uint8_t buf[ESP_NOW_FRAME_SIZE];
    frame_pack(&f, buf);
    TEST_ASSERT_EQUAL_UINT8(12, buf[0]);
    TEST_ASSERT_EQUAL_UINT8(EVENT_PITCH_BEND, buf[1]);
    TEST_ASSERT_EQUAL_UINT8(0x34, buf[3]);
    TEST_ASSERT_EQUAL_UINT8(0x12, buf[4]);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_frame_size_and_constants);
    RUN_TEST(test_pack_unpack_round_trip);
    RUN_TEST(test_pack_byte_layout);
    return UNITY_END();
}
