#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
/* Two background policies, selected per run and reported in every summary.
 *
 * Policy 2 (default): Q16 ADC^2, 16 warmup captures, 1/64 negative and 1/256
 * positive adaptation. Decide against the PREVIOUS background, then adapt on
 * every capture. A sustained level rise therefore cannot freeze the estimate.
 * The floor is one Q16 quantum, not one whole ADC^2.
 *
 * Policy 1 (legacy): the rule of the measured optimized-v2 image. Whole ADC^2
 * background with a floor of one, 16 warmup captures, 1/64 adaptation on
 * NEGATIVE captures only. A sustained level rise keeps every later capture
 * positive until the run ends. It exists so both rules can be compared on one
 * installed image; its q16 field always holds a whole multiple of 65536.
 *
 * Inputs are the unchanged integer energy kernel (maximum 2^19 ADC^2).
 * State and products fit uint64_t, including ratio <= 1000000. */
#define DETECTOR_BACKGROUND_POLICY_LEGACY 1u
#define DETECTOR_BACKGROUND_POLICY_Q16 2u
#define DETECTOR_BACKGROUND_POLICY DETECTOR_BACKGROUND_POLICY_Q16
#define DETECTOR_BACKGROUND_SCALE UINT64_C(65536)
/* A zero-initialized state is policy 2. Use detector_background_start() to
 * choose; never flip `legacy` after the first step. */
typedef struct {
    uint64_t q16, warm_sum;
    unsigned count;
    bool legacy;
} detector_background_t;
/* Sticky selection for the NEXT DET1/DETPIPE1 run; resets to policy 2 at boot. */
static unsigned detector_background_policy __attribute__((unused)) = DETECTOR_BACKGROUND_POLICY;
static inline detector_background_t detector_background_start(unsigned policy) {
    bool legacy = policy == DETECTOR_BACKGROUND_POLICY_LEGACY;
    return (detector_background_t){.q16 = legacy ? DETECTOR_BACKGROUND_SCALE : 1, .legacy = legacy};
}
static inline unsigned detector_background_state_policy(const detector_background_t *state) {
    return state->legacy ? DETECTOR_BACKGROUND_POLICY_LEGACY : DETECTOR_BACKGROUND_POLICY_Q16;
}
static bool detector_background_step_legacy(detector_background_t *state,
                                           uint32_t mean, uint32_t peak,
                                           unsigned ratio, unsigned *score) {
    uint64_t background = state->q16 / DETECTOR_BACKGROUND_SCALE;
    if (state->count <= 16) {
        state->warm_sum += mean;
        background = state->warm_sum / state->count;
        if (!background) background = 1;
        state->q16 = background * DETECTOR_BACKGROUND_SCALE;
        return false;
    }
    if (!background) background = 1;
    uint64_t scaled_peak = (uint64_t)peak * 1000;
    bool positive = scaled_peak > background * ratio;
    uint64_t raw_score = scaled_peak / background;
    *score = raw_score > UINT_MAX ? UINT_MAX : (unsigned)raw_score;
    if (!positive) {
        background = (background * 63 + mean + 32) / 64;
        if (!background) background = 1;
    }
    state->q16 = background * DETECTOR_BACKGROUND_SCALE;
    return positive;
}
static bool detector_background_step(detector_background_t *state,
                                    uint32_t mean, uint32_t peak,
                                    unsigned ratio, unsigned *score) {
    *score = 0;
    state->count++;
    if (state->legacy) return detector_background_step_legacy(state, mean, peak, ratio, score);
    uint64_t sample = (uint64_t)mean * DETECTOR_BACKGROUND_SCALE;
    if (state->count <= 16) {
        state->warm_sum += sample;
        state->q16 = state->warm_sum / state->count;
        if (!state->q16) state->q16 = 1;
        return false;
    }
    if (!state->q16) state->q16 = 1;
    uint64_t scaled_peak = (uint64_t)peak * 1000 * DETECTOR_BACKGROUND_SCALE;
    bool positive = scaled_peak > state->q16 * ratio;
    uint64_t raw_score = scaled_peak / state->q16;
    *score = raw_score > UINT_MAX ? UINT_MAX : (unsigned)raw_score;
    unsigned divisor = positive ? 256 : 64;
    state->q16 = (state->q16 * (divisor - 1) + sample + divisor / 2) / divisor;
    if (!state->q16) state->q16 = 1;
    return positive;
}
