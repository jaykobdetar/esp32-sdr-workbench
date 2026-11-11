#pragma once
#include <stdint.h>
#include <string.h>
/* All observations counted. Bins provide exact quantile bounds, not estimates. */
#define PROFILE_BINS 465u
typedef struct { uint32_t bins[PROFILE_BINS], count, nonzero, min, max; uint64_t sum; } profile_hist;
static unsigned profile_bin(uint32_t us) {
    if (us < 128) return us;
    if (us < 1024) return 128 + (us - 128) / 8;
    if (us < 8192) return 240 + (us - 1024) / 64;
    if (us < 65536) return 352 + (us - 8192) / 512;
    return 464;
}
static void profile_add(profile_hist *h, uint32_t us) {
    h->bins[profile_bin(us)]++;
    if (!h->count || us < h->min) h->min = us;
    if (!h->count || us > h->max) h->max = us;
    h->count++; h->nonzero += us != 0; h->sum += us;
}
static void profile_quantile(const profile_hist *h, unsigned percent, uint32_t *lo, uint32_t *hi) {
    if (!h->count) { *lo = *hi = 0; return; }
    uint32_t rank = ((uint64_t)h->count * percent + 99) / 100, count = 0;
    unsigned b;
    for (b = 0; b < PROFILE_BINS; b++) { count += h->bins[b]; if (count >= rank) break; }
    if (b < 128) *lo = *hi = b;
    else if (b < 240) { *lo = 128 + (b-128)*8; *hi = *lo+7; }
    else if (b < 352) { *lo = 1024 + (b-240)*64; *hi = *lo+63; }
    else if (b < 464) { *lo = 8192 + (b-352)*512; *hi = *lo+511; }
    else { *lo = 65536; *hi = h->max; }
    if (*lo < h->min) *lo = h->min;
    if (*hi > h->max) *hi = h->max;
}
enum profile_stage {
    P_PREPARE, P_CAL_CHECK, P_TUNE_CAL, P_GAIN, P_RX_PREP, P_CLEAR, P_FILTER_APPLY,
    P_REG_SETUP, P_TRIGGER, P_REG_RESTORE, P_FILTER_RESTORE, P_VALIDATE,
    P_ACQUIRE, P_ENERGY, P_DECISION, P_RETAIN, P_SCHEDULE, P_HISTOGRAM,
    P_ITERATION, P_TIMER_PAIR, P_STAGE_COUNT
};
static const char *const profile_names[P_STAGE_COUNT] = {
    "prepare_total", "calibration_check", "tune_calibration", "gain_apply", "rx_prepare", "sentinel_clear", "filter_apply",
    "register_setup", "trigger_to_done", "register_restore", "filter_restore", "sentinel_validate",
    "acquire_total", "energy", "threshold_ewma", "retention_copy", "scheduling", "histogram_update",
    "iteration_total", "timer_pair"
};
