#pragma once
/* Persistent, no-retention detector with bounded nonblocking telemetry.
 * One writer, no new task, no RF-owned SRAM access outside acquisition. Every
 * analyzed capture has its own CRC-protected record. Not raw I/Q streaming.
 * Include after detector_pipeline.h and dual_timing_commands.h. */
#define DSTREAM_QUEUE 64u
#define DSTREAM_END UINT32_C(0x80000000)
typedef struct {
    uint32_t magic, sequence;
    uint64_t trigger;
    uint32_t mean, peak, background, events, flags, observed_us, gain, crc;
} dstream_record_t;
_Static_assert(sizeof(dstream_record_t) == 48, "DSTREAM wire record size");
static dstream_record_t dstream_queue[DSTREAM_QUEUE];
static unsigned dstream_head, dstream_count, dstream_cursor;
static bool dstream_overflow;
static uint32_t dstream_gain; /* Snapshot at associated acquisition completion. */
static void dstream_enqueue(dstream_record_t record) {
    if (dstream_count == DSTREAM_QUEUE) { dstream_overflow = true; return; }
    record.magic = UINT32_C(0x31565344); /* DSV1, little endian */
    record.crc = esp_rom_crc32_le(0, (const uint8_t *)&record, 44);
    dstream_queue[(dstream_head + dstream_count) % DSTREAM_QUEUE] = record;
    dstream_count++;
}
#include "detector_stream_iq.h"
static void dstream_pump(void) {
    /* A fixed two-record budget can recover transient backlog. All writes
     * remain FIFO-nonblocking; stop immediately when no progress is possible. */
    unsigned budget = dstream_iq.every ? 128 : 96;
    if (dstream_iq.cursor) {
        unsigned sent=dstream_iq_send(budget); budget-=sent;
        if(dstream_iq.cursor) return;
    }
    while (dstream_count && budget) {
        const uint8_t *p = (const uint8_t *)&dstream_queue[dstream_head];
        unsigned remaining = 48 - dstream_cursor;
        unsigned request = remaining < budget ? remaining : budget;
        unsigned sent = burst_serial_try_send(p + dstream_cursor, request);
        if (!sent) break;
        dstream_cursor += sent;
        budget -= sent;
        if (dstream_cursor == 48) {
            dstream_head = (dstream_head + 1) % DSTREAM_QUEUE;
            dstream_cursor = 0; dstream_count--;
        }
    }
    /* Use the remaining bounded budget, not just one sparse frame. Timing
     * has priority at every boundary; this command task is the sole writer. */
    while (budget && !dstream_count && dstream_iq.busy) {
        unsigned sent=dstream_iq_send(budget);
        if(!sent) break; /* FIFO full: no spinning and no acquisition stall. */
        budget-=sent;
    }
}
static bool dstream_drain(void) {
    if (dstream_iq.every) {
        int64_t until=esp_timer_get_time()+2000000;
        while(dstream_count || dstream_iq.busy) {
            dstream_pump();
            if(esp_timer_get_time()>until) return false;
            vTaskDelay(1);
        }
        return true;
    }
    while (dstream_count) {
        const uint8_t *p = (const uint8_t *)&dstream_queue[dstream_head];
        if (!burst_serial_send(p + dstream_cursor, 48 - dstream_cursor)) return false;
        dstream_cursor = 0; dstream_head = (dstream_head + 1) % DSTREAM_QUEUE; dstream_count--;
    }
    return true;
}
static void dstream_commit(detpipe_state_t *p, unsigned ratio) {
    if (!p->pending) return;
    detpipe_compute(p);
    uint64_t t = esp_timer_get_time();
    unsigned score;
    bool positive = detector_background_step(&p->background, p->mean, p->peak, ratio, &score);
    p->processed++; p->events += positive;
    if (score > p->best_ratio) p->best_ratio = score;
    dstream_enqueue((dstream_record_t){.sequence=p->generation,
        .trigger=p->trigger_device_us, .mean=p->mean, .peak=p->peak,
        .background=(uint32_t)(p->background.q16 >> 16), .events=p->events,
        .flags=(positive ? 1u : 0u) | (p->processed > 16 ? 2u : 0u),
        .observed_us=p->observed_us, .gain=dstream_gain});
    dstream_iq_snapshot(p);
    p->commit_us += esp_timer_get_time() - t;
    p->pending=p->ready=false;
}
typedef struct { detpipe_state_t *p; unsigned ratio; } dstream_validation_t;
static unsigned dstream_validate(void *context, unsigned n) {
    dstream_validation_t *v = context;
    dstream_commit(v->p, v->ratio);
    uint64_t t=esp_timer_get_time();
    unsigned bad=vc_candidate_select(2)(samples, v->p->copy, n);
    v->p->copy_us += esp_timer_get_time()-t;
    return bad;
}
#include "dstream_idle.h"
/* Experimental tick-aware yielding: preserve watchdog/idle servicing while
 * preferring a tick that fits inside the next scheduled acquisition gap.
 * Always force a yield after at most 64 captures, even when no fit is found. */
