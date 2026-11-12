#pragma once
/* Validation-only, outside the RF-owned interval. No dynamic storage of our own.
 * Pinned ESP-IDF reports task stack high water in BYTES, not upstream words. */
#ifndef DETPIPE_HEALTH
#define DETPIPE_HEALTH 0
#endif
#if DETPIPE_HEALTH
#define DETPIPE_HEALTH_CAPABILITY "DETPIPEHEALTH "
typedef struct {
    unsigned run_id;
    bool active, valid;
    int start_error, stop_error;
    size_t before, allocated, drained, after, local_min, lifetime_before, lifetime_after;
    size_t stack_before, stack_after;
} detpipe_health_t;
static detpipe_health_t detpipe_health = {
    .before=SIZE_MAX,.allocated=SIZE_MAX,.drained=SIZE_MAX,.after=SIZE_MAX,
    .local_min=SIZE_MAX,.lifetime_before=SIZE_MAX,.lifetime_after=SIZE_MAX,
    .stack_before=SIZE_MAX,.stack_after=SIZE_MAX
};
static void detpipe_health_begin(void) {
    unsigned id = detpipe_health.run_id + 1;
    detpipe_health = (detpipe_health_t){.run_id=id,
        .allocated=SIZE_MAX,.drained=SIZE_MAX,.after=SIZE_MAX,.local_min=SIZE_MAX,
        .lifetime_after=SIZE_MAX,.stack_after=SIZE_MAX};
    detpipe_health.before = heap_caps_get_free_size(DETPIPE_ALLOC_CAPS);
    detpipe_health.lifetime_before = heap_caps_get_minimum_free_size(DETPIPE_ALLOC_CAPS);
    detpipe_health.stack_before = uxTaskGetStackHighWaterMark(NULL);
    /* SDK start allocates a small region-indexed snapshot and asserts on OOM.
     * This guard is conservative, NOT a reservation against concurrent allocators. */
    detpipe_health.start_error = heap_caps_get_largest_free_block(MALLOC_CAP_DEFAULT) < 4096
        ? ESP_ERR_NO_MEM : heap_caps_monitor_local_minimum_free_size_start();
    detpipe_health.active = detpipe_health.start_error == ESP_OK;
}
static void detpipe_health_allocated(void) {
    detpipe_health.allocated = heap_caps_get_free_size(DETPIPE_ALLOC_CAPS);
}
static void detpipe_health_drained(void) {
    detpipe_health.drained = heap_caps_get_free_size(DETPIPE_ALLOC_CAPS);
}
static void detpipe_health_finish(bool valid) {
    if (detpipe_health.active) {
        /* Sum of regional local low watermarks, not sampled boundary minima. */
        detpipe_health.local_min = heap_caps_get_minimum_free_size(DETPIPE_ALLOC_CAPS);
        detpipe_health.stop_error = heap_caps_monitor_local_minimum_free_size_stop();
        detpipe_health.active = false;
    }
    detpipe_health.after = heap_caps_get_free_size(DETPIPE_ALLOC_CAPS);
    detpipe_health.lifetime_after = heap_caps_get_minimum_free_size(DETPIPE_ALLOC_CAPS);
    detpipe_health.stack_after = uxTaskGetStackHighWaterMark(NULL);
    detpipe_health.valid = valid && detpipe_health.start_error == ESP_OK && detpipe_health.stop_error == ESP_OK;
}
static void detpipe_health_field(const char *name, size_t value) {
    if(value==SIZE_MAX) reply(",\"%s\":null",name);
    else reply(",\"%s\":%u",name,(unsigned)value);
}
static void detpipe_health_report(void) {
    reply("DETPIPEHEALTH {\"version\":1,\"enabled\":true,\"caps\":%u,\"run_id\":%u,\"run_valid\":%s,\"monitor_start_error\":%d,\"monitor_stop_error\":%d",
        (unsigned)DETPIPE_ALLOC_CAPS,detpipe_health.run_id,detpipe_health.valid?"true":"false",detpipe_health.start_error,detpipe_health.stop_error);
    detpipe_health_field("free_now_bytes",heap_caps_get_free_size(DETPIPE_ALLOC_CAPS));
    detpipe_health_field("largest_now_bytes",heap_caps_get_largest_free_block(DETPIPE_ALLOC_CAPS));
#define DETPIPE_HEALTH_FIELD(name, member) detpipe_health_field(name,detpipe_health.member)
    DETPIPE_HEALTH_FIELD("free_before_bytes",before);
    DETPIPE_HEALTH_FIELD("free_allocated_bytes",allocated);
    DETPIPE_HEALTH_FIELD("free_drained_bytes",drained);
    DETPIPE_HEALTH_FIELD("free_after_bytes",after);
    DETPIPE_HEALTH_FIELD("run_min_bytes",local_min);
    DETPIPE_HEALTH_FIELD("lifetime_min_before_bytes",lifetime_before);
    DETPIPE_HEALTH_FIELD("lifetime_min_after_bytes",lifetime_after);
    DETPIPE_HEALTH_FIELD("stack_before_bytes",stack_before);
    DETPIPE_HEALTH_FIELD("stack_after_bytes",stack_after);
#undef DETPIPE_HEALTH_FIELD
    reply("}\n");
}
#else
#define DETPIPE_HEALTH_CAPABILITY ""
#define detpipe_health_begin() ((void)0)
#define detpipe_health_allocated() ((void)0)
#define detpipe_health_drained() ((void)0)
#define detpipe_health_finish(valid) ((void)0)
static void detpipe_health_report(void) {
    reply("DETPIPEHEALTH {\"version\":1,\"enabled\":false}\n");
}
#endif
