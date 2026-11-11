#pragma once
#include <stdlib.h>
#include "esp_cpu.h"
#include "esp_private/esp_clk.h"
#include "validate_copy_runtime.h"
#define VCTEST_MAX_REPEATS 255u
#define VCTEST_CANARY UINT32_C(0xfeed1234)
typedef struct { uint32_t count,min,median,p95,p99,max,mismatches; uint64_t sum; } vctest_result;
typedef struct { uint32_t cycles[VCTEST_MAX_REPEATS];vctest_result result[VC_CANDIDATE_COUNT],timer; } vctest_workspace;
static uint32_t *vctest_saved;
static unsigned vctest_saved_n,vctest_saved_us;
static int vctest_compare(const void*a,const void*b){uint32_t x=*(const uint32_t*)a,y=*(const uint32_t*)b;return(x>y)-(x<y);}
static void vctest_summarize(uint32_t*c,unsigned count,vctest_result*r){
    r->count=count;if(!count)return;qsort(c,count,sizeof(uint32_t),vctest_compare);
    r->min=c[0];r->median=c[(count*50+99)/100-1];r->p95=c[(count*95+99)/100-1];r->p99=c[(count*99+99)/100-1];r->max=c[count-1];
    for(unsigned j=0;j<count;j++)r->sum+=c[j];
}
static bool vctest_canary(unsigned n){for(unsigned j=n;j<n+4;j++)if(vctest_saved[j]!=VCTEST_CANARY)return false;return true;}
static bool vctest_verify(vc_candidate_fn fn,unsigned n){
    memset(vctest_saved,0x5a,n*sizeof(uint32_t));for(unsigned j=n;j<n+4;j++)vctest_saved[j]=VCTEST_CANARY;
    if(fn(samples,vctest_saved,n)!=UINT_MAX||memcmp(samples,vctest_saved,n*sizeof(uint32_t))||!vctest_canary(n))return false;
    /* Aperture is CPU-owned and stopped here; every temporary fault is restored. */
    const unsigned faults[]={0,n-1,n,CAPACITY-1};
    for(unsigned k=0;k<4;k++){
        unsigned at=faults[k];uint32_t saved=samples[at];samples[at]=at<n?SENTINEL:~SENTINEL;
        unsigned bad=fn(samples,vctest_saved,n);samples[at]=saved;
        if(bad!=at||!vctest_canary(n))return false;
    }
    return true;
}
static bool vctest_send(const char*prefix,unsigned variant,const char*name,const vctest_result*r){
    char text[512];int len=snprintf(text,sizeof(text),
        "%s {\"variant\":%u,\"name\":\"%s\",\"count\":%u,\"sum_cycles\":%" PRIu64 ",\"min_cycles\":%u,"
        "\"median_cycles\":%u,\"p95_cycles\":%u,\"p99_cycles\":%u,\"max_cycles\":%u,\"mismatch_count\":%u}\n",
        prefix,variant,name,(unsigned)r->count,r->sum,(unsigned)r->min,(unsigned)r->median,(unsigned)r->p95,
        (unsigned)r->p99,(unsigned)r->max,(unsigned)r->mismatches);
    return len>0&&(size_t)len<sizeof(text)&&burst_serial_send(text,len);
}
static bool validate_copy_test_command(const char*line){
    if(!strcmp(line,"VCTESTINFO?")){reply("VCTESTINFO 1 %u 255 5000\n",VC_CANDIDATE_COUNT);return true;}
    if(!strcmp(line,"VCTESTCLEAR")){
        vctest_saved_n=vctest_saved_us=0;if(vctest_saved){heap_caps_free(vctest_saved);vctest_saved=NULL;}reply("OK\n");return true;
    }
    if(!strcmp(line,"VCTESTGET")){
        if(!vctest_saved_n)reply("ERR no_validate_copy_capture\n");
        else{memcpy(samples,vctest_saved,vctest_saved_n*sizeof(uint32_t));burst_send_capture(vctest_saved_n,20,vctest_saved_us);}return true;
    }
    if(strncmp(line,"VCTEST",6))return false;
    unsigned n,rate,repeats;char extra;
    if(sscanf(line,"VCTEST %u %u %u %c",&n,&rate,&repeats,&extra)!=3||n<256||n>MAX_SAMPLES||
       (rate!=0&&rate!=1&&rate!=6)||repeats<3||repeats>VCTEST_MAX_REPEATS){reply("ERR validate_copy_args\n");return true;}
    vctest_saved_n=0;if(vctest_saved){heap_caps_free(vctest_saved);vctest_saved=NULL;}
    detpipe_clear();det_retained_n=0;if(det_retained){heap_caps_free(det_retained);det_retained=NULL;}
    size_t bytes=(n+4)*sizeof(uint32_t);vctest_saved=heap_caps_malloc(bytes,DETPIPE_ALLOC_CAPS);
    if(!detpipe_safe_buffer(vctest_saved,bytes)){
        if(vctest_saved){heap_caps_free(vctest_saved);vctest_saved=NULL;}reply("ERR validate_copy_memory\n");return true;
    }
    vctest_workspace*w=heap_caps_malloc(sizeof(*w),DETPIPE_ALLOC_CAPS);
    if(!w){heap_caps_free(vctest_saved);vctest_saved=NULL;reply("ERR validate_copy_workspace\n");return true;}
    memset(w,0,sizeof(*w));prepare_rx();unsigned capture_us;
    if(!acquire_iq(n,0,rate==0?1:rate==1?2:0,&capture_us)){
        heap_caps_free(w);heap_caps_free(vctest_saved);vctest_saved=NULL;return true;
    }
    uint32_t crc=esp_rom_crc32_le(0,(const uint8_t*)samples,n*sizeof(uint32_t));
    unsigned cpu_before=esp_clk_cpu_freq(),core_before=esp_cpu_get_core_id();
    reply("VCTEST BEGIN %u %u %u %u\n",n,rate,repeats,frequency_mhz);
    int64_t start=esp_timer_get_time();unsigned mismatch=0,status=0;
    for(unsigned v=0;v<VC_CANDIDATE_COUNT;v++)if(!vctest_verify(vc_candidate_select(v),n)){mismatch|=1u<<v;w->result[v].mismatches++;}
    for(unsigned j=0;j<VCTEST_MAX_REPEATS;j++){uint32_t a=esp_cpu_get_cycle_count(),b=esp_cpu_get_cycle_count();w->cycles[j]=b-a;}
    vctest_summarize(w->cycles,VCTEST_MAX_REPEATS,&w->timer);if(mismatch)status=2;
    for(unsigned v=0;v<VC_CANDIDATE_COUNT;v++){
        vctest_result*r=&w->result[v];if(mismatch&(1u<<v))continue;
        vc_candidate_fn fn=vc_candidate_select(v);for(unsigned j=0;j<3;j++)fn(samples,vctest_saved,n);
        unsigned count=0;
        while(count<repeats){
            if(esp_timer_get_time()-start>=5000000){if(!status)status=1;break;}
            uint32_t a=esp_cpu_get_cycle_count();unsigned bad=fn(samples,vctest_saved,n);uint32_t b=esp_cpu_get_cycle_count();
            w->cycles[count++]=b-a;
            if(bad!=UINT_MAX||memcmp(samples,vctest_saved,n*sizeof(uint32_t))||!vctest_canary(n)){mismatch|=1u<<v;r->mismatches++;status=2;}
            if((count&15)==0)vTaskDelay(1);
        }
        vctest_summarize(w->cycles,count,r);
    }
    uint64_t elapsed=esp_timer_get_time()-start;unsigned cpu_after=esp_clk_cpu_freq(),core_after=esp_cpu_get_core_id();
    /* Preserve the actual original capture even if the last candidate failed. */
    memcpy(vctest_saved,samples,n*sizeof(uint32_t));vctest_saved_n=n;vctest_saved_us=capture_us;
    vctest_send("VCTEST TIMER",0,"cycle-read-pair",&w->timer);
    for(unsigned v=0;v<VC_CANDIDATE_COUNT;v++)if(!vctest_send("VCTEST RESULT",v,vc_candidate_names[v],&w->result[v]))status=3;
    char text[640];int len=snprintf(text,sizeof(text),
        "VCTEST END {\"version\":1,\"status\":%u,\"mismatch_mask\":%u,\"wall_elapsed_us\":%" PRIu64 ","
        "\"cpu_hz_before\":%u,\"cpu_hz_after\":%u,\"core_before\":%u,\"core_after\":%u,\"samples\":%u,"
        "\"rate_code\":%u,\"repeats_requested\":%u,\"warmup_calls\":3,\"cycle_bits\":32,\"raw_crc32\":\"%08" PRIx32 "\",\"capture_us\":%u}\n",
        status,mismatch,elapsed,cpu_before,cpu_after,core_before,core_after,n,rate,repeats,crc,capture_us);
    if(len>0&&(size_t)len<sizeof(text))burst_serial_send(text,len);else reply("ERR validate_copy_summary\n");
    heap_caps_free(w);return true;
}
