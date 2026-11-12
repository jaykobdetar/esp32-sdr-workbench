"""Current adaptive pipeline integrated C state tests, no hardware or serial.

Extends the historical pipeline mock to exercise the live source headers, not
the archived retention patch. Both optimization levels run under UBSan.
"""

import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
#define MAX_SAMPLES 16380
#define CAPACITY 16384
#define MALLOC_CAP_DMA 4
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
static uint32_t samples[CAPACITY];
static uint32_t *det_retained;
static unsigned det_retained_n,frequency_mhz=2440,acquisition_option,clear_option;
static uint64_t now, capture_trigger_device_us;
static unsigned gain_code=40, guard_fail_at;
static bool hardware_agc;
#define RX_GAIN 0x3ff5c02cu
#define REG_READ(address) ((void)(address), UINT32_C(0x12345678))
static unsigned calls,fail_at,allocs,alloc_fail,active_allocations,reject_at;
static uintptr_t reject_lo,reject_hi;
static uint8_t wire[131072]; static size_t wire_len;
static char output[8192];
static int64_t esp_timer_get_time(void){return now;}
static void *heap_caps_malloc(size_t n,int caps){assert(caps&MALLOC_CAP_DMA);allocs++;if(allocs==alloc_fail)return NULL;void*p=malloc(n);if(p){active_allocations++;if(allocs==reject_at){reject_lo=(uintptr_t)p;reject_hi=reject_lo+n-1;}}return p;}
static void heap_caps_free(void*p){if(p){assert(active_allocations);active_allocations--;free(p);}}
static size_t heap_caps_get_free_size(int caps){(void)caps;return 250000;}
static size_t heap_caps_get_largest_free_block(int caps){(void)caps;return 72000;}
static uint32_t esp_rom_crc32_le(uint32_t crc,const uint8_t*p,size_t n){uint32_t c=~crc;for(size_t j=0;j<n;j++){c^=p[j];for(unsigned k=0;k<8;k++)c=(c>>1)^((c&1)?0xedb88320u:0);}return ~c;}
static void prepare_rx(void){}
static void vTaskDelay(unsigned n){now+=n*1000;}
static void reply(const char *fmt,...){va_list ap;va_start(ap,fmt);vsnprintf(output+strlen(output),sizeof(output)-strlen(output),fmt,ap);va_end(ap);}
static bool burst_serial_send(const void*p,size_t n){
 assert(wire_len+n<sizeof(wire));memcpy(wire+wire_len,p,n);wire_len+=n;
 if(n>12 && !memcmp(p,"DETPIPE1 END ",12)){size_t used=strlen(output);assert(used+n<sizeof(output));memcpy(output+used,p,n);output[used+n]=0;}return true;}
