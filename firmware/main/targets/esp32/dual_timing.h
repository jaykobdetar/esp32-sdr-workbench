#pragma once
/* Experimental diagnostic only. No global-clock or RF-arrival guarantee.
 * Trace stores successful trigger-register timestamps; N/fs remains nominal.
 * UART output happens only after acquisition has completely stopped. */
#define DUAL_TRACE_CAPACITY 4096u
static uint32_t *dual_trace;
static unsigned dual_count, dual_period, dual_yield_phase, dual_late, dual_skipped;
static uint64_t dual_first, dual_next, dual_armed_deadline;
static bool dual_armed, dual_active, dual_overflow;
/* Optional nanosecond period for drift-compensated persistent runs. The
 * actual trigger remains integer-microsecond resolution. Zero preserves TRACE. */
static uint32_t dual_period_ns, dual_fraction_ns;
static inline void dual_advance(unsigned slots) {
    uint64_t ns = (uint64_t)slots * dual_period_ns + dual_fraction_ns;
    dual_next += dual_period_ns ? ns / 1000 : (uint64_t)slots * dual_period;
    dual_fraction_ns = dual_period_ns ? ns % 1000 : 0;
}
static inline void dual_wait_trigger(void) {
    if (!dual_next) return;
    uint64_t now = esp_timer_get_time();
    if (dual_period && now > dual_next + dual_period) {
        unsigned skipped = dual_period_ns ?
            ((now - dual_next) * 1000 - dual_fraction_ns) / dual_period_ns :
            (now - dual_next) / dual_period;
        dual_advance(skipped);
        dual_skipped += skipped;
    }
    while ((now = esp_timer_get_time()) + 2000 < dual_next) vTaskDelay(1);
    while ((now = esp_timer_get_time()) < dual_next) {}
    unsigned late = now > dual_next ? now - dual_next : 0;
    if (late > dual_late) dual_late = late;
    if (dual_period) dual_advance(1);
    else dual_next = 0;
}
static inline bool dual_trace_begin(void) {
    if (!dual_armed) return true;
    dual_armed = false;
    if (dual_trace) heap_caps_free(dual_trace);
    dual_trace = heap_caps_malloc(DUAL_TRACE_CAPACITY * sizeof(uint32_t),
                                  MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT | MALLOC_CAP_DMA);
    dual_count = dual_late = dual_skipped = 0;
    dual_first = 0; dual_overflow = false;
    if (!dual_trace) { reply("ERR trace_memory\n"); return false; }
    dual_period_ns = dual_fraction_ns = 0;
    dual_next = dual_armed_deadline;
    dual_active = true;
    return true;
}
static inline void dual_trace_record(uint64_t trigger) {
    if (!dual_active) return;
    if (!dual_count) dual_first = trigger;
    if (dual_count >= DUAL_TRACE_CAPACITY || trigger - dual_first > UINT32_MAX) {
        dual_overflow = true; return;
    }
    dual_trace[dual_count++] = (uint32_t)(trigger - dual_first);
}
static inline void dual_trace_end(void) {
    dual_active = false; dual_next = 0; dual_period_ns = dual_fraction_ns = 0;
}
