#pragma once
/* Proposal only: finite single-core overlap. Include after detector_experiment.h.
 * No live reads of RF-owned SRAM. DETPIPEGET retrieves the strongest packed copy.
 * Requires acquire_iq_with_work() from accompanying receiver patch. */
#include "esp_memory_utils.h"
#include "dual_timing.h"

#include "pipeline_energy3.h"
#include "detector_retention.h"
#include "pack20_candidates.h"
#include "ascii_frame.h"
#include "validate_copy_runtime.h"
#define DETPIPE_ALLOC_CAPS (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT | MALLOC_CAP_DMA)
#include "pipeline_health.h"
#define DETPIPE_PAGE_BYTES 4096u
#define DETPIPE_MAX_PACKED ((MAX_SAMPLES * 20u + 7u) / 8u)
#define DETPIPE_MAX_PAGES 12u /* max(10 legacy pages, 3 x 4 crop pages) */
static uint8_t *detpipe_pages[DETPIPE_MAX_PAGES];
static size_t detpipe_page_sizes[DETPIPE_MAX_PAGES];
static unsigned detpipe_page_count;
static unsigned detpipe_keep = 1, detpipe_run_keep = 1;
static unsigned detpipe_candidate_pages, detpipe_best_slot;
static detector_candidate_t detpipe_candidates[DETECTOR_CANDIDATES];
static unsigned detpipe_copy_option; /* 0 separate; 1 fused only at full length */
static unsigned detpipe_kernel; /* default 0: unchanged v2 kernel */
static uint64_t detpipe_retained_trigger_us;
static unsigned detpipe_retained_n, detpipe_retained_us, detpipe_retained_generation;
static void detpipe_clear(void) {
    for (unsigned page = 0; page < detpipe_page_count; page++) {
        heap_caps_free(detpipe_pages[page]);
        detpipe_pages[page] = NULL; detpipe_page_sizes[page] = 0;
    }
    detpipe_page_count = 0; detpipe_retained_n = 0;
    detpipe_retained_trigger_us = 0;
    memset(detpipe_candidates, 0, sizeof(detpipe_candidates));
    detpipe_candidate_pages = detpipe_best_slot = 0;
    detpipe_retained_us = detpipe_retained_generation = 0;
}
/* Validated aligned CAP20 packer. All allocation/range guards remain mandatory.
 * Candidate validates source/page alignment before writing any byte. */
static bool detpipe_pack(const uint32_t *words, unsigned n) {
    uint32_t *pages[DETPIPE_MAX_PAGES];
    if(n>MAX_SAMPLES || detpipe_page_count != ((n*20u+7u)/8u+DETPIPE_PAGE_BYTES-1)/DETPIPE_PAGE_BYTES)return false;
    size_t left=(n*20u+7u)/8u;
    for(unsigned j=0;j<detpipe_page_count;j++){
        size_t needed=left>DETPIPE_PAGE_BYTES?DETPIPE_PAGE_BYTES:left;
        if(detpipe_page_sizes[j]<needed)return false;
        pages[j]=(uint32_t*)detpipe_pages[j];left-=needed;
    }
    return pack20_words8(words,n,pages);
}
static uint32_t detpipe_crc(void) {
    uint32_t crc = 0;
    for (unsigned page = 0; page < detpipe_page_count; page++)
        crc = esp_rom_crc32_le(crc, detpipe_pages[page], detpipe_page_sizes[page]);
    return crc;
}

