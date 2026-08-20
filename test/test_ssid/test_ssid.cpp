#include <unity.h>
#include "ssid.h"

void setUp(void) {}
void tearDown(void) {}

void test_controller_ssid(void) {
    char out[32];
    uint8_t mac[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0x12, 0x34};
    ssid_build(out, sizeof(out), 1, 0, mac);
    TEST_ASSERT_EQUAL_STRING("reduzent-controller", out);
}

void test_leaf_ssid_with_node_id(void) {
    char out[32];
    uint8_t mac[6] = {0, 0, 0, 0, 0x12, 0x34};
    ssid_build(out, sizeof(out), 0, 7, mac);
    TEST_ASSERT_EQUAL_STRING("reduzent-leaf-7", out);
}

void test_leaf_ssid_max_node_id(void) {
    char out[32];
    uint8_t mac[6] = {0};
    ssid_build(out, sizeof(out), 0, 254, mac);
    TEST_ASSERT_EQUAL_STRING("reduzent-leaf-254", out);
}

void test_leaf_ssid_node_id_255_uses_mac(void) {
    char out[32];
    uint8_t mac[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0x12, 0x34};
    ssid_build(out, sizeof(out), 0, 255, mac);
    TEST_ASSERT_EQUAL_STRING("reduzent-leaf-1234", out);
}

void test_leaf_ssid_mac_uppercase_hex(void) {
    char out[32];
    uint8_t mac[6] = {0, 0, 0, 0, 0xAB, 0xcd};
    ssid_build(out, sizeof(out), 0, 255, mac);
    TEST_ASSERT_EQUAL_STRING("reduzent-leaf-ABCD", out);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_controller_ssid);
    RUN_TEST(test_leaf_ssid_with_node_id);
    RUN_TEST(test_leaf_ssid_max_node_id);
    RUN_TEST(test_leaf_ssid_node_id_255_uses_mac);
    RUN_TEST(test_leaf_ssid_mac_uppercase_hex);
    return UNITY_END();
}
