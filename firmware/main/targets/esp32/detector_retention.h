#pragma once
#include <stdint.h>
/* Three 5120-sample CAP20 crops need 38400 bytes, below the previous full
 * 16380-sample packed retention budget of 40950. At 16 MS/s each spans
 * 320 us; at 40/80 MS/s it is shorter and NOT sufficient for a 292 us frame.
 * Peak-centering cannot guarantee packet containment at a crop boundary. */
#define DETECTOR_CANDIDATES 3u
#define DETECTOR_CROP_SAMPLES 5120u
typedef struct {
    unsigned samples, offset_samples, generation, score_milli, capture_us;
    uint64_t trigger_device_us;
} detector_candidate_t;
static unsigned detector_crop_length(unsigned n) {
    unsigned aligned = n & ~7u;
    return aligned > DETECTOR_CROP_SAMPLES ? DETECTOR_CROP_SAMPLES : aligned;
}
/* First maximum-energy block; integer arithmetic is identical to the kernel. */
static unsigned detector_crop_offset(const uint32_t *words, unsigned n, unsigned crop) {
    unsigned best = 0; uint32_t maximum = 0;
    for (unsigned b = 0; b < n / 64; b++) {
        uint32_t mean, peak;
        detector_energy(words + b * 64, 64, &mean, &peak);
        if (peak > maximum) { maximum = peak; best = b * 64; }
    }
    unsigned center = best + 32;
    unsigned offset = center > crop / 2 ? center - crop / 2 : 0;
    if (offset > n - crop) offset = n - crop;
    return offset & ~7u;
}
static unsigned detector_candidate_slot(const detector_candidate_t *candidates,
                                        unsigned capacity, unsigned score) {
    unsigned weakest = 0;
    for (unsigned j = 0; j < capacity; j++) {
        if (!candidates[j].samples) return j;
        if (candidates[j].score_milli < candidates[weakest].score_milli) weakest = j;
    }
    return score > candidates[weakest].score_milli ? weakest : capacity;
}