static bool detpipe_pack_candidate(const uint32_t *words, unsigned crop, unsigned slot) {
    uint32_t *pages[4];
    if (slot >= DETECTOR_CANDIDATES || !detpipe_candidate_pages || detpipe_candidate_pages > 4) return false;
    size_t left = (crop * 20u + 7u) / 8u;
    for (unsigned j = 0; j < detpipe_candidate_pages; j++) {
        unsigned index = slot * detpipe_candidate_pages + j;
        size_t needed = left > DETPIPE_PAGE_BYTES ? DETPIPE_PAGE_BYTES : left;
        if (index >= detpipe_page_count || detpipe_page_sizes[index] != needed) return false;
        pages[j] = (uint32_t *)detpipe_pages[index]; left -= needed;
    }
    return !left && pack20_words8(words, crop, pages);
}
static void detpipe_send_candidate(unsigned slot) {
    if (slot >= DETECTOR_CANDIDATES || !detpipe_candidates[slot].samples) {
        reply("ERR no_retained_event\n"); return;
    }
    detector_candidate_t *candidate = &detpipe_candidates[slot];
    uint32_t crc = 0;
    for (unsigned j = 0; j < detpipe_candidate_pages; j++) {
        unsigned page = slot * detpipe_candidate_pages + j;
        crc = esp_rom_crc32_le(crc, detpipe_pages[page], detpipe_page_sizes[page]);
    }
    char header[96];
    int length = snprintf(header, sizeof(header), "DATA %u %08" PRIx32 " %u\n",
                          candidate->samples, crc, candidate->capture_us);
    if (length > 0 && (size_t)length < sizeof(header) && burst_serial_send(header, length)) {
        for (unsigned j = 0; j < detpipe_candidate_pages; j++) {
            unsigned page = slot * detpipe_candidate_pages + j;
            if (!burst_serial_send(detpipe_pages[page], detpipe_page_sizes[page])) break;
        }
    }
}

typedef struct {
    uint32_t *copy;
    unsigned n, observed_us, generation, processed, kernel;
    uint32_t mean, peak;
    bool pending, ready, pack_failed;
    uint64_t compute_us, copy_us, commit_us, retention_us, trigger_device_us;
    unsigned best_ratio, events;
    detector_background_t background;
} detpipe_state_t;

static bool detpipe_safe_buffer(const void *p, size_t bytes) {
    uintptr_t lo = (uintptr_t)p;
    if (!p || !bytes || lo > UINTPTR_MAX - (bytes - 1)) return false;
    uintptr_t hi = lo + bytes - 1;
    return esp_ptr_internal(p) && esp_ptr_in_dram(p) &&
           esp_ptr_in_dram((const void *)hi) && esp_ptr_byte_accessible(p) &&
           (hi < UINT32_C(0x3ffe8000) || lo >= UINT32_C(0x3fff8000));
}

/* Diagnostic predicates are observational only: safety rules remain unchanged. */
static void detpipe_allocation_report(const char *prefix,const char *stage,unsigned page,const void *ptr,size_t bytes){
    uintptr_t lo=(uintptr_t)ptr;bool range=ptr&&bytes&&lo<=UINTPTR_MAX-(bytes-1);
    uintptr_t hi=range?lo+bytes-1:lo;
    bool internal=ptr&&esp_ptr_internal(ptr),dram_lo=ptr&&esp_ptr_in_dram(ptr);
    bool dram_hi=range&&esp_ptr_in_dram((const void *)hi),byte=ptr&&esp_ptr_byte_accessible(ptr);
    bool outside=range&&(hi<UINT32_C(0x3ffe8000)||lo>=UINT32_C(0x3fff8000));
    reply("%s stage=%s page=%u ptr=0x%" PRIxPTR " bytes=%u caps=%u free=%u largest=%u internal=%u dram_lo=%u dram_hi=%u byte=%u aperture=%u range=%u\n",
          prefix,stage,page,lo,(unsigned)bytes,(unsigned)DETPIPE_ALLOC_CAPS,
          (unsigned)heap_caps_get_free_size(DETPIPE_ALLOC_CAPS),
          (unsigned)heap_caps_get_largest_free_block(DETPIPE_ALLOC_CAPS),
          (unsigned)internal,(unsigned)dram_lo,(unsigned)dram_hi,(unsigned)byte,(unsigned)outside,(unsigned)range);
}
static bool detpipe_allocation_test(unsigned n,unsigned retain){
    /* Matches pipeline ownership: prior saved captures are explicitly discarded. */
    detpipe_clear();det_retained_n=0;if(det_retained){heap_caps_free(det_retained);det_retained=NULL;}
    reply("DETPIPEALLOC BEGIN %u %u\n",n,retain);
    uint8_t *pages[DETPIPE_MAX_PAGES]={0};size_t sizes[DETPIPE_MAX_PAGES]={0};unsigned count=0,status=0;
    size_t bytes=n*sizeof(uint32_t);void *raw=heap_caps_malloc(bytes,DETPIPE_ALLOC_CAPS);
    detpipe_allocation_report("DETPIPEALLOC","raw",0,raw,bytes);
    if(!detpipe_safe_buffer(raw,bytes)){status=1;goto cleanup;}
    for(size_t left=retain?(n*20u+7u)/8u:0;left;){
        size_t amount=left>DETPIPE_PAGE_BYTES?DETPIPE_PAGE_BYTES:left;
        void *p=heap_caps_malloc(amount,DETPIPE_ALLOC_CAPS);
        detpipe_allocation_report("DETPIPEALLOC","page",count,p,amount);
        if(!detpipe_safe_buffer(p,amount)){if(p)heap_caps_free(p);status=1;goto cleanup;}
        uintptr_t lo=(uintptr_t)p,hi=lo+amount-1,raw_lo=(uintptr_t)raw;
        bool disjoint=hi<raw_lo||lo>raw_lo+bytes-1;
        for(unsigned j=0;j<count;j++){uintptr_t other=(uintptr_t)pages[j];disjoint=disjoint&&(hi<other||lo>other+sizes[j]-1);}
        if(!disjoint||count>=DETPIPE_MAX_PAGES){reply("ERR pipeline_alias reset_required\n");return true;}
        pages[count]=p;sizes[count]=amount;count++;left-=amount;
    }
cleanup:
    for(unsigned j=0;j<count;j++)heap_caps_free(pages[j]);
    if(raw)heap_caps_free(raw);
    reply("DETPIPEALLOC END status=%u pages=%u free=%u largest=%u\n",status,count,
          (unsigned)heap_caps_get_free_size(DETPIPE_ALLOC_CAPS),
          (unsigned)heap_caps_get_largest_free_block(DETPIPE_ALLOC_CAPS));
    return true;
}

