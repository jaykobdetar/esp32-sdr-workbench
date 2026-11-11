#pragma once
#include "pipeline_compact_stats.h"
#include "ascii_frame.h"
#include "esp_memory_utils.h"
/* Same instrumented implementation with runtime OFF/ON. All observations,
 * exact extrema/sums; quantiles are histogram interval bounds, never midpoints. */
enum {SP_PREPARE,SP_CALCHECK,SP_TUNE,SP_GAIN,SP_RXPREP,SP_CLEAR,SP_FILTER,
 SP_SETUP,SP_TRIGGER,SP_POLL,SP_FINALIZE,SP_RESTORE,SP_FILTER_RESTORE,SP_VALIDATE,
 SP_ACQUIRE,SP_ENERGY,SP_DECISION,SP_RETAIN,SP_COPY,SP_YIELD,SP_ITERATION,SP_TIMER,SP_HIST,SP_COUNT};
static const char *const sp_names[SP_COUNT]={"prepare","calibration_check","tune_calibration","gain","rx_prepare","clear","filter_apply","register_setup","trigger_to_done","poll_after_overlap","hardware_finalize","register_restore","filter_restore","validate_or_fused_copy","acquire_total","energy","decision_including_retention","retention","separate_copy","yield","iteration","timer_pair","histogram_update"};
static compact_hist *sp_hist[SP_COUNT];
static bool sp_enabled,sp_active,sp_overflow;
static unsigned sp_yield_cadence=32;
static uint64_t sp_hist_us;
static void sp_free(void){sp_active=false;for(unsigned j=0;j<SP_COUNT;j++){if(sp_hist[j])heap_caps_free(sp_hist[j]);sp_hist[j]=NULL;}}
static bool sp_allocate(void){
 sp_free();sp_hist_us=0;sp_overflow=false;
 for(unsigned j=0;j<SP_COUNT;j++){
  sp_hist[j]=heap_caps_malloc(sizeof(compact_hist),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT|MALLOC_CAP_DMA);
  uintptr_t lo=(uintptr_t)sp_hist[j],hi=lo+sizeof(compact_hist)-1;
  if(!sp_hist[j]||hi<lo||!esp_ptr_internal(sp_hist[j])||!esp_ptr_in_dram(sp_hist[j])||!esp_ptr_in_dram((void*)hi)||!esp_ptr_byte_accessible(sp_hist[j])||!(hi<0x3ffe8000u||lo>=0x3fff8000u)){sp_free();return false;}
  memset(sp_hist[j],0,sizeof(compact_hist));
 }
 return true;
}
static __attribute__((noinline)) int64_t sp_start(void){return sp_active?esp_timer_get_time():0;}
static __attribute__((noinline)) void sp_end(unsigned stage,int64_t start){
 if(!sp_active)return;
 int64_t end=esp_timer_get_time();
 int64_t t=esp_timer_get_time();if(!compact_add(sp_hist[stage],end-start)){sp_overflow=true;sp_active=false;return;}
 uint32_t overhead=esp_timer_get_time()-t;
 sp_hist_us+=overhead;if(!compact_add(sp_hist[SP_HIST],overhead)){sp_overflow=true;sp_active=false;}
}
static void sp_report(void){
 sp_active=false;
 for(unsigned j=0;j<SP_COUNT;j++){
  compact_hist*h=sp_hist[j];uint32_t lo[3],hi[3];unsigned q[]={50,95,99};
  for(unsigned k=0;k<3;k++)compact_quantile(h,q[k],lo+k,hi+k);
  char line[512];int n=snprintf(line,sizeof(line),"PPROF1 STAGE {\"id\":%u,\"name\":\"%s\",\"count\":%u,\"sum_us\":%"PRIu64",\"min_us\":%u,\"p50_lo\":%u,\"p50_hi\":%u,\"p95_lo\":%u,\"p95_hi\":%u,\"p99_lo\":%u,\"p99_hi\":%u,\"max_us\":%u}\n",j,sp_names[j],(unsigned)h->count,h->sum,(unsigned)h->min,(unsigned)lo[0],(unsigned)hi[0],(unsigned)lo[1],(unsigned)hi[1],(unsigned)lo[2],(unsigned)hi[2],(unsigned)h->max);
  if(n>0&&(size_t)n<sizeof(line)){
   size_t framed=ascii_frame_pad(line,n,sizeof(line));if(framed)burst_serial_send(line,framed);
   /* Force a short-packet boundary between telemetry lines. Outside timing. */
   vTaskDelay(pdMS_TO_TICKS(20)+1);
  }
 }
 sp_free();
}
static bool pipeline_profile_command(const char*line){
 unsigned value;char extra;
 if(!strcmp(line,"PIPEPROFILE?")){reply("PIPEPROFILE %u\n",sp_enabled);return true;}
 if(!strncmp(line,"PIPEPROFILE",11)){
  if(sscanf(line,"PIPEPROFILE %u %c",&value,&extra)==1&&value<=1){sp_enabled=value;reply("PIPEPROFILE %u\n",value);}else reply("ERR pipeline_profile\n");return true;
 }
 if(!strcmp(line,"PIPEYIELD?")){reply("PIPEYIELD %u 100000\n",sp_yield_cadence);return true;}
 if(!strncmp(line,"PIPEYIELD",9)){
  if(sscanf(line,"PIPEYIELD %u %c",&value,&extra)==1&&(value==32||value==64||value==128)){sp_yield_cadence=value;reply("PIPEYIELD %u 100000\n",value);}else reply("ERR pipeline_yield\n");return true;
 }
 return false;
}
