"""Compile the actual experimental queue/phase helpers without device access."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ROOT / 'firmware/main/targets/esp32'


def compile_run(tmp_path, code):
    cc = shutil.which('cc')
    if not cc:
        pytest.skip('host C compiler unavailable')
    src = tmp_path / 'review.c'
    src.write_text(code)
    exe = tmp_path / 'review'
    subprocess.run(
        [cc, '-std=c11', '-Wall', '-Wextra', str(src), '-o', str(exe)],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(exe)], check=True, capture_output=True)


def test_actual_dstream_queue_partial_writes_wrap_and_overflow(tmp_path):
    source = (HEADERS / 'detector_stream.h').read_text()
    helpers = source[
        source.index('#define DSTREAM_QUEUE') : source.index('static void dstream_commit')
    ]
    helpers = helpers.replace(
        '#include "detector_stream_iq.h"',
        'static struct {unsigned every,cursor;bool busy;} dstream_iq;\nstatic unsigned dstream_iq_send(unsigned n){(void)n;return 0;}\nstatic void dstream_iq_crc_step(void){}\nstatic int64_t esp_timer_get_time(void){return 0;}\nstatic void vTaskDelay(unsigned n){(void)n;}',
    )
    compile_run(
        tmp_path,
        r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
static unsigned char wire[100000];
static size_t used, budget;
static uint32_t esp_rom_crc32_le(uint32_t initial,const uint8_t *p,size_t n) {
    uint32_t v=initial; while(n--) v=v*33+*p++; return v;
}
static size_t burst_serial_try_send(const void *p,size_t n) {
    if(n>budget)n=budget; memcpy(wire+used,p,n); used+=n; budget-=n; return n;
}
static bool burst_serial_send(const void *p,size_t n) {
    memcpy(wire+used,p,n); used+=n; return true;
}
"""
        + helpers
        + r"""
int main(void) {
    for(unsigned j=0;j<64;j++)dstream_enqueue((dstream_record_t){.sequence=j,.trigger=10000000000ULL+j});
    assert(dstream_count==64 && !dstream_overflow);
    dstream_enqueue((dstream_record_t){.sequence=999});
    assert(dstream_overflow && dstream_count==64);
    budget=0;dstream_pump();assert(used==0 && dstream_cursor==0);
    budget=7;
    for(unsigned j=0;j<6;j++){budget=7;dstream_pump();}
    budget=6;dstream_pump();
    assert(used==48 && dstream_count==63 && dstream_cursor==0);
    dstream_enqueue((dstream_record_t){.sequence=64});
    budget=1000;dstream_pump();assert(used==144 && dstream_count==62);
    while(dstream_count){budget=1000;dstream_pump();}
    assert(used==65*48);
    for(unsigned j=0;j<65;j++) {
        dstream_record_t r;memcpy(&r,wire+j*48,48);
        assert(r.sequence==j && r.magic==0x31565344);
        assert(r.crc==esp_rom_crc32_le(0,wire+j*48,44));
    }
    dstream_enqueue((dstream_record_t){.sequence=65});
    budget=13;dstream_pump();assert(dstream_cursor==13);
    assert(dstream_drain());assert(used==66*48 && !dstream_count);
    return 0;
}
""",
    )


def test_actual_fractional_period_accumulation(tmp_path):
    source = (HEADERS / 'dual_timing.h').read_text()
    helper = source[
        source.index('static inline void dual_advance') : source.index(
            'static inline void dual_wait_trigger'
        )
    ]
    compile_run(
        tmp_path,
        r"""
#include <stdint.h>
#include <assert.h>
static uint64_t dual_next;
static unsigned dual_period_ns,dual_fraction_ns,dual_period;
"""
        + helper
        + r"""
int main(void) {
    dual_period_ns=1875044;dual_next=1000000000ULL;
    for(unsigned j=0;j<320000;j++)dual_advance(1);
    assert(dual_next==1000000000ULL+320000ULL*1875044/1000);
    assert(dual_fraction_ns==(320000ULL*1875044)%1000);
    dual_next=1000000000ULL;dual_fraction_ns=0;dual_advance(320000);
    assert(dual_next==1000000000ULL+320000ULL*1875044/1000);
    dual_period_ns=0;dual_period=1875;dual_fraction_ns=999;dual_next=0;
    dual_advance(300);assert(dual_next==562500 && !dual_fraction_ns);
    return 0;
}
""",
    )