/* Bounded exact work on ONE previously validated immutable buffer. This callback
 * may run with dump SRAM owned by RF; it touches only state and copy, never samples,
 * radio registers, allocation, UART, scheduler, or retained-buffer state. */
static void detpipe_compute(void *context) {
    detpipe_state_t *p = context;
    if (!p->pending || p->ready) return;
    int64_t t = esp_timer_get_time();
    if (p->kernel == 3) pipeline_energy_flash_3(p->copy, p->n, &p->mean, &p->peak);
    else detector_energy(p->copy, p->n, &p->mean, &p->peak);
    p->compute_us += esp_timer_get_time() - t;
    p->ready = true;
}

/* Called after ownership has been restored, before a pending copy is overwritten.
 * Also drains a valid previous capture after the next acquisition fails. */
static void detpipe_commit(detpipe_state_t *p, unsigned ratio, bool retain) {
    if (!p->pending) return;
    detpipe_compute(p); /* final drain or acquisition failed before callback */
    int64_t t = esp_timer_get_time();
    p->processed++;
    unsigned score;
    if (detector_background_step(&p->background, p->mean, p->peak, ratio, &score)) {
        p->events++;
        if (detpipe_run_keep == 3 && retain) {
            unsigned slot = detector_candidate_slot(detpipe_candidates, 3, score);
            if (slot < 3) {
                int64_t r = esp_timer_get_time();
                unsigned crop = detector_crop_length(p->n);
                unsigned offset = detector_crop_offset(p->copy, p->n, crop);
                if (!detpipe_pack_candidate(p->copy + offset, crop, slot)) p->pack_failed = true;
                else {
                    detpipe_candidates[slot] = (detector_candidate_t){crop, offset,
                        p->generation, score, p->observed_us, p->trigger_device_us};
                    if (score > p->best_ratio) {
                        p->best_ratio = score; detpipe_best_slot = slot;
                        detpipe_retained_n = crop; detpipe_retained_us = p->observed_us;
                        detpipe_retained_generation = p->generation;
                        detpipe_retained_trigger_us = p->trigger_device_us;
                    }
                }
                p->retention_us += esp_timer_get_time() - r;
            }
        } else if (score > p->best_ratio) {
            p->best_ratio = score;
            if (retain) {
                int64_t r = esp_timer_get_time();
                bool packed=detpipe_pack(p->copy,p->n);
                if(!packed)p->pack_failed=true;
                if(packed){
                    detpipe_retained_n = p->n;
                    detpipe_retained_us = p->observed_us;
                    detpipe_retained_generation = p->generation;
                    detpipe_retained_trigger_us = p->trigger_device_us;
                }
                p->retention_us += esp_timer_get_time() - r;
            }
        }
    }
    p->commit_us += esp_timer_get_time() - t;
    p->pending = p->ready = false;
}

