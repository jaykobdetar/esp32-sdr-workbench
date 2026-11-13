#pragma once
/* Phase34: block the main task until same-core idle reaches this hook.
 * Semaphore storage and handle live forever: xSemaphoreGive may preempt its
 * idle caller, so deleting/reinitializing storage at stream end is unsafe.
 * Never run this service while RF owns capture SRAM. Watchdogs stay enabled. */
static StaticSemaphore_t dstream_wake_storage;
static SemaphoreHandle_t dstream_wake_sem;
static volatile bool dstream_wake_armed;
static volatile uint32_t dstream_wake_counter;
static bool dstream_wake_hook(void) {
    if (!dstream_wake_armed) return true;
    dstream_wake_armed=false;
    dstream_wake_counter++;
    /* Give has zero blocking time. It can context-switch before returning;
     * everything referenced after that switch has static lifetime. Returning
     * false avoids WFI for this one idle pass, including delayed resumption. */
    xSemaphoreGive(dstream_wake_sem);
    return false;
}
static bool dstream_wake_begin(dstream_idle_t *s) {
    s->core=xPortGetCoreID();
    dstream_wake_armed=false;
    if (!dstream_wake_sem) dstream_wake_sem=xSemaphoreCreateBinaryStatic(&dstream_wake_storage);
    if (!dstream_wake_sem) return false;
    (void)xSemaphoreTake(dstream_wake_sem,0); /* Drain at most one stale token. */
    s->registered=esp_register_freertos_idle_hook_for_cpu(dstream_wake_hook,s->core)==ESP_OK;
    return s->registered;
}
static void dstream_wake_end(dstream_idle_t *s) {
    dstream_wake_armed=false;
    if (s->registered) esp_deregister_freertos_idle_hook_for_cpu(dstream_wake_hook,s->core);
    s->registered=false;
    /* Deliberately neither delete nor recreate the semaphore. */
}
static void dstream_wake_service(dstream_idle_t *s) {
    if (++s->since<32) return;
    s->since=0;s->handshakes++;
    int64_t start=esp_timer_get_time();
    (void)xSemaphoreTake(dstream_wake_sem,0);
    uint32_t previous=dstream_wake_counter;
    dstream_wake_armed=true;
    BaseType_t taken=xSemaphoreTake(dstream_wake_sem,2);
    dstream_wake_armed=false;
    if (taken==pdTRUE && dstream_wake_counter!=previous) s->observed++;
    else {s->fallbacks++;vTaskDelay(1);}
    uint64_t elapsed=(uint64_t)(esp_timer_get_time()-start);
    if (elapsed>s->latency_max_us) s->latency_max_us=elapsed;
    s->attempts_max=1;
}