def test_actual_smart_yield_observation_fit_force_and_wrap(tmp_path):
    source = (HEADERS / 'detector_stream.h').read_text()
    helper = source[
        source.index('typedef struct { int64_t origin_us;') : source.index(
            'static bool detector_stream_command'
        )
    ]
    compile_run(
        tmp_path,
        r"""
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
typedef uint32_t TickType_t;
#define portTICK_PERIOD_MS 1
static TickType_t tick;
static int64_t now_us;
static uint64_t dual_next;
static unsigned delays;
static uint64_t capture_pretrigger_max_us;
static unsigned delay_us;
static bool changing;
static TickType_t xTaskGetTickCount(void) {
    TickType_t result=tick; if(changing)tick++; return result;
}
static int64_t esp_timer_get_time(void) { return now_us; }
static void vTaskDelay(unsigned n) { assert(n==1); delays++;now_us+=delay_us; }
"""
        + helper
        + r"""
int main(void) {
    dstream_yield_t y={.origin_us=INT64_MAX};
    tick=10;now_us=10500;
    dstream_tick_observe(&y);
    assert(y.origin_us==500 && y.tick==10);
    now_us=10700;dstream_tick_observe(&y);
    assert(y.origin_us==500); /* Keep tightest observed tick boundary. */
    now_us=10200;dstream_tick_observe(&y);assert(y.origin_us==200);
    changing=true;now_us=1;dstream_tick_observe(&y);
    assert(y.origin_us==200 && y.tick==10); /* Straddled ticks rejected. */

    /* No valid origin at all: must never overflow sentinel arithmetic and
       must still service idle/watchdog at the 64-capture bound. */
    y=(dstream_yield_t){.origin_us=INT64_MAX};delays=0;
    dual_next=UINT64_C(1000000);now_us=100;
    for(unsigned i=0;i<63;i++)dstream_smart_yield(&y);
    assert(delays==0 && y.since==63 && y.origin_us==INT64_MAX);
    dstream_smart_yield(&y);
    assert(delays==1 && y.forced==1 && y.yielded==1 && y.since==0);

    changing=false;tick=10;now_us=10000;
    y=(dstream_yield_t){.origin_us=INT64_MAX};delays=0;dual_next=11081;
    for(unsigned i=0;i<15;i++)dstream_smart_yield(&y);
    assert(!delays); /* Never fit-yield before 16 captures. */
    dstream_smart_yield(&y);
    assert(delays==1 && y.forced==0 && y.yielded==1);
    y.since=15;dual_next=11080;dstream_smart_yield(&y);
    assert(delays==1 && y.since==16); /* Margin comparison is strict. */
    y.since=63;dual_next=10000;dstream_smart_yield(&y);
    assert(delays==2 && y.forced==1 && y.since==0);

    /* Stable observation after the 32-bit tick wraps must rebase origin,
       even though its numerical origin is larger than the previous one. */
    y=(dstream_yield_t){.origin_us=0,.tick=UINT32_MAX};
    tick=0;now_us=(INT64_C(1)<<32)*1000+7;
    dstream_tick_observe(&y);
    assert(y.tick==0 && y.origin_us==now_us);
    y.since=15;dual_next=(uint64_t)now_us+1081;
    dstream_smart_yield(&y);
    assert(delays==3 && y.forced==0 && y.yielded==1 && y.since==0);
    /* Rejected adaptive guard does not ratchet historical phase32. */
    tick=10;now_us=10000;capture_pretrigger_max_us=300;
    y=(dstream_yield_t){.origin_us=0,.since=15};dual_next=11200;delay_us=1250;
    unsigned previous=delays;dstream_smart_yield(&y);
    assert(delays==previous+1 && y.max_guard_us==80);
    assert(y.max_delay_us==1250 && y.max_estimated_wake_late_us==250);
    return 0;
}
""",
    )