/* Invoked only after RF ownership/restoration and hardware completion checks.
 * Commit the PREVIOUS valid copy before overwriting it. Partial current writes
 * on validation failure are never published. Outer drain is then a no-op. */
typedef struct { detpipe_state_t *state; unsigned ratio; bool retain; } detpipe_validation_t;
static unsigned detpipe_validate_copy(void *context, unsigned n) {
    detpipe_validation_t *v = context;
    detpipe_commit(v->state, v->ratio, v->retain);
    int64_t t = esp_timer_get_time();
    unsigned bad = vc_candidate_select(2)(samples, v->state->copy, n);
    v->state->copy_us += esp_timer_get_time() - t; /* includes validation here */
    return bad;
}

static bool detector_pipeline_command(const char *line) {
    if (!strcmp(line, "DETPIPEHEALTH?")) { detpipe_health_report(); return true; }
    if (!strcmp(line, "PIPEKEEP?")) { reply("PIPEKEEP %u\n", detpipe_keep); return true; }
    if (!strncmp(line, "PIPEKEEP", 8)) {
        unsigned count; char extra;
        if (sscanf(line, "PIPEKEEP %u %c", &count, &extra) == 1 && (count == 1 || count == 3)) {
            detpipe_keep = count; reply("PIPEKEEP %u\n", count);
        } else reply("ERR pipeline_keep\n");
        return true;
    }
    if (!strncmp(line, "DETPIPEGET ", 11)) {
        unsigned slot; char extra;
        if (detpipe_run_keep != 3 || sscanf(line, "DETPIPEGET %u %c", &slot, &extra) != 1)
            reply("ERR pipeline_get\n");
        else detpipe_send_candidate(slot);
        return true;
    }
    if (!strcmp(line,"PIPECOPY?")) { reply("PIPECOPY %u\n",detpipe_copy_option); return true; }
    if (!strncmp(line,"PIPECOPY",8)) {
        unsigned mode; char extra;
        if (sscanf(line,"PIPECOPY %u %c",&mode,&extra)==1 && mode<=1) {
            detpipe_copy_option=mode; reply("PIPECOPY %u\n",mode);
        } else reply("ERR pipeline_copy\n");
        return true;
    }
    if(!strncmp(line,"DETPIPEALLOCTEST",15)){
        unsigned n,retain;char extra;
        if(sscanf(line,"DETPIPEALLOCTEST %u %u %c",&n,&retain,&extra)!=2||n<256||n>MAX_SAMPLES||retain>1){reply("ERR pipeline_alloc_args\n");return true;}
        return detpipe_allocation_test(n,retain);
    }
    /* Background rule for the next DET1 or DETPIPE1 run. Sticky like PIPEKERNEL,
     * so clients must set and read it back; every END summary reports the rule
     * that actually ran. Policy 1 is the measured optimized-v2 rule. */
    if (!strcmp(line, "BGPOLICY?")) { reply("BGPOLICY %u\n", detector_background_policy); return true; }
    if (!strncmp(line, "BGPOLICY", 8)) {
        /* Exact text only: one space and the single digit 1 or 2. scanf %u
         * accepted "BGPOLICY1" and wrapped 4294967297 and -4294967295 to 1. */
        unsigned policy = !strcmp(line, "BGPOLICY 1") ? DETECTOR_BACKGROUND_POLICY_LEGACY :
                          !strcmp(line, "BGPOLICY 2") ? DETECTOR_BACKGROUND_POLICY_Q16 : 0;
        if (policy) {
            detector_background_policy = policy; reply("BGPOLICY %u\n", policy);
        } else reply("ERR background_policy\n");
        return true;
    }
    if (!strcmp(line, "PIPEKERNEL?")) { reply("PIPEKERNEL %u\n", detpipe_kernel); return true; }
    if (!strncmp(line, "PIPEKERNEL", 10)) {
        unsigned kernel; char extra;
        if (sscanf(line, "PIPEKERNEL %u %c", &kernel, &extra) == 1 && (kernel == 0 || kernel == 3)) {
            detpipe_kernel = kernel; reply("PIPEKERNEL %u\n", kernel);
        } else reply("ERR pipeline_kernel\n");
        return true;
    }
    if (!strcmp(line, "DETPIPECLEAR")) { detpipe_clear(); reply("OK\n"); return true; }
    if (!strcmp(line, "DETPIPEMEM?")) {
        reply("DETPIPEMEM %u %u\n", (unsigned)heap_caps_get_free_size(DETPIPE_ALLOC_CAPS),
              (unsigned)heap_caps_get_largest_free_block(DETPIPE_ALLOC_CAPS)); return true;
    }
    if (!strcmp(line, "DETPIPEGET")) {
        if (detpipe_run_keep == 3) { detpipe_send_candidate(detpipe_best_slot); return true; }
        if (!detpipe_retained_n) reply("ERR no_retained_event\n");
        else {
            uint32_t crc = detpipe_crc();
            char header[96];
            int length = snprintf(header, sizeof(header), "DATA %u %08" PRIx32 " %u\n",
                                  detpipe_retained_n, crc, detpipe_retained_us);
            if (length > 0 && (size_t)length < sizeof(header) && burst_serial_send(header, length)) {
                for (unsigned page = 0; page < detpipe_page_count; page++)
                    if (!burst_serial_send(detpipe_pages[page], detpipe_page_sizes[page])) break;
            }
        }
        return true;
    }
    if (!strcmp(line, "DETPIPEINFO?")) {
        reply("DETPIPEINFO 1 5000 16 64\n");
        return true;
    }
    if (strncmp(line, "DETPIPE1", 8)) return false;
    unsigned ms, n, rate, ratio, retain;
    char extra;
    if (sscanf(line, "DETPIPE1 %u %u %u %u %u %c", &ms, &n, &rate, &ratio, &retain, &extra) != 5 ||
        ms < 1 || ms > 5000 || n < 256 || n > MAX_SAMPLES ||
        (rate != 0 && rate != 1 && rate != 6) || ratio < 1000 || ratio > 1000000 || retain > 1) {
        reply("ERR pipeline_args\n"); return true;
    }
    if (dual_armed && (rate != 6 || n != MAX_SAMPLES)) {
        reply("ERR trace_requires_full_rx16\n"); return true;
    }
    detpipe_health_begin();
    detpipe_clear();
    det_retained_n = 0;
    if (det_retained) { heap_caps_free(det_retained); det_retained = NULL; }
    detpipe_run_keep = detpipe_keep;
    detpipe_keep = 1; /* One-shot option: legacy clients cannot inherit crops. */
    detpipe_state_t p = {.n=n, .kernel=detpipe_kernel,
                         .background=detector_background_start(detector_background_policy)};
    size_t bytes = n * sizeof(uint32_t);
    p.copy = heap_caps_malloc(bytes, DETPIPE_ALLOC_CAPS);
    size_t retained_bytes = ((detpipe_run_keep == 3 ? detector_crop_length(n) : n) * 20u + 7u) / 8u;
    detpipe_candidate_pages = (retained_bytes + DETPIPE_PAGE_BYTES - 1) / DETPIPE_PAGE_BYTES;
    if (!detpipe_safe_buffer(p.copy, bytes)) {
        detpipe_allocation_report("ERR pipeline_memory","raw",0,p.copy,bytes);
        if (p.copy) heap_caps_free(p.copy);
        detpipe_health_finish(false);
        return true;
    }
    for (unsigned slot = 0; slot < (retain ? detpipe_run_keep : 0); slot++) {
    for (size_t left = retained_bytes; left;) {
        unsigned page = detpipe_page_count;
        size_t amount = left > DETPIPE_PAGE_BYTES ? DETPIPE_PAGE_BYTES : left;
        uint8_t *allocation = heap_caps_malloc(amount, DETPIPE_ALLOC_CAPS);
        if (!detpipe_safe_buffer(allocation, amount)) {
            detpipe_allocation_report("ERR pipeline_memory","page",page,allocation,amount);
            if (allocation) heap_caps_free(allocation);
            heap_caps_free(p.copy); detpipe_clear();
            detpipe_health_finish(false);
            return true;
        }
        uintptr_t lo = (uintptr_t)allocation, hi = lo + amount - 1;
        uintptr_t raw = (uintptr_t)p.copy;
        bool disjoint = hi < raw || lo > raw + bytes - 1;
        for (unsigned prev = 0; prev < page; prev++) {
            uintptr_t prev_lo = (uintptr_t)detpipe_pages[prev];
            disjoint = disjoint && (hi < prev_lo || lo > prev_lo + detpipe_page_sizes[prev] - 1);
        }
        if (!disjoint || page >= DETPIPE_MAX_PAGES) {
            /* A corrupted allocator could alias live allocations. Avoid invalid
             * frees and require reset; ordinary allocation failures above clean all. */
            reply("ERR pipeline_alias\n"); detpipe_health_finish(false); return true;
        }
        detpipe_pages[page] = allocation; detpipe_page_sizes[page] = amount;
        detpipe_page_count++; left -= amount;
    }
    }
    if (!dual_trace_begin()) {
        heap_caps_free(p.copy); detpipe_clear(); detpipe_health_finish(false); return true;
    }
    detpipe_health_allocated();
    prepare_rx();
    uint32_t gain_register_start = REG_READ(RX_GAIN);
    uint64_t first_trigger_us = 0, last_trigger_us = 0;
    reply("DETPIPE1 BEGIN %u %u %u %u %u %u\n", ms, n, rate, ratio, retain, frequency_mhz);
    uint64_t acquisition_us = 0, observed_done_us = 0;
    unsigned captures = 0, status = 0;
    /* Schedule origin excludes the deliberate pre-run wait from run duration. */
    while (dual_active && (uint64_t)esp_timer_get_time() + 2000 < dual_armed_deadline) vTaskDelay(1);
    int64_t start = esp_timer_get_time();
    while (esp_timer_get_time() - start < (int64_t)ms * 1000) {
        unsigned observed = 0;
        int64_t t = esp_timer_get_time();
        bool fused = detpipe_copy_option == 1 && n == MAX_SAMPLES;
        detpipe_validation_t validation = {&p, ratio, retain};
        bool ok = fused ? acquire_iq_with_validation(n, 0, rate == 0 ? 1 : rate == 1 ? 2 : 0,
                                      &observed, detpipe_compute, &p, detpipe_validate_copy, &validation) :
                         acquire_iq_with_work(n, 0, rate == 0 ? 1 : rate == 1 ? 2 : 0,
                                      &observed, detpipe_compute, &p);
        acquisition_us += esp_timer_get_time() - t;
        /* Current SRAM is restored on all acquire exits. Commit PREVIOUS valid
         * copy even on failure; current data has not been published or counted. */
        detpipe_commit(&p, ratio, retain);
        if(p.pack_failed){status=2;break;}
        if (!ok) { status = 1; break; }
        captures++; observed_done_us += observed;
        dual_trace_record(capture_trigger_device_us);
        if (!first_trigger_us) first_trigger_us = capture_trigger_device_us;
        last_trigger_us = capture_trigger_device_us;
        t = esp_timer_get_time();
        if (!fused) {
            memcpy(p.copy, samples, bytes); /* acquisition validated entire aperture */
            p.copy_us += esp_timer_get_time() - t;
        }
        p.generation = captures; p.observed_us = observed;
        p.trigger_device_us = capture_trigger_device_us;
        p.pending = true; p.ready = false;
        if ((captures & 31) == (dual_active ? dual_yield_phase : 0)) vTaskDelay(1);
    }
    dual_trace_end();
    detpipe_commit(&p, ratio, retain); /* final successful capture, exactly once */
    uint64_t elapsed = esp_timer_get_time() - start;
    if(p.pack_failed)status=2;
    if (p.processed != captures) status = 2; /* internal accounting error fails closed */
    detpipe_health_drained();
    heap_caps_free(p.copy);
    char candidate_json[900] = "[]";
    if (detpipe_run_keep == 3) {
        size_t used = 1; candidate_json[0] = '[';
        unsigned emitted = 0;
        for (unsigned slot = 0; slot < 3; slot++) {
            detector_candidate_t *c = &detpipe_candidates[slot];
            if (!c->samples) continue;
            int written = snprintf(candidate_json + used, sizeof(candidate_json) - used,
                "%s{\"slot\":%u,\"samples\":%u,\"offset_samples\":%u,\"generation\":%u,"
                "\"trigger_device_us\":%" PRIu64 ",\"score_milli\":%u,\"capture_us\":%u}",
                emitted ? "," : "", slot, c->samples, c->offset_samples, c->generation,
                c->trigger_device_us, c->score_milli, c->capture_us);
            if (written < 0 || (size_t)written >= sizeof(candidate_json) - used) {
                reply("ERR pipeline_summary\n"); detpipe_health_finish(false); return true;
            }
            used += written; emitted++;
        }
        candidate_json[used++] = ']'; candidate_json[used] = 0;
    }
    char summary[3000];
    int length = snprintf(summary, sizeof(summary),
        "DETPIPE1 END {\"version\":1,\"kernel\":%u,\"status\":%u,\"captures\":%u,\"processed_captures\":%u,"
        "\"detections\":%u,\"background_policy\":%u,\"background_q16\":%" PRIu64 ",\"background_adc2\":%u,\"best_ratio_milli\":%u,"
        "\"wall_elapsed_us\":%" PRIu64 ",\"completion_observed_us\":%" PRIu64 ","
        "\"acquire_call_us_includes_overlap\":%" PRIu64 ",\"energy_compute_us\":%" PRIu64 ","
        "\"copy_us\":%" PRIu64 ",\"decision_us\":%" PRIu64 ",\"retention_copy_us\":%" PRIu64 ","
        "\"retained_samples\":%u,\"frequency_mhz\":%u,\"total_samples\":%" PRIu64 ","
        "\"analyzed_samples\":%" PRIu64 ",\"sample_rate_hz\":%u,\"errors\":%u,\"warmup_captures\":%u,\"acquisition_option\":%u,\"clear_option\":%u,\"copy_option\":%u,\"fused_active\":%u,\"pack_failed\":%u,\"gain_register_start\":%" PRIu32 ",\"gain_register_end\":%" PRIu32 ",\"hardware_agc\":%u,\"gain_index_requested\":%u,\"first_trigger_device_us\":%" PRIu64 ",\"last_trigger_device_us\":%" PRIu64 ",\"retained_trigger_device_us\":%" PRIu64 ",\"retained_generation\":%u,\"retention_capacity\":%u,\"retained_candidates\":%s}\n",
        p.kernel, status, captures, p.processed, p.events,
        detector_background_state_policy(&p.background), p.background.q16, (unsigned)(p.background.q16 / DETECTOR_BACKGROUND_SCALE), p.best_ratio, elapsed,
        observed_done_us, acquisition_us, p.compute_us, p.copy_us, p.commit_us - p.retention_us,
        p.retention_us, detpipe_retained_n, frequency_mhz, (uint64_t)captures*n,
        (uint64_t)p.processed*(n/64)*64,
        rate == 0 ? 80000000u : rate == 1 ? 40000000u : 16000000u,
        status ? 1u : 0u, p.processed < 16 ? p.processed : 16u,acquisition_option,clear_option,detpipe_copy_option,detpipe_copy_option == 1 && n == MAX_SAMPLES,p.pack_failed, gain_register_start, (uint32_t)REG_READ(RX_GAIN),
        (unsigned)hardware_agc, gain_code, first_trigger_us, last_trigger_us, detpipe_retained_trigger_us, detpipe_retained_generation, detpipe_run_keep, candidate_json);
    bool health_valid = false;
    if (length > 0 && (size_t)length < sizeof(summary)) {
        size_t framed=ascii_frame_pad(summary,length,sizeof(summary));
        if(framed)health_valid=burst_serial_send(summary,framed);else reply("ERR pipeline_frame\n");
    }
    else reply("ERR pipeline_summary\n");
    detpipe_health_finish(health_valid);
    (void)health_valid;
    return true;
}