#include "ENERGY_HEADER"
#include "BACKGROUND_HEADER"
static bool acquire_iq_with_work(unsigned n,unsigned source,unsigned clock,unsigned *elapsed,
 void(*work)(void*),void*context){
 (void)source;(void)clock;calls++;capture_trigger_device_us=now+1;now+=1000;
 if(work)work(context);
 /* Simulate invalid current samples on a failure, AFTER prior computation. */
 if(calls==fail_at){memset(samples,0xee,sizeof(samples));reply("ERR capture_memory 0\n");return false;}
 unsigned amplitude=calls==17?100:calls==18?20:calls==19?80:calls==20?60:1;
 for(unsigned i=0;i<n;i++){int v=(i&1)?(int)amplitude:-(int)amplitude; samples[i]=(v&1023)|((v&1023)<<10);}
 for(unsigned i=n;i<CAPACITY;i++)samples[i]=UINT32_C(0xa55aa55a);
 if(calls==guard_fail_at)samples[CAPACITY-1]=0;
 *elapsed=1050;return true;
}
static bool acquire_iq_with_validation(unsigned n,unsigned s,unsigned c,unsigned *us,void(*work)(void*),void*context,unsigned(*validate)(void*,unsigned),void*vcontext){bool ok=acquire_iq_with_work(n,s,c,us,work,context);if(ok&&validate)return validate(vcontext,n)==UINT_MAX;return ok;}
#include "PIPE_HEADER"
static void reset(unsigned failure,unsigned allocation_failure){
 if(det_retained){heap_caps_free(det_retained);det_retained=NULL;}
 detpipe_clear();assert(active_allocations==0);wire_len=0;det_retained_n=0;now=calls=allocs=0;fail_at=failure;alloc_fail=allocation_failure;output[0]=0;reject_at=0;reject_lo=reject_hi=0;guard_fail_at=0;detpipe_keep=detpipe_run_keep=1;detpipe_copy_option=detpipe_kernel=0;
 detector_background_policy=DETECTOR_BACKGROUND_POLICY;
}
int main(void){
#if !DETPIPE_HEALTH
 assert(detector_pipeline_command("DETPIPEHEALTH?"));
 assert(strstr(output,"\"enabled\":false"));
 output[0]=0;
#endif
 assert(!detpipe_safe_buffer(NULL,1024));
 assert(!detpipe_safe_buffer((void*)0x3ffe8000,1024));
 assert(!detpipe_safe_buffer((void*)0x3ffe7fff,2));
 assert(!detpipe_safe_buffer((void*)0x3fff7fff,2));
 assert(!detpipe_safe_buffer((void*)(UINTPTR_MAX-2),8));
 assert(detpipe_safe_buffer((void*)0x3ffe7000,1024));
 assert(detpipe_safe_buffer((void*)0x3fff8000,1024));
 /* Background-rule selector: default 2, strict arguments, sticky across runs,
  * and every summary reports the rule that actually ran. */
 reset(0,0);assert(detector_pipeline_command("BGPOLICY?"));assert(!strcmp(output,"BGPOLICY 2\n"));
 const char *bad_policy[]={"BGPOLICY","BGPOLICY 0","BGPOLICY 3","BGPOLICY 1 x","BGPOLICY -1","BGPOLICY two"};
 for(unsigned k=0;k<sizeof(bad_policy)/sizeof(bad_policy[0]);k++){
  output[0]=0;assert(detector_pipeline_command(bad_policy[k]));
  assert(!strcmp(output,"ERR background_policy\n"));assert(detector_background_policy==2);
 }
 output[0]=0;assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 1"));
 assert(strstr(output,"\"background_policy\":2,"));
 reset(0,0);assert(detector_pipeline_command("BGPOLICY 1"));assert(!strcmp(output,"BGPOLICY 1\n"));
 for(unsigned run=0;run<2;run++){
  /* Alternating +/-1 codes give block energy 2, so the whole-unit legacy
   * background is exactly 2 and its Q16 field a whole multiple of 65536. */
  output[0]=0;calls=0;assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 1"));
  assert(strstr(output,"\"detections\":4,\"background_policy\":1,\"background_q16\":131072,\"background_adc2\":2,"));
  output[0]=0;assert(detector_pipeline_command("BGPOLICY?"));assert(!strcmp(output,"BGPOLICY 1\n"));
 }
 output[0]=0;assert(detector_pipeline_command("BGPOLICY 2"));assert(!strcmp(output,"BGPOLICY 2\n"));
 output[0]=0;calls=0;assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 1"));
 assert(strstr(output,"\"detections\":4,\"background_policy\":2,"));
 /* The Q16 rule adapted on its four positives, so it no longer equals 2.0. */
 assert(!strstr(output,"\"background_q16\":131072,"));
 for(unsigned count=1;count<=20;count++){
  reset(0,0);char cmd[80];snprintf(cmd,sizeof(cmd),"DETPIPE1 %u 256 6 4000 1",count);
  assert(detector_pipeline_command(cmd));
  char expected[100];snprintf(expected,sizeof(expected),"\"status\":0,\"captures\":%u,\"processed_captures\":%u",count,count);
  assert(strstr(output,expected));
  if(count<=16){assert(detpipe_retained_n==0);assert(strstr(output,"\"detections\":0"));}
  else{assert(detpipe_retained_n==256);assert((detpipe_pages[0][0]|((detpipe_pages[0][1]&3)<<8))==924);assert(detpipe_retained_us==1050);assert(detpipe_retained_generation==17);}
 }
 for(unsigned failure=1;failure<=20;failure++){
  reset(failure,0);assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 1"));
  char expected[100];snprintf(expected,sizeof(expected),"\"status\":1,\"captures\":%u,\"processed_captures\":%u",failure-1,failure-1);
  assert(strstr(output,expected));assert(strstr(output,"ERR capture_memory"));
  if(failure>17){assert(detpipe_retained_n==256);assert((detpipe_pages[0][0]|((detpipe_pages[0][1]&3)<<8))==924);assert(detpipe_retained_generation==17);}
 }
 for(unsigned fail=1;fail<=11;fail++){
  reset(0,fail);assert(detector_pipeline_command("DETPIPE1 20 16380 6 4000 1"));
  assert(strstr(output,"ERR pipeline_memory"));assert(!calls);assert(!detpipe_page_count);assert(!detpipe_retained_n);assert(active_allocations==0);
 }
 reset(0,0);assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 0"));
 assert(!detpipe_page_count);assert(!detpipe_retained_n);assert(strstr(output,"\"captures\":20,\"processed_captures\":20"));
 reset(0,0);assert(detector_pipeline_command("DETPIPE1 20 257 6 4000 1"));
 assert(strstr(output,"\"total_samples\":5140,\"analyzed_samples\":5120"));
 reset(0,0);assert(detector_pipeline_command("DETPIPE1 5001 256 6 4000 1"));assert(!calls);
 /* Exact CAP20 packing, page boundaries, odd tails, incremental CRC and GET. */
 assert(esp_rom_crc32_le(0,(const uint8_t*)"123456789",9)==0xcbf43926u);
 const unsigned lengths[]={256,257,1637,1638,1639,3276,3277,3278,4915,4916,8191,8192,16379,16380};
 for(unsigned k=0;k<sizeof(lengths)/sizeof(lengths[0]);k++){
  unsigned n=lengths[k];reset(0,0);char cmd[80];snprintf(cmd,sizeof(cmd),"DETPIPE1 1 %u 6 4000 1",n);
  assert(detector_pipeline_command(cmd));
  uint32_t words[16380];uint8_t packed[40952];memset(packed,0xa5,sizeof(packed));
  for(unsigned j=0;j<n;j++)words[j]=(j*7919u)^0xabcdef12u;
  detpipe_pack(words,n);
  size_t bytes=(n*20+7)/8,at=0;
  for(unsigned page=0;page<detpipe_page_count;page++){
   assert(detpipe_page_sizes[page]<=4096);
   memcpy(packed+at,detpipe_pages[page],detpipe_page_sizes[page]);at+=detpipe_page_sizes[page];
  }
  assert(at==bytes);assert(packed[bytes]==0xa5);
  for(unsigned j=0;j<n;j++){
   unsigned bit=j*20,off=bit/8,shift=bit%8;
   uint32_t word=((uint32_t)packed[off]|((uint32_t)packed[off+1]<<8)|((uint32_t)packed[off+2]<<16))>>shift;
   assert((word&0xfffff)==(words[j]&0xfffff));
  }
  uint32_t expected_crc=esp_rom_crc32_le(0,packed,bytes);assert(detpipe_crc()==expected_crc);
  detpipe_retained_n=n;detpipe_retained_us=777;wire_len=0;
  assert(detector_pipeline_command("DETPIPEGET"));
  uint8_t*nl=memchr(wire,'\n',wire_len);assert(nl);size_t header=nl-wire+1;
  unsigned got_n,us;uint32_t got_crc;
  assert(sscanf((const char*)wire,"DATA %u %"SCNx32" %u",&got_n,&got_crc,&us)==3);
  assert(got_n==n && got_crc==expected_crc && us==777);
  assert(wire_len==header+bytes);assert(!memcmp(wire+header,packed,bytes));
 }
 /* Same pipeline, exact candidate3, strongest final/earlier retention survives. */
 for(unsigned kernel=0;kernel<=3;kernel+=3){
  reset(0,0);char cmd[40];snprintf(cmd,sizeof(cmd),"PIPEKERNEL %u",kernel);assert(detector_pipeline_command(cmd));
  assert(detpipe_kernel==kernel);assert(detector_pipeline_command("DETPIPE1 20 257 6 4000 1"));
  assert(detpipe_retained_n==257 && detpipe_retained_generation==17);
  uint32_t state=7,words[16380];
  for(unsigned trial=0;trial<200;trial++){
   for(unsigned j=0;j<16380;j++){state=state*1664525u+1013904223u;words[j]=state;}
   unsigned n=trial%4 ? state%16381:16380;uint32_t m0,p0,m3,p3;
   detector_energy(words,n,&m0,&p0);pipeline_energy_flash_3(words,n,&m3,&p3);assert(m0==m3&&p0==p3);
  }
 }
 reset(0,0);detector_pipeline_command("PIPEKERNEL 2");assert(strstr(output,"ERR pipeline_kernel"));
 /* Allocation-only diagnostic must never invoke acquisition and always clean ordinary failures. */
 for(unsigned failure=0;failure<=11;failure++){
  reset(0,failure);assert(detector_pipeline_command("DETPIPEALLOCTEST 16380 1"));
  assert(calls==0 && active_allocations==0);
  assert(strstr(output,"DETPIPEALLOC BEGIN 16380 1"));
  assert(strstr(output,failure?"DETPIPEALLOC END status=1":"DETPIPEALLOC END status=0"));
  assert(strstr(output,"stage=raw") && strstr(output,"internal=") && strstr(output,"dram_hi=") && strstr(output,"aperture="));
 }
 /* Simulate an allocated INTERNAL/8BIT region rejected by DRAM membership. */
 for(unsigned reject=1;reject<=11;reject++){
  reset(0,0);reject_at=reject;assert(detector_pipeline_command("DETPIPEALLOCTEST 16380 1"));
  assert(!calls && !active_allocations);assert(strstr(output,"DETPIPEALLOC END status=1"));
  assert(strstr(output,"internal=1 dram_lo=0 dram_hi=0 byte=1 aperture=1 range=1"));
  reset(0,0);reject_at=reject;assert(detector_pipeline_command("DETPIPE1 20 16380 6 4000 1"));
  assert(!calls && !active_allocations);assert(strstr(output,"ERR pipeline_memory stage="));
  assert(strstr(output,"internal=1 dram_lo=0 dram_hi=0 byte=1 aperture=1 range=1"));
 }
 reset(0,0);assert(detector_pipeline_command("DETPIPEALLOCTEST 255 1"));assert(strstr(output,"ERR pipeline_alloc_args"));assert(!calls && !allocs);

 /* New one-shot three-crop path: allocation sizes, latest/final drain, payload
  * indexing, timestamps and pending selector reset, for both kernels/copy modes. */
 for(unsigned kernel=0;kernel<=3;kernel+=3)for(unsigned fused=0;fused<=1;fused++){
  reset(0,0);detpipe_kernel=kernel;detpipe_copy_option=fused;
  assert(detector_pipeline_command("PIPEKEEP 3"));
  assert(detpipe_keep==3);assert(detector_pipeline_command("PIPEKEEP?"));
  assert(detector_pipeline_command("DETPIPE1 20 16380 6 4000 1"));
  assert(detpipe_keep==1 && detpipe_run_keep==3);
  assert(detpipe_page_count==12 && active_allocations==12);
  assert(strstr(output,"\"status\":0,\"captures\":20,\"processed_captures\":20"));
  assert(strstr(output,"\"retention_capacity\":3"));
  assert(strstr(output,"\"gain_register_start\":305419896"));
  assert(strstr(output,"\"first_trigger_device_us\":1"));
  assert(strstr(output,"\"last_trigger_device_us\":19001"));
  unsigned generations=0;size_t retained_bytes=0;
  for(unsigned page=0;page<detpipe_page_count;page++)retained_bytes+=detpipe_page_sizes[page];
  assert(retained_bytes==38400 && retained_bytes<DETPIPE_MAX_PACKED);
  for(unsigned slot=0;slot<3;slot++){
   detector_candidate_t *c=&detpipe_candidates[slot];
   assert(c->samples==5120 && c->offset_samples+c->samples<=16380);
   assert(!(c->offset_samples&7) && c->trigger_device_us==(c->generation-1)*1000+1);
   assert(c->generation==17 || c->generation==19 || c->generation==20);
   generations|=1u<<(c->generation-17);
   wire_len=0;char get[32];snprintf(get,sizeof(get),"DETPIPEGET %u",slot);
   assert(detector_pipeline_command(get));
   uint8_t *nl=memchr(wire,'\n',wire_len);assert(nl);size_t header=(size_t)(nl-wire)+1;
   unsigned got_n,us;uint32_t got_crc;
   assert(sscanf((const char*)wire,"DATA %u %"SCNx32" %u",&got_n,&got_crc,&us)==3);
   assert(got_n==5120 && us==1050 && wire_len==header+12800);
   assert(got_crc==esp_rom_crc32_le(0,wire+header,12800));
   unsigned amplitude=c->generation==17?100:c->generation==19?80:60;
   for(unsigned j=0;j<got_n;j++){
    unsigned bit=j*20,off=bit/8,shift=bit%8;
    uint8_t *data=wire+header;
    uint32_t word=((uint32_t)data[off]|((uint32_t)data[off+1]<<8)|((uint32_t)data[off+2]<<16))>>shift;
    int value=(j&1)?(int)amplitude:-(int)amplitude;
    assert((word&0xfffffu)==(((unsigned)value&1023)|(((unsigned)value&1023)<<10)));
   }
  }
  assert(generations==13); /* generations 17,19,20: final pending capture drained */
  assert(detpipe_retained_generation==17 && detpipe_retained_trigger_us==16001);
  wire_len=0;assert(detector_pipeline_command("DETPIPEGET"));assert(wire_len>12800);
  assert(detector_pipeline_command("DETPIPEGET 3"));assert(strstr(output,"ERR no_retained_event"));
  /* A following legacy call cannot inherit the crop option. It frees all pages. */
  assert(detector_pipeline_command("DETPIPE1 1 16380 6 4000 0"));
  assert(detpipe_run_keep==1 && active_allocations==0 && !detpipe_retained_n);
 }
 /* Every raw/page allocation failure and rejected address releases all ordinary
  * allocations, never starts RF work, and consumes the one-shot setting. */
 for(unsigned point=1;point<=13;point++)for(unsigned rejected=0;rejected<=1;rejected++){
  reset(0,rejected?0:point);reject_at=rejected?point:0;
  assert(detector_pipeline_command("PIPEKEEP 3"));
  assert(detector_pipeline_command("DETPIPE1 20 16380 6 4000 1"));
  assert(strstr(output,"ERR pipeline_memory"));
  assert(!calls && !active_allocations && !detpipe_page_count && !detpipe_retained_n);
  assert(detpipe_keep==1);
 }
 /* An invalid current acquisition must not erase the previous valid immutable
  * capture, and may not publish partial current data through fused validation. */
 for(unsigned fused=0;fused<=1;fused++){
  reset(19,0);detpipe_copy_option=fused;
  assert(detector_pipeline_command("PIPEKEEP 3"));
  assert(detector_pipeline_command("DETPIPE1 20 16380 6 4000 1"));
  assert(strstr(output,"\"status\":1,\"captures\":18,\"processed_captures\":18"));
  assert(detpipe_candidates[0].generation==17 && detpipe_candidates[1].generation==18);
  assert(!detpipe_candidates[2].samples);
  assert(detpipe_candidates[1].trigger_device_us==17001);
 }
 reset(0,0);detpipe_copy_option=1;guard_fail_at=19;
 assert(detector_pipeline_command("PIPEKEEP 3"));
 assert(detector_pipeline_command("DETPIPE1 20 16380 6 4000 1"));
 assert(strstr(output,"\"status\":1,\"captures\":18,\"processed_captures\":18"));
 assert(detpipe_candidates[1].generation==18 && !detpipe_candidates[2].samples);
 assert(detpipe_retained_generation==17);
 /* Empty slots, explicit cancellation and invalid selector input are bounded. */
 reset(0,0);assert(detector_pipeline_command("PIPEKEEP 3"));
 assert(detector_pipeline_command("DETPIPE1 1 256 6 4000 1"));
 assert(detector_pipeline_command("DETPIPEGET 0"));assert(strstr(output,"ERR no_retained_event"));
 assert(detector_pipeline_command("PIPEKEEP 3"));assert(detector_pipeline_command("PIPEKEEP 1"));
 assert(detpipe_keep==1);assert(detector_pipeline_command("PIPEKEEP 2"));
 assert(strstr(output,"ERR pipeline_keep"));assert(detpipe_keep==1);


 /* Stable top-three selection: equal scores retain earlier generations. */
 for(unsigned encoded=0;encoded<4096;encoded++){
  detector_candidate_t candidates[3]={{0}};
  unsigned scores[6],order[6]={0,1,2,3,4,5},code=encoded;
  for(unsigned generation=0;generation<6;generation++){
   scores[generation]=100+(code%4)*100;code/=4;
   unsigned slot=detector_candidate_slot(candidates,3,scores[generation]);
   if(slot<3)candidates[slot]=(detector_candidate_t){.samples=256,
    .generation=generation+1,.score_milli=scores[generation]};
  }
  for(unsigned a=0;a<6;a++)for(unsigned b=a+1;b<6;b++){
   if(scores[order[b]]>scores[order[a]] ||
      (scores[order[b]]==scores[order[a]] && order[b]<order[a])){
    unsigned tmp=order[a];order[a]=order[b];order[b]=tmp;
   }
  }
  unsigned actual=0,expected=0;
  for(unsigned j=0;j<3;j++){
   actual|=1u<<(candidates[j].generation-1);expected|=1u<<order[j];
  }
  assert(actual==expected);
 }
 /* Exercise the same tie replacement through commit, packed retention and GET.
  * Reset background to a fixed valid reference so equal scores are deliberate. */
 reset(0,0);assert(detector_pipeline_command("PIPEKEEP 3"));
 assert(detector_pipeline_command("DETPIPE1 1 256 6 1000 1"));
 detpipe_state_t ties={.copy=samples,.n=256};
 for(unsigned generation=17;generation<=20;generation++){
  unsigned amplitude=generation==20?2:1;
  for(unsigned j=0;j<256;j++){
   int value=(j&1)?(int)amplitude:-(int)amplitude;
   samples[j]=((unsigned)value&1023)|(((unsigned)value&1023)<<10);
  }
  ties.background=(detector_background_t){.count=16,.q16=65536};
  ties.mean=ties.peak=2*amplitude*amplitude;
  ties.generation=generation;ties.observed_us=1050;
  ties.trigger_device_us=(generation-1)*1000+1;
  ties.pending=ties.ready=true;
  detpipe_commit(&ties,1000,true);
 }
 assert(!ties.pack_failed && ties.processed==4 && ties.events==4);
 assert(detpipe_candidates[0].generation==17 && detpipe_candidates[1].generation==18);
 assert(detpipe_candidates[2].generation==20 && detpipe_best_slot==2);
 assert(detpipe_retained_generation==20 && detpipe_retained_trigger_us==19001);
 assert(detector_candidate_slot(detpipe_candidates,3,2000)==3);
 wire_len=0;assert(detector_pipeline_command("DETPIPEGET"));
 uint8_t *tie_payload=memchr(wire,'\n',wire_len);assert(tie_payload);tie_payload++;
 assert((size_t)(tie_payload-wire)+640==wire_len);
 assert((tie_payload[0]|((tie_payload[1]&3)<<8))==1022);

 reset(0,0);puts("pipeline candidate state, drain, retention, range, allocation-failure tests passed");
}
"""


def main():
    source = (
        SOURCE.replace('ENERGY_HEADER', str(ROOT / 'main/targets/esp32/detector_energy.h'))
        .replace('PIPE_HEADER', str(ROOT / 'main/targets/esp32/detector_pipeline.h'))
        .replace('BACKGROUND_HEADER', str(ROOT / 'main/targets/esp32/detector_background.h'))
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / 'esp_memory_utils.h').write_text(
            'static bool esp_ptr_internal(const void*p){return p!=NULL;}\nstatic bool esp_ptr_in_dram(const void*p){return p!=NULL&&!((uintptr_t)p>=reject_lo&&(uintptr_t)p<=reject_hi);}\nstatic bool esp_ptr_byte_accessible(const void*p){return p!=NULL;}\n'
        )
        (p / 'test.c').write_text(source)
        for opt in ('-O0', '-O2'):
            subprocess.run(
                [
                    'cc',
                    '-std=c11',
                    opt,
                    '-Wall',
                    '-Wextra',
                    '-Werror',
                    '-fsanitize=undefined',
                    '-fno-sanitize-recover=all',
                    '-I' + td,
                    str(p / 'test.c'),
                    '-o',
                    str(p / 'test'),
                ],
                check=True,
            )
            subprocess.run([str(p / 'test')], check=True)


def test_pipeline_state_regressions():
    main()


if __name__ == '__main__':
    main()
