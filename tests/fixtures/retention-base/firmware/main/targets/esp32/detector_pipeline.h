#pragma once
/* Proposal only: finite single-core overlap. Include after detector_experiment.h.
 * No live reads of RF-owned SRAM. DETPIPEGET retrieves the strongest packed copy.
 * Requires acquire_iq_with_work() from accompanying receiver patch. */
#include "esp_memory_utils.h"

#include "pipeline_energy3.h"
#include "pack20_candidates.h"
#include "ascii_frame.h"
#include "validate_copy_runtime.h"
#define DETPIPE_ALLOC_CAPS (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT | MALLOC_CAP_DMA)
#define DETPIPE_PAGE_BYTES 4096u
#define DETPIPE_MAX_PACKED ((MAX_SAMPLES * 20u + 7u) / 8u)
#define DETPIPE_MAX_PAGES ((DETPIPE_MAX_PACKED + DETPIPE_PAGE_BYTES - 1) / DETPIPE_PAGE_BYTES)
static uint8_t *detpipe_pages[DETPIPE_MAX_PAGES];
static size_t detpipe_page_sizes[DETPIPE_MAX_PAGES];
static unsigned detpipe_page_count;
static unsigned detpipe_copy_option; /* 0 separate; 1 fused only at full length */
static unsigned detpipe_kernel; /* default 0: unchanged v2 kernel */
static unsigned detpipe_retained_n, detpipe_retained_us, detpipe_retained_generation;
static void detpipe_clear(void) {
    for (unsigned page = 0; page < detpipe_page_count; page++) {
        heap_caps_free(detpipe_pages[page]);
        detpipe_pages[page] = NULL; detpipe_page_sizes[page] = 0;
    }
    detpipe_page_count = 0; detpipe_retained_n = 0;
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

typedef struct {
    uint32_t *copy;
    unsigned n, observed_us, generation, processed, kernel;
    uint32_t mean, peak;
    bool pending, ready, pack_failed;
    uint64_t compute_us, copy_us, commit_us, retention_us;
    unsigned background, best_ratio, events;
    uint64_t warm_total;
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
    if (p->processed <= 16) {
        p->warm_total += p->mean;
        p->background = p->warm_total / p->processed;
        if (!p->background) p->background = 1;
    } else if ((uint64_t)p->peak * 1000 > (uint64_t)p->background * ratio) {
        p->events++;
        unsigned score = (uint64_t)p->peak * 1000 / p->background;
        if (score > p->best_ratio) {
            p->best_ratio = score;
            if (retain) {
                int64_t r = esp_timer_get_time();
                bool packed=detpipe_pack(p->copy,p->n);
                if(!packed)p->pack_failed=true;
                if(packed){
                detpipe_retained_n = p->n;
                detpipe_retained_us = p->observed_us;
                detpipe_retained_generation = p->generation;
                }
                p->retention_us += esp_timer_get_time() - r;
            }
        }
    } else {
        p->background = ((uint64_t)p->background * 63 + p->mean + 32) / 64;
        if (!p->background) p->background = 1;
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
    detpipe_clear();
    det_retained_n = 0;
    if (det_retained) { heap_caps_free(det_retained); det_retained = NULL; }
    detpipe_state_t p = {.n=n, .background=1, .kernel=detpipe_kernel};
    size_t bytes = n * sizeof(uint32_t);
    p.copy = heap_caps_malloc(bytes, DETPIPE_ALLOC_CAPS);
    size_t retained_bytes = (n * 20u + 7u) / 8u;
    if (!detpipe_safe_buffer(p.copy, bytes)) {
        detpipe_allocation_report("ERR pipeline_memory","raw",0,p.copy,bytes);
        if (p.copy) heap_caps_free(p.copy);
        return true;
    }
    for (size_t left = retain ? retained_bytes : 0; left;) {
        unsigned page = detpipe_page_count;
        size_t amount = left > DETPIPE_PAGE_BYTES ? DETPIPE_PAGE_BYTES : left;
        uint8_t *allocation = heap_caps_malloc(amount, DETPIPE_ALLOC_CAPS);
        if (!detpipe_safe_buffer(allocation, amount)) {
            detpipe_allocation_report("ERR pipeline_memory","page",page,allocation,amount);
            if (allocation) heap_caps_free(allocation);
            heap_caps_free(p.copy); detpipe_clear();
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
            reply("ERR pipeline_alias\n"); return true;
        }
        detpipe_pages[page] = allocation; detpipe_page_sizes[page] = amount;
        detpipe_page_count++; left -= amount;
    }
    prepare_rx();
    reply("DETPIPE1 BEGIN %u %u %u %u %u %u\n", ms, n, rate, ratio, retain, frequency_mhz);
    uint64_t acquisition_us = 0, observed_done_us = 0;
    unsigned captures = 0, status = 0;
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
        t = esp_timer_get_time();
        if (!fused) {
            memcpy(p.copy, samples, bytes); /* acquisition validated entire aperture */
            p.copy_us += esp_timer_get_time() - t;
        }
        p.generation = captures; p.observed_us = observed;
        p.pending = true; p.ready = false;
        if ((captures & 31) == 0) vTaskDelay(1);
    }
    detpipe_commit(&p, ratio, retain); /* final successful capture, exactly once */
    uint64_t elapsed = esp_timer_get_time() - start;
    if(p.pack_failed)status=2;
    if (p.processed != captures) status = 2; /* internal accounting error fails closed */
    heap_caps_free(p.copy);
    char summary[1400];
    int length = snprintf(summary, sizeof(summary),
        "DETPIPE1 END {\"version\":1,\"kernel\":%u,\"status\":%u,\"captures\":%u,\"processed_captures\":%u,"
        "\"detections\":%u,\"background_adc2\":%u,\"best_ratio_milli\":%u,"
        "\"wall_elapsed_us\":%" PRIu64 ",\"completion_observed_us\":%" PRIu64 ","
        "\"acquire_call_us_includes_overlap\":%" PRIu64 ",\"energy_compute_us\":%" PRIu64 ","
        "\"copy_us\":%" PRIu64 ",\"decision_us\":%" PRIu64 ",\"retention_copy_us\":%" PRIu64 ","
        "\"retained_samples\":%u,\"frequency_mhz\":%u,\"total_samples\":%" PRIu64 ","
        "\"analyzed_samples\":%" PRIu64 ",\"sample_rate_hz\":%u,\"errors\":%u,\"warmup_captures\":%u,\"acquisition_option\":%u,\"clear_option\":%u,\"copy_option\":%u,\"fused_active\":%u,\"pack_failed\":%u}\n",
        p.kernel, status, captures, p.processed, p.events, p.background, p.best_ratio, elapsed,
        observed_done_us, acquisition_us, p.compute_us, p.copy_us, p.commit_us - p.retention_us,
        p.retention_us, detpipe_retained_n, frequency_mhz, (uint64_t)captures*n,
        (uint64_t)p.processed*(n/64)*64,
        rate == 0 ? 80000000u : rate == 1 ? 40000000u : 16000000u,
        status ? 1u : 0u, p.processed < 16 ? p.processed : 16u,acquisition_option,clear_option,detpipe_copy_option,detpipe_copy_option == 1 && n == MAX_SAMPLES,p.pack_failed);
    if (length > 0 && (size_t)length < sizeof(summary)) {
        size_t framed=ascii_frame_pad(summary,length,sizeof(summary));
        if(framed)burst_serial_send(summary,framed);else reply("ERR pipeline_frame\n");
    }
    else reply("ERR pipeline_summary\n");
    return true;
}