def test_idle_handshake_requires_hook_and_restores_priority(tmp_path):
    helper = (HEADERS / 'dstream_idle.h').read_text().replace('#pragma once', '')
    compile_run(
        tmp_path,
        r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
typedef unsigned UBaseType_t;
#define ESP_OK 0
#define tskIDLE_PRIORITY 0
static unsigned priority=5, yields, delays, registered, removed, mode;
static int64_t now;
static bool (*hook)(void);
static unsigned xPortGetCoreID(void) {return 0;}
static int esp_register_freertos_idle_hook_for_cpu(bool (*h)(void),unsigned c) {
    assert(c==0);if(mode==9)return -1;hook=h;registered++;return 0;
}
static void esp_deregister_freertos_idle_hook_for_cpu(bool (*h)(void),unsigned c) {
    assert(c==0 && h==hook);removed++;hook=NULL;
}
static int64_t esp_timer_get_time(void) {return now;}
static unsigned uxTaskPriorityGet(void *t) {(void)t;return priority;}
static void vTaskPrioritySet(void *t,unsigned p) {(void)t;priority=p;}
static void vTaskDelay(unsigned ticks) {assert(ticks==1 && priority==5);delays++;now+=1000;}
static void taskYIELD(void) {
    assert(priority==0);yields++;now+=mode==2?1000:10;
    /* First yield merely returns from idle's pre-hook yield. Only second
       scheduling turn reaches the registered callback. */
    if(mode==0 && yields%2==0) assert(!hook());
}
"""
        + helper
        + r"""
int main(void) {
    dstream_idle_t s={0};
    assert(dstream_idle_begin(&s) && registered==1);
    assert(hook()); /* Outside handshake normal WFI remains allowed. */
    for(unsigned i=0;i<31;i++)dstream_idle_service(&s);
    assert(!yields && !s.handshakes);
    dstream_idle_service(&s);
    assert(yields==2 && s.observed==1 && !s.fallbacks && s.attempts_max==2);
    assert(priority==5 && !dstream_idle_active && hook());
    mode=1;s.since=31;unsigned previous=yields;dstream_idle_service(&s);
    assert(yields-previous==8 && s.fallbacks==1 && delays==1);
    assert(priority==5 && !dstream_idle_active);
    mode=2;s.since=31;previous=yields;dstream_idle_service(&s);
    assert(yields-previous==2 && s.fallbacks==2 && delays==2);
    assert(s.latency_max_us==3000); /* Time cap plus bounded requested delay. */
    dstream_idle_end(&s);assert(removed==1 && !s.registered && !hook);
    dstream_idle_end(&s);assert(removed==1);
    mode=9;s=(dstream_idle_t){0};assert(!dstream_idle_begin(&s));
    dstream_idle_end(&s);assert(removed==1 && !dstream_idle_active);
    return 0;
}
""",
    )


def test_idle_semaphore_wake_static_lifetime_and_timeout(tmp_path):
    helper = (HEADERS / 'dstream_idle_wake.h').read_text().replace('#pragma once', '')
    compile_run(
        tmp_path,
        r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
typedef struct {unsigned token;} StaticSemaphore_t;
typedef StaticSemaphore_t *SemaphoreHandle_t;
typedef int BaseType_t;
#define pdTRUE 1
#define ESP_OK 0
typedef struct {
 bool registered; unsigned core,since,handshakes,observed,fallbacks,attempts_max;
 uint64_t latency_max_us;
} dstream_idle_t;
static unsigned creates, registrations, removals, delays, mode;
static int64_t now;
static bool (*hook)(void);
static unsigned xPortGetCoreID(void) {return 0;}
static int esp_register_freertos_idle_hook_for_cpu(bool (*h)(void),unsigned c) {
 assert(c==0);if(mode==9)return -1;hook=h;registrations++;return 0;
}
static void esp_deregister_freertos_idle_hook_for_cpu(bool (*h)(void),unsigned c) {
 assert(c==0 && hook==h);removals++;hook=NULL;
}
static SemaphoreHandle_t xSemaphoreCreateBinaryStatic(StaticSemaphore_t *s) {
 creates++;s->token=0;return s;
}
static int xSemaphoreGive(SemaphoreHandle_t s) {assert(!s->token);s->token=1;return pdTRUE;}
static int xSemaphoreTake(SemaphoreHandle_t s,unsigned ticks) {
 if(s->token){s->token=0;return pdTRUE;}
 if(!ticks)return 0;
 assert(ticks==2);
 if(mode==0){now+=25;assert(!hook());assert(s->token);s->token=0;return pdTRUE;}
 now+=2000;return 0;
}
static int64_t esp_timer_get_time(void) {return now;}
static void vTaskDelay(unsigned t) {assert(t==1);delays++;now+=1000;}
"""
        + helper
        + r"""
int main(void) {
 dstream_idle_t s={0};assert(dstream_wake_begin(&s));
 assert(creates==1 && registrations==1 && hook());
 for(unsigned i=0;i<31;i++)dstream_wake_service(&s);
 assert(!s.handshakes);
 /* Even a stale success token must be drained, not counted as idle work. */
 dstream_wake_sem->token=1;
 dstream_wake_service(&s);
 assert(s.handshakes==1 && s.observed==1 && !s.fallbacks);
 assert(!dstream_wake_armed && s.latency_max_us==25 && hook());
 mode=1;s.since=31;dstream_wake_service(&s);
 assert(s.fallbacks==1 && delays==1 && !dstream_wake_armed);
 assert(s.latency_max_us==3000 && s.attempts_max==1);
 SemaphoreHandle_t original=dstream_wake_sem;
 dstream_wake_end(&s);assert(removals==1 && !s.registered);
 /* A callback suspended inside give may later resume; static object survives.
    Begin drains any old token without recreating or deleting that object. */
 original->token=1;mode=0;s=(dstream_idle_t){0};assert(dstream_wake_begin(&s));
 assert(creates==1 && original==dstream_wake_sem && !original->token);
 dstream_wake_counter=UINT32_MAX;s.since=31;dstream_wake_service(&s);
 assert(s.observed==1 && dstream_wake_counter==0);
 dstream_wake_end(&s);dstream_wake_end(&s);assert(removals==2);
 mode=9;s=(dstream_idle_t){0};assert(!dstream_wake_begin(&s));
 dstream_wake_end(&s);assert(removals==2 && creates==1);
 return 0;
}
""",
    )
