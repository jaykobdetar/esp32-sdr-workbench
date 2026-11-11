#pragma once
#include <stdint.h>
/* Energy in signed 10-bit ADC units, with block-local complex mean removed.
 * 64-sample blocks suppress DC and very slow content. Tail is not analyzed. */
static void detector_energy(const uint32_t *words, unsigned n, uint32_t *mean, uint32_t *peak) {
    uint64_t total = 0;
    uint32_t maximum = 0;
    unsigned blocks = n / 64;
    for (unsigned b = 0; b < blocks; b++) {
        int64_t si = 0, sq = 0;
        uint64_t squares = 0;
        for (unsigned j = 0; j < 64; j++) {
            uint32_t w = words[b * 64 + j];
            int32_t i = (int32_t)(w & 1023), q = (int32_t)((w >> 10) & 1023);
            if (i >= 512) i -= 1024;
            if (q >= 512) q -= 1024;
            si += i; sq += q;
            squares += i * i + q * q;
        }
        uint32_t energy = (squares * 64 - (uint64_t)(si * si + sq * sq)) / 4096;
        total += energy;
        if (energy > maximum) maximum = energy;
    }
    *mean = blocks ? total / blocks : 0;
    *peak = maximum;
}
