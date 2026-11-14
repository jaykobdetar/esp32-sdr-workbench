#pragma once
/* Experimental same-core idle handshake. The pinned IDF idle task can yield
 * before its hook, so a scheduler yield alone is not proof of idle progress.
 * Never call while RF owns capture SRAM. No watchdog setting is changed.
 * Hook work is bounded and nonblocking; suppress WFI only during handshake. */
static volatile bool dstream_idle_active;
static volatile uint32_t dstream_idle_counter;
typedef struct {
    bool registered;
    unsigned core, since, handshakes, observed, fallbacks, attempts_max;
    uint64_t latency_max_us;
} dstream_idle_t;
static bool dstream_idle_hook(void) {
    dstream_idle_counter++;
    return !dstream_idle_active;
}
static bool dstream_idle_begin(dstream_idle_t *s) {
    s->core=xPortGetCoreID();
    dstream_idle_active=false;
    dstream_idle_counter=0;
    s->registered=esp_register_freertos_idle_hook_for_cpu(dstream_idle_hook,s->core)==ESP_OK;
    return s->registered;
}
static void dstream_idle_end(dstream_idle_t *s) {
    dstream_idle_active=false;
    if(s->registered) esp_deregister_freertos_idle_hook_for_cpu(dstream_idle_hook,s->core);
    s->registered=false;
}
static void dstream_idle_service(dstream_idle_t *s) {
    if(++s->since<32) return;
    s->since=0;s->handshakes++;
    int64_t start=esp_timer_get_time();
    uint32_t previous=dstream_idle_counter;
    UBaseType_t priority=uxTaskPriorityGet(NULL);
    unsigned attempts=0;
    dstream_idle_active=true;
    vTaskPrioritySet(NULL,tskIDLE_PRIORITY);
    /* Priority lowering may itself schedule idle. Otherwise repeat yields until
     * its hook runs. Bound requested attempts/time, not RTOS preemption latency. */
    while(dstream_idle_counter==previous && attempts<8 && esp_timer_get_time()-start<2000) {
        attempts++;taskYIELD();
    }
    bool observed=dstream_idle_counter!=previous;
    vTaskPrioritySet(NULL,priority);
    dstream_idle_active=false;
    if(observed) s->observed++;
    else {s->fallbacks++;vTaskDelay(1);}
    uint64_t elapsed=(uint64_t)(esp_timer_get_time()-start);
    if(elapsed>s->latency_max_us) s->latency_max_us=elapsed;
    if(attempts>s->attempts_max) s->attempts_max=attempts;
}
