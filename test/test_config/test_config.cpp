#include <unity.h>
#include <string.h>
#include "config.h"

void setUp(void) {}
void tearDown(void) {}

void test_leaf_defaults(void) {
    leaf_config_t cfg;
    config_defaults(&cfg);
    TEST_ASSERT_EQUAL_UINT8(0, cfg.channel);
    TEST_ASSERT_EQUAL_UINT8(0, cfg.actuator);
    TEST_ASSERT_EQUAL_UINT8(3, cfg.gpio_piezo);
    TEST_ASSERT_EQUAL_UINT8(4, cfg.gpio_solenoid);
    TEST_ASSERT_EQUAL_UINT16(36, cfg.solenoid_note);
    TEST_ASSERT_EQUAL_UINT16(40, cfg.solenoid_hold_ms);
    TEST_ASSERT_EQUAL_UINT8(40, cfg.solenoid_duty_min);
    TEST_ASSERT_EQUAL_UINT8(220, cfg.solenoid_duty_max);
    TEST_ASSERT_EQUAL_UINT8(2, cfg.piezo_pitch_bend_range);
    TEST_ASSERT_EQUAL_UINT16(5, cfg.piezo_adsr_attack_ms);
    TEST_ASSERT_EQUAL_UINT16(100, cfg.piezo_adsr_decay_ms);
    TEST_ASSERT_EQUAL_UINT8(70, cfg.piezo_adsr_sustain_pct);
    TEST_ASSERT_EQUAL_UINT16(100, cfg.piezo_adsr_release_ms);
    TEST_ASSERT_EQUAL_UINT8(255, cfg.node_id);
    TEST_ASSERT_EQUAL_UINT16(30, cfg.settings_window_sec);
    TEST_ASSERT_EQUAL_UINT8(13, cfg.espnow_channel);
}

void test_controller_defaults(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    TEST_ASSERT_EQUAL_UINT8(13, cfg.espnow_channel);
    TEST_ASSERT_EQUAL_UINT16(30, cfg.settings_window_sec);
}

void test_crc_simple(void) {
    uint8_t data[3] = {1, 2, 3};
    TEST_ASSERT_EQUAL_UINT8(6, config_crc(data, sizeof(data)));
}

void test_crc_wrap(void) {
    uint8_t data[2] = {0xFF, 0x01};
    TEST_ASSERT_EQUAL_UINT8(0, config_crc(data, sizeof(data)));
}

void test_crc_empty(void) {
    TEST_ASSERT_EQUAL_UINT8(0, config_crc(NULL, 0));
}

void test_defaults_crc_appends(void) {
    // NVS blob layout: struct bytes + one trailing CRC byte. A load would
    // accept the blob iff config_crc(blob, sizeof(cfg)) == trailing byte.
    leaf_config_t cfg;
    config_defaults(&cfg);
    uint8_t blob[sizeof(cfg) + 1];
    memcpy(blob, &cfg, sizeof(cfg));
    blob[sizeof(cfg)] = config_crc(&cfg, sizeof(cfg));
    TEST_ASSERT_EQUAL_UINT8(blob[sizeof(cfg)], config_crc(blob, sizeof(cfg)));
    // Corruption must be caught: flip one struct byte, CRC must now differ.
    blob[0] ^= 0x01;
    TEST_ASSERT_NOT_EQUAL_UINT8(blob[sizeof(cfg)], config_crc(blob, sizeof(cfg)));
}

void test_wrong_size_noop(void) {
    // config_defaults_impl with an unrecognized size must not write anything.
    // sizeof(controller_config_t) == 4 (uint8 + uint16 padded to 2-byte align),
    // so a 4-byte buffer would NOT be unrecognized — use 3.
    uint8_t buf[3] = {0xAA, 0xAA, 0xAA};
    config_defaults_impl(buf, sizeof(buf));
    for (int i = 0; i < 3; i++) TEST_ASSERT_EQUAL_UINT8(0xAA, buf[i]);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_leaf_defaults);
    RUN_TEST(test_controller_defaults);
    RUN_TEST(test_crc_simple);
    RUN_TEST(test_crc_wrap);
    RUN_TEST(test_crc_empty);
    RUN_TEST(test_defaults_crc_appends);
    RUN_TEST(test_wrong_size_noop);
    return UNITY_END();
}
