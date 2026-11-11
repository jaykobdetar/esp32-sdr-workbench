#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
/* Policy 2: Q16 ADC^2, 16 warmup captures, 1/64 negative and 1/256 positive
 * adaptation. Decide against the PREVIOUS background, then adapt on every
 * capture. A sustained level rise therefore cannot freeze the estimate.
 * Inputs are the unchanged integer energy kernel (maximum 2^19 ADC^2).
 * Q16 state and products fit uint64_t, including ratio <= 1000000.
 * The floor is one Q16 quantum, not one whole ADC^2. */
#define DETECTOR_BACKGROUND_POLICY 2u
#define DETECTOR_BACKGROUND_SCALE UINT64_C(65536)
typedef struct {
    uint64_t q16, warm_sum;
    unsigned count;
} detector_background_t;
static bool detector_background_step(detector_background_t *state,
                                    uint32_t mean, uint32_t peak,
                                    unsigned ratio, unsigned *score) {
    uint64_t sample = (uint64_t)mean * DETECTOR_BACKGROUND_SCALE;
    *score = 0;
    state->count++;
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
