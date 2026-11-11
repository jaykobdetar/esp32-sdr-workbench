#pragma once
#include "profile_stats.h"
static bool profile_send_stage(const char *name, const profile_hist *h) {
    uint32_t q[6];
    profile_quantile(h,50,&q[0],&q[1]); profile_quantile(h,95,&q[2],&q[3]); profile_quantile(h,99,&q[4],&q[5]);
    char text[512];
    int len = snprintf(text,sizeof(text),
        "PROF1 STAGE {\"name\":\"%s\",\"count\":%u,\"nonzero_count\":%u,\"sum_us\":%" PRIu64 ","
        "\"min_us\":%u,\"median_us\":[%u,%u],\"p95_us\":[%u,%u],\"p99_us\":[%u,%u],\"max_us\":%u}\n",
        name,(unsigned)h->count,(unsigned)h->nonzero,h->sum,(unsigned)h->min,(unsigned)q[0],(unsigned)q[1],(unsigned)q[2],(unsigned)q[3],(unsigned)q[4],(unsigned)q[5],(unsigned)h->max);
    return len>0 && len<sizeof(text) && burst_serial_send(text,len);
}
static bool profile_command(const char *line) {
    if (!strcmp(line,"PROFINFO?")) { reply("PROFINFO 1 5000 465 20\n"); return true; }
    if (strncmp(line,"PROF1",5)) return false;
    unsigned ms,n,rate,ratio,retain; char extra;
    if (sscanf(line,"PROF1 %u %u %u %u %u %c",&ms,&n,&rate,&ratio,&retain,&extra)!=5 ||
        ms<1 || ms>5000 || n<256 || n>MAX_SAMPLES || (rate!=0 && rate!=1 && rate!=6) ||
        ratio<1000 || ratio>1000000 || retain>1) { reply("ERR profile_args\n"); return true; }
    int64_t setup_start=esp_timer_get_time();
    profile_hist *hist=heap_caps_malloc(sizeof(profile_hist)*P_STAGE_COUNT,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    if (!hist) { reply("ERR profile_memory\n"); return true; }
    memset(hist,0,sizeof(profile_hist)*P_STAGE_COUNT);
    det_retained_n=0;
    if (det_retained) { heap_caps_free(det_retained);det_retained=NULL; }
    if (retain) {
        det_retained=heap_caps_malloc(n*sizeof(uint32_t),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
        if (!det_retained) { heap_caps_free(hist);reply("ERR profile_retention_memory\n");return true; }
    }
    uint64_t allocation_us=esp_timer_get_time()-setup_start;
    reply("PROF1 BEGIN %u %u %u %u %u %u\n",ms,n,rate,ratio,retain,frequency_mhz);
    int64_t timer_start=esp_timer_get_time();
    for(unsigned j=0;j<1000;j++) {
        int64_t a=esp_timer_get_time(),b=esp_timer_get_time();
        profile_add(&hist[P_TIMER_PAIR],b-a);
    }
    uint64_t timer_us=esp_timer_get_time()-timer_start;
    uint32_t init[P_STAGE_COUNT]={0};profile_prepare(init);
    char text[1024];
    int len=snprintf(text,sizeof(text),
        "PROF1 INIT {\"allocation_us\":%" PRIu64 ",\"timer_benchmark_us\":%" PRIu64 ","
        "\"prepare_total_us\":%u,\"calibration_check_us\":%u,\"tune_calibration_us\":%u,\"gain_apply_us\":%u,\"rx_prepare_us\":%u}\n",
        allocation_us,timer_us,(unsigned)init[P_PREPARE],(unsigned)init[P_CAL_CHECK],(unsigned)init[P_TUNE_CAL],(unsigned)init[P_GAIN],(unsigned)init[P_RX_PREP]);
    if(len>0 && len<sizeof(text))burst_serial_send(text,len);
    uint64_t setup_us=esp_timer_get_time()-setup_start;
    unsigned captures=0,events=0,background=1,best_ratio=0,status=0;
    uint64_t warm_total=0;
    int64_t start=esp_timer_get_time();
    while(esp_timer_get_time()-start<(int64_t)ms*1000) {
        int64_t iteration_start=esp_timer_get_time();
        uint32_t row[P_STAGE_COUNT]={0};unsigned captured_us;
        if(!profile_acquire(n,0,rate==0?1:rate==1?2:0,&captured_us,row)){status=1;break;}
        uint32_t mean,peak;int64_t a=esp_timer_get_time();
        detector_energy(samples,n,&mean,&peak);
        row[P_ENERGY]=esp_timer_get_time()-a;
        a=esp_timer_get_time();captures++;bool store=false;
        if(captures<=16){warm_total+=mean;background=warm_total/captures;if(!background)background=1;}
        else if((uint64_t)peak*1000>(uint64_t)background*ratio){
            events++;unsigned score=(uint64_t)peak*1000/background;
            if(score>best_ratio){best_ratio=score;store=retain;}
        }else{background=((uint64_t)background*63+mean+32)/64;if(!background)background=1;}
        row[P_DECISION]=esp_timer_get_time()-a;
        if(store){
            a=esp_timer_get_time();memcpy(det_retained,samples,n*sizeof(uint32_t));
            det_retained_n=n;det_retained_capture_us=captured_us;
            row[P_RETAIN]=esp_timer_get_time()-a;
        }
        if((captures&31)==0){a=esp_timer_get_time();vTaskDelay(1);row[P_SCHEDULE]=esp_timer_get_time()-a;}
        a=esp_timer_get_time();
        for(unsigned j=0;j<=P_SCHEDULE;j++)profile_add(&hist[j],row[j]);
        row[P_HISTOGRAM]=esp_timer_get_time()-a;
        profile_add(&hist[P_HISTOGRAM],row[P_HISTOGRAM]);
        row[P_ITERATION]=esp_timer_get_time()-iteration_start;
        profile_add(&hist[P_ITERATION],row[P_ITERATION]);
    }
    uint64_t elapsed=esp_timer_get_time()-start;
    for(unsigned j=0;j<P_STAGE_COUNT;j++)if(!profile_send_stage(profile_names[j],&hist[j])){status=2;break;}
    len=snprintf(text,sizeof(text),
        "PROF1 END {\"version\":1,\"status\":%u,\"captures\":%u,\"detections\":%u,\"errors\":%u,"
        "\"background_adc2\":%u,\"best_ratio_milli\":%u,\"wall_elapsed_us\":%" PRIu64 ","
        "\"setup_elapsed_us\":%" PRIu64 ",\"histogram_bytes\":%u,\"retained_samples\":%u,"
        "\"frequency_mhz\":%u,\"total_samples\":%" PRIu64 ",\"analyzed_samples\":%" PRIu64 ","
        "\"sample_rate_hz\":%u,\"warmup_captures\":%u,\"histogram_version\":1}\n",
        status,captures,events,status?1u:0u,background,best_ratio,elapsed,setup_us,
        (unsigned)(sizeof(profile_hist)*P_STAGE_COUNT),det_retained_n,frequency_mhz,
        (uint64_t)captures*n,(uint64_t)captures*(n/64)*64,
        rate==0?80000000u:rate==1?40000000u:16000000u,captures<16?captures:16u);
    if(len>0 && len<sizeof(text))burst_serial_send(text,len);else reply("ERR profile_summary\n");
    heap_caps_free(hist);return true;
}
