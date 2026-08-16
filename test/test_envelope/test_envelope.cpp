#include <unity.h>
#include "envelope.h"

void setUp(void) {}
void tearDown(void) {}

static const envelope_params_t P = { 10, 100, 100, 70 }; // A10/D100/S70%/R100

void test_attack_ramp(void) {
    env_stage_t stage = ENV_STAGE_ATTACK;
    uint16_t level = 0, release_start = 0;
    uint32_t t0 = 0;
    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 0);
    TEST_ASSERT_EQUAL(ENV_STAGE_ATTACK, stage);
    TEST_ASSERT_EQUAL_UINT16(0, level);

    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 4);
    TEST_ASSERT_EQUAL(ENV_STAGE_ATTACK, stage);
    TEST_ASSERT_EQUAL_UINT16(40, level);

    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 9);
    TEST_ASSERT_EQUAL_UINT16(90, level);
}

void test_attack_transitions_to_decay(void) {
    env_stage_t stage = ENV_STAGE_ATTACK;
    uint16_t level = 0, release_start = 0;
    uint32_t t0 = 0;
    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 10);
    TEST_ASSERT_EQUAL(ENV_STAGE_DECAY, stage);
    TEST_ASSERT_EQUAL_UINT16(100, level);
}

void test_decay_ramp_to_sustain(void) {
    env_stage_t stage = ENV_STAGE_DECAY;
    uint16_t level = 100, release_start = 0;
    uint32_t t0 = 10;
    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 60);
    TEST_ASSERT_EQUAL(ENV_STAGE_DECAY, stage);
    TEST_ASSERT_EQUAL_UINT16(85, level); // 100 - (100-70)*50/100

    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 110);
    TEST_ASSERT_EQUAL(ENV_STAGE_SUSTAIN, stage);
    TEST_ASSERT_EQUAL_UINT16(70, level); // sustain = 70% of 100
}

void test_sustain_holds(void) {
    env_stage_t stage = ENV_STAGE_SUSTAIN;
    uint16_t level = 70, release_start = 0;
    uint32_t t0 = 110;
    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 5000);
    TEST_ASSERT_EQUAL(ENV_STAGE_SUSTAIN, stage);
    TEST_ASSERT_EQUAL_UINT16(70, level);
}

void test_release_ramp_to_idle(void) {
    env_stage_t stage = ENV_STAGE_RELEASE;
    uint16_t level = 70, release_start = 70;
    uint32_t t0 = 5000;
    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 5050);
    TEST_ASSERT_EQUAL(ENV_STAGE_RELEASE, stage);
    TEST_ASSERT_EQUAL_UINT16(35, level); // 70 * (100-50)/100

    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 5100);
    TEST_ASSERT_EQUAL(ENV_STAGE_IDLE, stage);
    TEST_ASSERT_EQUAL_UINT16(0, level);
}

void test_zero_attack_jumps_to_decay(void) {
    const envelope_params_t z = { 0, 100, 100, 70 };
    env_stage_t stage = ENV_STAGE_ATTACK;
    uint16_t level = 0, release_start = 0;
    uint32_t t0 = 0;
    envelope_advance(&z, 100, &stage, &level, &release_start, &t0, 0);
    TEST_ASSERT_EQUAL(ENV_STAGE_DECAY, stage);
    TEST_ASSERT_EQUAL_UINT16(100, level);
}

void test_idle_stays_silent(void) {
    env_stage_t stage = ENV_STAGE_IDLE;
    uint16_t level = 0, release_start = 0;
    uint32_t t0 = 0;
    envelope_advance(&P, 100, &stage, &level, &release_start, &t0, 999);
    TEST_ASSERT_EQUAL(ENV_STAGE_IDLE, stage);
    TEST_ASSERT_EQUAL_UINT16(0, level);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_attack_ramp);
    RUN_TEST(test_attack_transitions_to_decay);
    RUN_TEST(test_decay_ramp_to_sustain);
    RUN_TEST(test_sustain_holds);
    RUN_TEST(test_release_ramp_to_idle);
    RUN_TEST(test_zero_attack_jumps_to_decay);
    RUN_TEST(test_idle_stays_silent);
    return UNITY_END();
}
