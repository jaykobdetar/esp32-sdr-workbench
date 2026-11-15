#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
#include "packet.h"
#define MAX_SAMPLES 16380
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define DUMP_CTRL 0
#define BIT(x) (1u<<(x))
static uint32_t samples[MAX_SAMPLES];
static bool dual_armed,dual_next,fail_capture,fail_decode,stop_now,fail_send;
static unsigned finish_calls,finish_max,fail_finish;
static unsigned allocated,alloc_calls,fail_alloc,cap_calls,decode_calls,send_calls;
static uint64_t now,capture_trigger_device_us;
static char output[20000];
static unsigned REG_READ(unsigned x){(void)x;return 0;}
static uint64_t esp_timer_get_time(void){now+=5;return now;}
static int esp_clk_cpu_freq(void){return 240000000;}
static int xPortGetCoreID(void){return 1;}
static uint32_t esp_cpu_get_cycle_count(void){return (uint32_t)(now*240);}
static void vTaskDelay(unsigned ticks){now+=ticks*1000;}
static void *heap_caps_calloc(unsigned a,unsigned b,unsigned caps){(void)caps;if(++alloc_calls==fail_alloc)return NULL;void*p=calloc(a,b);if(p)allocated++;return p;}
static void heap_caps_free(void*p){assert(p&&allocated);allocated--;free(p);}
static bool bank_ptr_ok(void*p,size_t n){(void)n;return p!=NULL;}
static void bank_release_other_retention(void){}
static void bank_discard(void){}
static void prepare_rx(void){}
static void reply(const char*fmt,...){(void)fmt;}
static bool burst_serial_stop_requested(void){return stop_now;}
static uint32_t esp_rom_crc32_le(uint32_t seed,const uint8_t*p,size_t n){(void)seed;uint32_t c=~0u;for(size_t i=0;i<n;i++){c^=p[i];for(int j=0;j<8;j++)c=(c>>1)^((c&1)?0xedb88320u:0);}return ~c;}
static bool burst_serial_send(const void*p,size_t n){send_calls++;if(fail_send)return false;assert(strlen(output)+n<sizeof(output));size_t old=strlen(output);memcpy(output+old,p,n);output[old+n]=0;return true;}
static bool burst_serial_finish(const void*p,size_t n){assert(n<=256);finish_calls++;if(n>finish_max)finish_max=(unsigned)n;if(fail_finish==finish_calls)return false;return burst_serial_send(p,n);}
static bool acquire_iq(unsigned n,unsigned src,unsigned clk,unsigned*out){assert(n==MAX_SAMPLES && src==0 && clk==0);capture_trigger_device_us=now+140;now+=1165;*out=1025;cap_calls++;return !fail_capture;}
static bool bank_arguments(const char*t,uint64_t*out,unsigned count){for(unsigned i=0;i<count;i++){if(*t++!=' ' || *t<'0'||*t>'9')return false;uint64_t n=0;while(*t>='0'&&*t<='9'){unsigned d=*t++-'0';if(n>(UINT64_MAX-d)/10)return false;n=n*10+d;}out[i]=n;}return !*t;}
int pkt_decode(const uint32_t*input,size_t n,pkt_workspace*w,pkt_result*r,unsigned cap){assert(input==samples&&n==MAX_SAMPLES&&w);memset(r,0,sizeof(*r));now+=6250;decode_calls++;if(fail_decode)return PKT_SENTINEL;if(cap){r->count=1;r->records[0].sequence=42;r->records[0].phase=0;r->records[0].polarity=1;
 memcpy(r->records[0].payload,"RFTX",4);r->records[0].payload[4]=42;
 for(unsigned j=8;j<16;j++)r->records[0].payload[j]=(uint8_t)(42+j);
 uint8_t wire[22]={0xef,0xcd,0xab,0x89,0xc3,16};memcpy(wire+6,r->records[0].payload,16);
 uint16_t crc=0xffff;for(unsigned j=0;j<22;j++)for(unsigned k=0;k<8;k++){unsigned fb=((crc>>15)^((wire[j]>>k)&1))&1;crc=(uint16_t)(crc<<1);if(fb)crc^=0x1021;}r->records[0].air_crc=crc;}else r->output_drops=1;return 0;}
#include "packet_only.h"
static void reset(void){assert(!allocated);now=0;output[0]=0;alloc_calls=cap_calls=decode_calls=send_calls=finish_calls=finish_max=fail_finish=0;fail_alloc=0;fail_capture=fail_decode=stop_now=fail_send=dual_armed=false;}
int main(void){
 reset();assert(packet_only_command("PKTONLY 3 10000 16"));assert(!allocated&&cap_calls==3&&decode_calls==3);assert(strstr(output,"END status=0 completed=3"));
 if(getenv("PONLY_TRANSCRIPT")){FILE*f=fopen(getenv("PONLY_TRANSCRIPT"),"w");assert(f);fputs(output,f);fclose(f);}
 reset();packet_only_command("PKTONLY 129 10000 16");assert(!alloc_calls&&!cap_calls);
 reset();packet_only_command("PKTONLY 2 9999 16");assert(!alloc_calls);
 reset();dual_armed=true;packet_only_command("PKTONLY 2 10000 16");assert(!alloc_calls);
 for(unsigned i=1;i<=2;i++){reset();fail_alloc=i;packet_only_command("PKTONLY 3 10000 16");assert(!allocated&&!cap_calls);}
 reset();fail_capture=true;packet_only_command("PKTONLY 3 10000 16");assert(!allocated&&cap_calls==1&&!decode_calls);assert(strstr(output,"status=1 completed=0 decoded=0 decode_errors=0 decoder_status=0 faults=1"));
 reset();fail_decode=true;packet_only_command("PKTONLY 3 10000 16");assert(!allocated&&decode_calls==1);assert(strstr(output,"END status=2"));
 reset();stop_now=true;packet_only_command("PKTONLY 3 10000 16");assert(!allocated&&!cap_calls);assert(strstr(output,"cancelled=3"));
 reset();fail_send=true;packet_only_command("PKTONLY 3 10000 16");assert(!allocated&&!cap_calls);
 reset();packet_only_command("PKTONLY 3 10000 0");assert(!allocated);assert(strstr(output,"output_drops=3"));
 reset();packet_only_command("PKTONLY?");assert(strlen(output)==128 && finish_calls==1 && finish_max==128);
 for(unsigned length=64;length<=512;length+=64){
  reset();char body[512];memset(body,'a',length-19);body[length-19]=0;uint32_t seq=0;
  assert(packet_only_line(&seq,true,"%s",body));assert(seq==1&&strlen(output)==length);
  assert(finish_calls==(length+255)/256 && finish_max<=256);
  char expected[544];char text[520];snprintf(text,sizeof(text),"PONLY 0 %s",body);
  snprintf(expected,sizeof(expected),"%s *%08" PRIx32 "\n",text,esp_rom_crc32_le(0,(const uint8_t*)text,strlen(text)));
  assert(!strcmp(output,expected));
 }
 reset();fail_finish=2;char body[400];memset(body,'x',sizeof(body)-1);body[399]=0;uint32_t seq=0;
 assert(!packet_only_line(&seq,true,"%s",body));assert(seq==0 && strlen(output)==256 && finish_calls==2);
 reset();fail_finish=1;packet_only_command("PKTONLY 3 10000 16");assert(!allocated && cap_calls==3);
 puts("PASS command bounds/allocation/capture/decode/STOP/send/cap-zero cleanup");return 0;
}
