#pragma once
/* Opt-in research only. Include after all legacy retention declarations. */
#include "packet_decimated_dfa.h"
#include "paused_calibration.h"
#include "esp_random.h"
#define PX_CAPS (MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT|MALLOC_CAP_DMA)
#define PX_WORDS 16380u
#define PX_BYTES (PX_WORDS*4u)
/* All metadata slots uint64 LE. Unused slots zero. */
enum { PX_VERSION, PX_KIND, PX_BOOT, PX_GEN, PX_REQUESTED, PX_ACTUAL,
 PX_CAP, PX_INPUT_CRC, PX_RESULT_CRC, PX_FREQ, PX_FILTER, PX_AGC, PX_GAIN,
 PX_DC_BEFORE, PX_DC_AFTER, PX_BEGIN, PX_ALLOC_END, PX_PREP_END, PX_CLEAR_END,
 PX_FILTER_END, PX_LOCKED, PX_TRIGGER, PX_DONE, PX_RESTORED, PX_UNLOCKED,
 PX_FILTER_RESTORED, PX_VALIDATE_END, PX_COPY_END, PX_DECODE_BEGIN, PX_DECODE_END,
 PX_INPUT_VERIFIED, PX_FREE_BEGIN, PX_LARGEST_BEGIN, PX_FREE_ALLOC,
 PX_LARGEST_ALLOC, PX_FREE_AFTER, PX_LARGEST_AFTER, PX_STACK_BEGIN,
 PX_STACK_AFTER, PX_GAIN_BEFORE, PX_GAIN_AFTER, PX_STATUS_REG, PX_CTRL_REG,
 PX_CAL_FRESH, PX_FREE_INPUT, PX_LARGEST_INPUT, PX_USED };
