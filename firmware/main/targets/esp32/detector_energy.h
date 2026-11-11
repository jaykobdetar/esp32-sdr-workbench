#pragma once
#include <stdint.h>
/* Energy in signed 10-bit ADC units, with block-local complex mean removed.
 * 64-sample blocks suppress DC and very slow content. Tail is not analyzed.
 * Caller bound: n <= MAX_SAMPLES (16380), hence at most 255 complete blocks.
 * Each component is [-512,511]. Block sums are [-32768,32704], so each
 * signed square is <= 2^30. Their SUM must be unsigned (can equal 2^31).
 * sum(|x|^2) <= 64*2*512^2 = 2^25; scaling by 64 is <= 2^31.
 * Cauchy-Schwarz proves the unsigned variance numerator nonnegative.
 * Block energy <= 2^19; total <= 255*2^19 < 2^27. Thus all arithmetic
 * below fits 32 bits with exactly the same truncation as the v1 uint64 code. */
static void detector_energy(const uint32_t *words, unsigned n, uint32_t *mean, uint32_t *peak) {
    uint32_t total = 0;
    uint32_t maximum = 0;
    unsigned blocks = n / 64;
    for (unsigned b = 0; b < blocks; b++) {
        int32_t si = 0, sq = 0;
        uint32_t squares = 0;
        for (unsigned j = 0; j < 64; j++) {
            uint32_t w = words[b * 64 + j];
            int32_t i = (int32_t)(w & 1023), q = (int32_t)((w >> 10) & 1023);
            if (i >= 512) i -= 1024;
            if (q >= 512) q -= 1024;
            si += i; sq += q;
            squares += i * i + q * q;
        }
        uint32_t mean_square = (uint32_t)(si * si) + (uint32_t)(sq * sq);
        uint32_t energy = ((squares << 6) - mean_square) >> 12;
        total += energy;
        if (energy > maximum) maximum = energy;
    }
    *mean = blocks ? total / blocks : 0;
    *peak = maximum;
}