typedef struct { int64_t origin_us; unsigned since, forced, yielded; TickType_t tick;
    uint64_t max_delay_us, max_estimated_wake_late_us, max_guard_us;
} dstream_yield_t;
static void dstream_tick_observe(dstream_yield_t *y) {
    TickType_t before=xTaskGetTickCount();int64_t now=esp_timer_get_time();
    TickType_t after=xTaskGetTickCount();
    if (before!=after) return;
    int64_t origin=now-(int64_t)after*portTICK_PERIOD_MS*1000;
    if (after<y->tick || origin<y->origin_us) y->origin_us=origin;
    y->tick=after;
}
static void dstream_smart_yield(dstream_yield_t *y) {
    y->since++;
    dstream_tick_observe(y);
    int64_t now=esp_timer_get_time();
    TickType_t tick=xTaskGetTickCount();
    bool fit=false;
    int64_t next_tick=0;
    /* Historical phase32 fit heuristic restored: adaptive max-based guard
     * regressed measured coverage. Diagnostics remain; neither is a guarantee. */
    uint64_t guard=80;
    if (guard>y->max_guard_us) y->max_guard_us=guard;
    if (y->origin_us!=INT64_MAX && tick>=y->tick) {
        next_tick=((int64_t)tick+1)*portTICK_PERIOD_MS*1000+y->origin_us;
        fit=y->since>=16 && next_tick>now && next_tick+(int64_t)guard<(int64_t)dual_next;
    }
    if (!fit && y->since<64) return;
    if (!fit) y->forced++;
    int64_t before_delay=esp_timer_get_time();
    vTaskDelay(1);
    int64_t after_delay=esp_timer_get_time();
    uint64_t elapsed=(uint64_t)(after_delay-before_delay);
    if (elapsed>y->max_delay_us) y->max_delay_us=elapsed;
    if (next_tick && after_delay>next_tick) {
        uint64_t late=(uint64_t)(after_delay-next_tick);
        if (late>y->max_estimated_wake_late_us) y->max_estimated_wake_late_us=late;
    }
    y->since=0;y->yielded++;dstream_tick_observe(y);
}
static bool detector_stream_command(const char *line) {
    if (!strcmp(line, "DSTREAM?")) { reply("DSTREAM 1 600000 16380 16000000 48\n"); return true; }
    if (strncmp(line, "DSTREAM", 7)) return false;
    bool iq=!strncmp(line,"DSTREAMIQ ",10);
    uint64_t a[7]={0}, now=esp_timer_get_time();
    /* deadline_us duration_ms period_ns yield_phase ratio_milli. Duration=0
     * deliberately forbidden in first experimental release (10-minute cap). */
    if (!dual_arguments(line+(iq?9:7),a,iq?7:5) || a[0]<now+10000 || a[0]>now+5000000 ||
        a[1]<1 || a[1]>600000 || a[2]<1600000 || a[2]>10000000 ||
        a[3]>33 || a[4]<1000 || a[4]>1000000 || dual_armed ||
        (iq && (a[5]<1024 || a[5]>1000000 || a[6]>=a[5]))) {
        reply("ERR stream_args\n"); return true;
    }
    dual_trace_end();
    if (dual_trace) { heap_caps_free(dual_trace); dual_trace=NULL; }
    dual_count=0;
    detpipe_clear();
    if (det_retained) { heap_caps_free(det_retained); det_retained=NULL; }
    det_retained_n=0;
    detpipe_state_t p={.n=MAX_SAMPLES,.kernel=3,
        .background=detector_background_start(detector_background_policy)};
    p.copy=heap_caps_malloc(MAX_SAMPLES*sizeof(uint32_t),DETPIPE_ALLOC_CAPS);
    if (!detpipe_safe_buffer(p.copy,MAX_SAMPLES*sizeof(uint32_t)) ||
        !detpipe_safe_buffer(dstream_queue,sizeof(dstream_queue))) {
        if (p.copy) heap_caps_free(p.copy);
        reply("ERR stream_memory\n"); return true;
    }
    memset(&dstream_iq,0,sizeof(dstream_iq));
    int allocated=iq?dstream_iq_allocate(p.copy):1;
    if(allocated<0) {reply("ERR stream_iq_alias_reset_required\n");return true;}
    if(!allocated) {
        heap_caps_free(p.copy);detpipe_clear();reply("ERR stream_iq_memory\n");return true;
    }
    dstream_idle_t idle={0};
    if(a[3]==33 && !dstream_idle_begin(&idle)) {
        heap_caps_free(p.copy);detpipe_clear();reply("ERR stream_idle_hook\n");return true;
    }
    dstream_iq.every=a[5];dstream_iq.phase=a[6];
    dstream_head=dstream_count=dstream_cursor=0;dstream_overflow=false;
    capture_pretrigger_max_us=0;
    unsigned old_acq=acquisition_option,old_clear=clear_option;
    acquisition_option=3;clear_option=1;
    prepare_rx();
    dstream_yield_t yielding={.origin_us=INT64_MAX};
    if(a[3]==32) {vTaskDelay(1);dstream_tick_observe(&yielding);}
    unsigned min_heap=heap_caps_get_free_size(DETPIPE_ALLOC_CAPS);
    unsigned min_stack=uxTaskGetStackHighWaterMark(NULL),status=0,captures=0;
    if(iq) reply("DSTREAM BEGIN 1 %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 " %u %u %" PRIu64 " %" PRIu64 "\n",
        a[0],a[1],a[2],a[3],a[4],frequency_mhz,detector_background_policy,a[5],a[6]);
    else reply("DSTREAM BEGIN 1 %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 " %u %u\n",
        a[0],a[1],a[2],a[3],a[4],frequency_mhz,detector_background_policy);
    dual_period=a[2]/1000;dual_period_ns=a[2];dual_fraction_ns=0;
    dual_next=a[0];dual_late=dual_skipped=0;
    uint64_t first=0,last=0,stop=a[0]+a[1]*1000;
    deferred_error[0]=0;deferred_reply=true;
    while ((uint64_t)esp_timer_get_time()<stop) {
        unsigned observed=0;
        dstream_validation_t validation={&p,(unsigned)a[4]};
        bool ok=acquire_iq_with_validation(MAX_SAMPLES,0,0,&observed,
            detpipe_compute,&p,dstream_validate,&validation);
        if (!ok) {status=1;break;}
        captures++;
        if (!first) first=capture_trigger_device_us;
        last=capture_trigger_device_us;
        p.generation=captures;p.observed_us=observed;
        p.trigger_device_us=capture_trigger_device_us;p.pending=true;p.ready=false;
        dstream_gain=REG_READ(RX_GAIN);
        dstream_pump();
        if (dstream_overflow) {status=2;break;}
        if(dstream_iq.errors) {status=4;break;}
        if (burst_serial_stop_requested()) {status=3;break;}
        if(a[3]==33) dstream_idle_service(&idle);
        else if(a[3]==32) dstream_smart_yield(&yielding);
        else if ((captures&31u)==a[3]) vTaskDelay(1);
        if (!(captures&127u)) {
            unsigned heap=heap_caps_get_free_size(DETPIPE_ALLOC_CAPS);
            unsigned stack=uxTaskGetStackHighWaterMark(NULL);
            if (heap<min_heap) min_heap=heap;
            if (stack<min_stack) min_stack=stack;
        }
    }
    dstream_idle_end(&idle);
    dual_trace_end();
    dstream_commit(&p,a[4]);
    deferred_reply=false;
    if (dstream_overflow && !status) status=2;
    if(dstream_iq.errors) status=4;
    /* Consume fragments of the stop line before announcing completion.
     * Never drain input after END: that could swallow the next host command. */
    burst_serial_stop_requested();
    bool delivered=dstream_drain();
    uint64_t ended=esp_timer_get_time();
    if (delivered) dstream_enqueue((dstream_record_t){.sequence=p.processed,.trigger=ended,
        .mean=status,.peak=dual_late,.background=dual_skipped,.events=p.events,
        .flags=DSTREAM_END,.observed_us=(uint32_t)(ended-a[0]),.gain=REG_READ(RX_GAIN)});
    if (delivered) delivered=dstream_drain();
    heap_caps_free(p.copy);detpipe_clear();acquisition_option=old_acq;clear_option=old_clear;
    if (delivered) {
        char summary[1024];
        int n=snprintf(summary,sizeof(summary),
            "DSTREAM END {\"status\":%u,\"captures\":%u,\"processed\":%u,\"events\":%u,"
            "\"first_trigger_us\":%" PRIu64 ",\"last_trigger_us\":%" PRIu64 ","
            "\"end_us\":%" PRIu64 ",\"max_late_us\":%u,\"skipped\":%u,"
            "\"overflow\":%u,\"min_heap\":%u,\"min_stack\":%u,\"compute_us\":%" PRIu64 ","
            "\"copy_us\":%" PRIu64 ",\"decision_us\":%" PRIu64 ",\"smart_yields\":%u,\"forced_yields\":%u,\"setup_max_us\":%" PRIu64 ",\"yield_delay_max_us\":%" PRIu64 ",\"estimated_wake_late_max_us\":%" PRIu64 ",\"yield_guard_max_us\":%" PRIu64 ",\"idle_handshakes\":%u,\"idle_observed\":%u,\"idle_fallbacks\":%u,\"idle_attempts_max\":%u,\"idle_latency_max_us\":%" PRIu64 ",\"retained\":0,\"iq_produced\":%u,\"iq_sent\":%u,\"iq_busy_skips\":%u}\n",
            status,captures,p.processed,p.events,first,last,ended,dual_late,dual_skipped,
            (unsigned)dstream_overflow,min_heap,min_stack,p.compute_us,p.copy_us,p.commit_us,yielding.yielded,yielding.forced,capture_pretrigger_max_us,yielding.max_delay_us,yielding.max_estimated_wake_late_us,yielding.max_guard_us,idle.handshakes,idle.observed,idle.fallbacks,idle.attempts_max,idle.latency_max_us,dstream_iq.produced,dstream_iq.sent,dstream_iq.skipped);
        if(n>0 && (unsigned)n<sizeof(summary)) {
            size_t length=ascii_frame_pad(summary,n,sizeof(summary));
            /* Empirical workaround for observed post-stream summary truncation.
             * Acquisition is already stopped: bounded paced chunks cannot open
             * gaps in the measured run. Never use this inside acquisition. */
            for (size_t off=0;off<length;) {
                size_t chunk=length-off>32?32:length-off;
                if(!burst_serial_send(summary+off,chunk)) break;
                off+=chunk;vTaskDelay(1);
            }
        }
        if (deferred_error[0]) burst_serial_send(deferred_error,strlen(deferred_error));
    }
    return true;
}