_Static_assert(PX_USED<=64,"metadata capacity");
_Static_assert(sizeof(pkt_result)==1844 && sizeof(pkt_workspace)==612,"DFA ABI");
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "PEX native wire requires little endian"
#endif
_Static_assert(sizeof(pkt_record)==28 && offsetof(pkt_result,records)==52,"record ABI");
_Static_assert(offsetof(pkt_result,status)==0,"counter ABI");
_Static_assert(offsetof(pkt_result,count)==4,"counter ABI");
_Static_assert(offsetof(pkt_result,sync_hits)==8,"counter ABI");
_Static_assert(offsetof(pkt_result,valid_hypotheses)==12,"counter ABI");
_Static_assert(offsetof(pkt_result,duplicates)==16,"counter ABI");
_Static_assert(offsetof(pkt_result,output_drops)==20,"counter ABI");
_Static_assert(offsetof(pkt_result,payload_rejects)==24,"counter ABI");
_Static_assert(offsetof(pkt_result,crc_rejects)==28,"counter ABI");
_Static_assert(offsetof(pkt_result,incomplete)==32,"counter ABI");
_Static_assert(offsetof(pkt_result,busy_syncs)==36,"counter ABI");
_Static_assert(offsetof(pkt_result,samples_processed)==40,"counter ABI");
_Static_assert(offsetof(pkt_result,differential_products)==44,"counter ABI");
_Static_assert(offsetof(pkt_result,symbol_decisions)==48,"counter ABI");
_Static_assert(offsetof(pkt_record,sequence)==0,"field ABI");
_Static_assert(offsetof(pkt_record,address_start_sample)==4,"field ABI");
_Static_assert(offsetof(pkt_record,payload)==8,"field ABI");
_Static_assert(offsetof(pkt_record,air_crc)==24,"field ABI");
_Static_assert(offsetof(pkt_record,phase)==26,"field ABI");
_Static_assert(offsetof(pkt_record,polarity)==27,"field ABI");
static bool px_compact_size(const pkt_result *r,unsigned cap,size_t *bytes) {
 if(r->status || cap>64 || r->count>cap)return false;
 size_t n=52u+28u*r->count;
 const uint8_t *raw=(const uint8_t *)r;
 for(size_t j=n;j<sizeof(*r);j++)if(raw[j])return false;
 *bytes=n;return true;
}
typedef struct {
 uint64_t m[64]; paused_calibration cal; pkt_workspace work; pkt_result result;
 uint32_t *input; uint64_t expires;
} px_context;
static px_context *px_keep;
static uint64_t px_generation, px_boot, px_attempt;
static uint32_t px_admission_heap[6];
static unsigned px_operation_version=1;
static uint64_t px_now(void) { return (uint64_t)esp_timer_get_time(); }
static void px_free(void) {
 if(px_keep) { if(px_keep->input)heap_caps_free(px_keep->input);heap_caps_free(px_keep); }
 px_keep=NULL;
}
static bool px_expire(void) {
 if(px_keep && px_now()>=px_keep->expires) {px_free();return true;} return false;
}
static void px_error(const char *error) {
 uint64_t gen=px_keep?px_keep->m[PX_GEN]:px_attempt, t[6]={0};
 if(px_keep) {
     const unsigned fields[6]={PX_TRIGGER,PX_DONE,PX_RESTORED,PX_COPY_END,PX_DECODE_END,PX_ACTUAL};
     for(unsigned j=0;j<6;j++)t[j]=px_keep->m[fields[j]];
 }
 px_free();
 char text[256];
 int n=snprintf(text,sizeof(text),"PEXERR %u %" PRIu64 " %" PRIu64 " %s %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64,
     px_operation_version,px_boot,gen,error,t[0],t[1],t[2],t[3],t[4],t[5],px_now());
 if(n<=0 || n>(int)sizeof(text)-11)return;
 uint32_t crc=esp_rom_crc32_le(0,(const uint8_t *)text,(size_t)n);
 int tail=snprintf(text+n,sizeof(text)-(size_t)n," %08" PRIx32 "\n",crc);
 if(tail!=10 || !burst_serial_finish(text,(size_t)n+(size_t)tail))return;
 n=snprintf(text,sizeof(text),"PEXMEM %u %" PRIu64 " %" PRIu64 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32,
     px_operation_version,px_boot,gen,px_admission_heap[0],px_admission_heap[1],px_admission_heap[2],px_admission_heap[3],px_admission_heap[4],px_admission_heap[5]);
 if(n<=0 || n>(int)sizeof(text)-11)return;
 crc=esp_rom_crc32_le(0,(const uint8_t *)text,(size_t)n);
 tail=snprintf(text+n,sizeof(text)-(size_t)n," %08" PRIx32 "\n",crc);
 if(tail==10)(void)burst_serial_finish(text,(size_t)n+(size_t)tail);
}
static void px_heap(px_context *p,unsigned free_slot,unsigned large_slot) {
 p->m[free_slot]=heap_caps_get_free_size(PX_CAPS);
 p->m[large_slot]=heap_caps_get_largest_free_block(PX_CAPS);
}
/* No new telemetry/FreeRTOS calls while mapped. Same v9 register ordering. */
static bool px_capture(px_context *p) {
 p->m[PX_PREP_END]=px_now();
 REG_WRITE(DUMP_CTRL,0);
 for(unsigned j=0;j<CAPACITY;j++)samples[j]=SENTINEL;
 p->m[PX_CLEAR_END]=px_now();
 filter_apply();p->m[PX_FILTER_END]=px_now();
 if(burst_serial_stop_requested() || !paused_calibration_begin(&p->cal)) {
     filter_restore();p->m[PX_FILTER_RESTORED]=px_now();return false;
 }
 p->m[PX_LOCKED]=px_now();
 uint32_t adc=DPORT_REG_READ(ADC_CTRL)&ADC_ON_FORCE;
 DPORT_REG_WRITE(ADC_CTRL,DPORT_REG_READ(ADC_CTRL)|ADC_ON_FORCE);
 esp_rom_delay_us(2);
 uint32_t owner=DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
 uint32_t bytes=REG_READ(DUMP_BYTES);
 DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,
       (owner&~DPORT_MAC_DUMP_MODE_M)|(3<<DPORT_MAC_DUMP_MODE_S));
 REG_WRITE(DUMP_BYTES,0x03020100);
 REG_WRITE(DUMP_CTRL,PX_WORDS|BIT(16)|BIT(31));
 p->m[PX_TRIGGER]=px_now();capture_trigger_device_us=p->m[PX_TRIGGER];
 REG_SET_BIT(DUMP_CTRL,BIT(19));REG_CLR_BIT(DUMP_CTRL,BIT(19));
 while(!(REG_READ(DUMP_CTRL)&BIT(18)) && px_now()-p->m[PX_TRIGGER]<20000) {}
 uint32_t ctrl=REG_READ(DUMP_CTRL),status=REG_READ(DUMP_STATUS);
 p->m[PX_DONE]=px_now();
 REG_WRITE(DUMP_CTRL,0);esp_rom_delay_us(10);
 DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,owner);
 REG_WRITE(DUMP_BYTES,bytes);
 DPORT_REG_WRITE(ADC_CTRL,(DPORT_REG_READ(ADC_CTRL)&~ADC_ON_FORCE)|adc);
 p->m[PX_RESTORED]=px_now();
 bool unchanged=paused_calibration_end(&p->cal);
 p->m[PX_UNLOCKED]=px_now();
 filter_restore();p->m[PX_FILTER_RESTORED]=px_now();
 p->m[PX_CTRL_REG]=ctrl;p->m[PX_STATUS_REG]=status;
 p->m[PX_ACTUAL]=status&0x7fff;
 p->m[PX_DC_BEFORE]=esp_rom_crc32_le(0,p->cal.before,sizeof(p->cal.before));
 p->m[PX_DC_AFTER]=esp_rom_crc32_le(0,p->cal.after,sizeof(p->cal.after));
 if(!unchanged || !(ctrl&BIT(18)) || p->m[PX_ACTUAL]!=PX_WORDS ||
    p->m[PX_DONE]-p->m[PX_TRIGGER]>=20000) return false;
 for(unsigned j=0;j<CAPACITY;j++)
     if(j<PX_WORDS ? samples[j]==SENTINEL : samples[j]!=SENTINEL)return false;
 p->m[PX_VALIDATE_END]=px_now();return true;
}
/* Chunked safe-context transfer supports STOP/idle and one overall deadline.
 * Partial frames never gain a terminal success. UART-only admission. */
static bool px_send(const void *data,size_t bytes,uint64_t deadline) {
 const uint8_t *s=data;
 while(bytes) {
     if(px_now()>=deadline || burst_serial_stop_requested())return false;
     size_t take=bytes>128?128:bytes;
     size_t done=burst_serial_try_send(s,take);
     if(done>take)return false;
     s+=done;bytes-=done;
     vTaskDelay(1);
 }
 return true;
}
static bool px_frame(unsigned version,unsigned kind,const void *payload,size_t bytes) {
 px_context *p=px_keep;p->m[PX_VERSION]=version;p->m[PX_KIND]=kind;
 uint32_t crc=esp_rom_crc32_le(0,(void *)p->m,sizeof(p->m));
 crc=esp_rom_crc32_le(crc,payload,bytes);
 char text[192];
 int n=snprintf(text,sizeof(text),"PEXFRAME %u %u %" PRIu64 " %" PRIu64 " %u %u %08" PRIx32 "\n",
     version,kind,px_boot,p->m[PX_GEN],(unsigned)sizeof(p->m),(unsigned)bytes,crc);
 /* 128-byte chunk / tick incurs deliberate idle. Bound includes wire+ticks. */
 uint64_t deadline=px_now()+15000000;
 if(n<=0 || n>=(int)sizeof(text) || !px_send(text,(size_t)n,deadline) ||
    !px_send(p->m,sizeof(p->m),deadline) || !px_send(payload,bytes,deadline))return false;
 n=snprintf(text,sizeof(text),"\nPEXEND %u %u %" PRIu64 " %" PRIu64 "\n",version,kind,px_boot,p->m[PX_GEN]);
 return n>0 && n<(int)sizeof(text) && burst_serial_finish(text,(size_t)n);
}
static bool paused_extract_command(const char *line) {
 px_operation_version=1;
 px_expire();
 if(!strcmp(line,"STOP")) {px_free();reply("OK\n");return true;}
 if(!strcmp(line,"PEX?")) {
     reply("PEX 1 16380 64 %" PRIu64 " %" PRIu64 "\n",px_boot,px_keep?px_keep->m[PX_GEN]:0);return true;
 }
 if(!strcmp(line,"PEXCOMPACT2?")) {
     reply("PEXCOMPACT2 2 3 512 52 28 64 LEGACY1 %" PRIu64 " %" PRIu64 "\n",px_boot,px_keep?px_keep->m[PX_GEN]:0);return true;
 }
 bool compact=!strncmp(line,"PEXCOMPACT2",11);
 if(compact)px_operation_version=2;
 bool get=!strncmp(line,"PEXGET",6),drop=!strncmp(line,"PEXDROP",7);
 uint64_t a[1];
 if(get||drop) {
     if(!bank_arguments(line+(get?6:7),a,1) || !px_keep || a[0]!=px_keep->m[PX_GEN]) {
         reply("ERR pex_generation\n");return true;
     }
     if(drop) {px_free();reply("OK\n");return true;}
     if(esp_rom_crc32_le(0,(void *)px_keep->input,PX_BYTES)!=px_keep->m[PX_INPUT_CRC]) {px_error("input_changed");return true;}
     uint64_t start=px_now(),gen=px_keep->m[PX_GEN];
     if(!px_frame(1,2,px_keep->input,PX_BYTES)) {px_free();return true;}
     reply("PEXCOST 1 2 %" PRIu64 " %" PRIu64 " %" PRIu64 "\n",gen,start,px_now());
     return true;
 }
 if(strncmp(line,"PEX",3)) {
     if(px_keep){reply("ERR pex_busy\n");return true;}return false;
 }
 if(!bank_arguments(line+(compact?11:3),a,1) || a[0]>64) {reply("ERR pex_args\n");return true;}
 if(px_keep || bank_keep || det_retained || detpipe_page_count || dual_armed || dual_active || dual_next ||
    (REG_READ(DUMP_CTRL)&BIT(31))) {reply("ERR pex_busy\n");return true;}
 if(burst_serial_port()!=BURST_SERIAL_UART || frequency_mhz<2400 || frequency_mhz>2500 ||
    !rx_ready || rx_recalibration_stale()) {reply("ERR pex_config\n");return true;}
 uint32_t local=0;
 if(!bank_ptr_ok(&local,sizeof(local)) || !bank_ptr_ok(xTaskGetCurrentTaskHandle(),1) ||
    uxTaskGetStackHighWaterMark(NULL)<1024 || px_generation==UINT64_MAX) {reply("ERR pex_admission\n");return true;}
 if(burst_serial_stop_requested() || !burst_serial_finish(NULL,0)) {reply("ERR pex_stop_drain\n");return true;}
 px_attempt=++px_generation;
 uint64_t begin=px_now(),free_begin=heap_caps_get_free_size(PX_CAPS),large_begin=heap_caps_get_largest_free_block(PX_CAPS);
 memset(px_admission_heap,0,sizeof(px_admission_heap));
 px_admission_heap[0]=(uint32_t)free_begin;px_admission_heap[1]=(uint32_t)large_begin;
 /* Largest contiguous allocation first; do not fragment it with context. */
 uint32_t *input=heap_caps_malloc(PX_BYTES,PX_CAPS);
 px_admission_heap[2]=heap_caps_get_free_size(PX_CAPS);
 px_admission_heap[3]=heap_caps_get_largest_free_block(PX_CAPS);
 if(!bank_ptr_ok(input,PX_BYTES)) {if(input)heap_caps_free(input);px_error("input_memory");return true;}
 px_keep=heap_caps_calloc(1,sizeof(*px_keep),PX_CAPS);
 px_admission_heap[4]=heap_caps_get_free_size(PX_CAPS);
 px_admission_heap[5]=heap_caps_get_largest_free_block(PX_CAPS);
 if(!bank_ptr_ok(px_keep,sizeof(*px_keep))) {
     if(px_keep){heap_caps_free(px_keep);}
     px_keep=NULL;
     heap_caps_free(input);px_error("context_memory");return true;
 }
 px_context *p=px_keep;p->m[PX_GEN]=px_attempt;p->input=input;
 p->m[PX_FREE_INPUT]=px_admission_heap[2];p->m[PX_LARGEST_INPUT]=px_admission_heap[3];
 if(!px_boot)px_boot=((uint64_t)esp_random()<<32)|esp_random();
 if(!px_boot)px_boot=1;
 p->m[PX_VERSION]=1;p->m[PX_BOOT]=px_boot;p->m[PX_GEN]=px_attempt;
 p->m[PX_REQUESTED]=PX_WORDS;p->m[PX_CAP]=a[0];p->m[PX_BEGIN]=begin;
 p->m[PX_FREE_BEGIN]=free_begin;p->m[PX_LARGEST_BEGIN]=large_begin;
 p->m[PX_STACK_BEGIN]=uxTaskGetStackHighWaterMark(NULL);
 px_heap(p,PX_FREE_ALLOC,PX_LARGEST_ALLOC);p->m[PX_ALLOC_END]=px_now();
 p->m[PX_FREQ]=frequency_mhz;p->m[PX_FILTER]=(uint64_t)(int64_t)rx_filter;
 p->m[PX_AGC]=hardware_agc;p->m[PX_GAIN]=gain_code;
 /* No tune/stale helper here; locked admission below rejects changed tables. */
 rom_pbus_workmode();rom_pbus_xpd_tx_off();rom_pbus_xpd_rx_on(1);rom_set_rxclk_en(1);
 apply_gain();if(rx_lo_select(rx_lo_plan(frequency_mhz).alternate))esp_rom_delay_us(3000);
 p->m[PX_GAIN_BEFORE]=REG_READ(RX_GAIN);
 if(!px_capture(p)) {px_error("capture_or_calibration");return true;}
 if(burst_serial_stop_requested()) {px_error("stopped");return true;}
 memcpy(p->input,samples,PX_BYTES);p->m[PX_COPY_END]=px_now();
 p->m[PX_INPUT_CRC]=esp_rom_crc32_le(0,(void *)p->input,PX_BYTES);
 p->m[PX_DECODE_BEGIN]=px_now();
 int status=pkt_decode(p->input,PX_WORDS,&p->work,&p->result,(unsigned)a[0]);
 p->m[PX_DECODE_END]=px_now();
 if(status || p->m[PX_DECODE_END]-p->m[PX_DECODE_BEGIN]>=100000 || px_now()-begin>=5000000) {px_error("decode_or_time");return true;}
 if(esp_rom_crc32_le(0,(void *)p->input,PX_BYTES)!=p->m[PX_INPUT_CRC]) {px_error("input_changed");return true;}
 p->m[PX_INPUT_VERIFIED]=px_now();p->m[PX_GAIN_AFTER]=REG_READ(RX_GAIN);
 if(rx_recalibration_stale() || burst_serial_stop_requested()) {px_error("stale_or_stopped");return true;}
 p->m[PX_CAL_FRESH]=1;p->m[PX_RESULT_CRC]=esp_rom_crc32_le(0,(void *)&p->result,sizeof(p->result));
 px_heap(p,PX_FREE_AFTER,PX_LARGEST_AFTER);p->m[PX_STACK_AFTER]=uxTaskGetStackHighWaterMark(NULL);
 size_t result_bytes=sizeof(p->result);
 if(compact && !px_compact_size(&p->result,(unsigned)a[0],&result_bytes)) {px_error("compact_layout");return true;}
 unsigned version=compact?2:1,kind=compact?3:1;
 uint64_t out_start=px_now(),gen=p->m[PX_GEN];
 if(!px_frame(version,kind,&p->result,result_bytes)) {px_free();return true;}
 p->expires=px_now()+60000000;
 reply("PEXCOST %u %u %" PRIu64 " %" PRIu64 " %" PRIu64 "\n",version,kind,gen,out_start,px_now());
 return true;
}
