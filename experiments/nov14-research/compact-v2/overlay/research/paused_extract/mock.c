/* Host-only wrapper lifecycle mock. Not peripheral emulation or MCU proof. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
#include "paused_calibration.h"
#include "packet_fixture.h"
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_DMA 4
#define BURST_SERIAL_UART 1
#define CAPACITY 16384
#define SENTINEL 0xa55aa55au
#define BIT(n) (1u<<(n))
#define DUMP_CTRL 0
#define DUMP_STATUS 1
#define DUMP_BYTES 2
#define ADC_CTRL 3
#define DPORT_IRAM_DRAM_AHB_SEL_REG 4
#define RX_GAIN 5
#define ADC_ON_FORCE (BIT(9)|BIT(8))
#define DPORT_MAC_DUMP_MODE_M 3
#define DPORT_MAC_DUMP_MODE_S 0
static uint32_t samples[CAPACITY],regs[6];
static bool mapped,leased,filtered,fail_capture,fail_guard,fail_lock,fail_dc,fail_send,stop_now;
static bool fail_short,fail_decode,fail_mutate,fail_slow,late_stop;
static size_t allocated_sizes[3];
static int alloc_index,fail_alloc,live,reply_count;
static unsigned stop_check,stop_at;
static uint64_t clock_us=1000;
static uint8_t output[150000];static size_t output_n;
static unsigned acquisition_option,clear_option,gain_code=40,frequency_mhz=2480;
static int rx_filter=-1;
static bool hardware_agc=true,rx_ready=true,dual_armed,dual_active;
static uint64_t dual_next,capture_trigger_device_us;
static void *bank_keep,*det_retained;static unsigned detpipe_page_count;
static void safe(void){assert(!mapped);}
static uint64_t esp_timer_get_time(void){clock_us+=10;return clock_us;}
static void esp_rom_delay_us(unsigned n){clock_us+=n;}
static void wr(unsigned r,uint32_t v){regs[r]=v;if(r==4)mapped=(v&3)==3;}
static void set(unsigned r,uint32_t b){regs[r]|=b;if(r==0&&b==BIT(19)&&!fail_capture){for(unsigned j=0;j<16380;j++)samples[j]=0;for(unsigned k=0;k<3;k++)memcpy(samples+256+k*2048,packet_fixture,sizeof(packet_fixture));regs[0]|=BIT(18);regs[1]=fail_short?100:16380;if(fail_guard)samples[16383]=0;}}
#define REG_READ(r) (regs[(r)])
#define REG_WRITE(r,v) wr(r,v)
#define REG_SET_BIT(r,b) set(r,b)
#define REG_CLR_BIT(r,b) (regs[r]&=~(b))
#define DPORT_REG_READ(r) REG_READ(r)
#define DPORT_REG_WRITE(r,v) REG_WRITE(r,v)
static uint32_t esp_rom_crc32_le(uint32_t crc,const void *data,size_t n){const uint8_t*p=data;crc=~crc;while(n--){crc^=*p++;for(int j=0;j<8;j++)crc=(crc>>1)^(0xedb88320u&-(crc&1));}return ~crc;}
static void *heap_caps_malloc(size_t n,unsigned c){safe();(void)c;++alloc_index;if(alloc_index<3)allocated_sizes[alloc_index]=n;if(alloc_index==fail_alloc)return NULL;void*p=malloc(n);if(p)live++;return p;}
static void *heap_caps_calloc(size_t n,size_t s,unsigned c){void*p=heap_caps_malloc(n*s,c);if(p)memset(p,0,n*s);return p;}
static void heap_caps_free(void*p){safe();assert(!leased);if(p){live--;free(p);}}
static unsigned heap_caps_get_free_size(unsigned c){safe();(void)c;return 100000-live*100;}
static unsigned heap_caps_get_largest_free_block(unsigned c){return heap_caps_get_free_size(c);}
static bool bank_ptr_ok(void*p,size_t n){return p&&n;}
static bool bank_arguments(const char*t,uint64_t*a,unsigned n){if(n!=1||*t++!=' '||*t<'0'||*t>'9')return false;uint64_t v=0;while(*t>='0'&&*t<='9'){unsigned d=*t++-'0';if(v>(UINT64_MAX-d)/10)return false;v=v*10+d;}*a=v;return !*t;}
static void *xTaskGetCurrentTaskHandle(void){return &clock_us;}
static unsigned uxTaskGetStackHighWaterMark(void*p){safe();(void)p;return 4096;}
static unsigned burst_serial_port(void){safe();return BURST_SERIAL_UART;}
static bool burst_serial_stop_requested(void){safe();return stop_now||(++stop_check==stop_at);}
static void vTaskDelay(unsigned ticks){safe();assert(!leased);clock_us+=1000*ticks;}
static size_t burst_serial_try_send(const void*p,size_t n){safe();assert(!leased);if(fail_send)return 0;assert(output_n+n<=sizeof(output));memcpy(output+output_n,p,n);output_n+=n;return n;}
static bool burst_serial_finish(const void*p,size_t n){safe();assert(!leased);if(fail_send)return false;if(n)burst_serial_try_send(p,n);clock_us+=40000;if(n&&late_stop)stop_now=true;return true;}
static void reply(const char*f,...){safe();assert(!leased);char b[256];va_list a;va_start(a,f);int n=vsnprintf(b,sizeof(b),f,a);va_end(a);reply_count++;if(n>0)burst_serial_try_send(b,(size_t)n);}
static bool rx_recalibration_stale(void){safe();assert(!leased);return false;}
static void filter_apply(void){safe();assert(!leased);filtered=true;}
static void filter_restore(void){safe();assert(!leased);filtered=false;}
static void rom_pbus_workmode(void){safe();assert(!leased);}
static void rom_pbus_xpd_tx_off(void){rom_pbus_workmode();}
static void rom_pbus_xpd_rx_on(int a){(void)a;rom_pbus_workmode();}
static void rom_set_rxclk_en(int a){(void)a;rom_pbus_workmode();}
static void apply_gain(void){rom_pbus_workmode();}
typedef struct{bool alternate;} rx_lo_plan_t;
static rx_lo_plan_t rx_lo_plan(unsigned f){(void)f;return(rx_lo_plan_t){false};}
static bool rx_lo_select(bool a){safe();assert(!leased);return a;}
static uint32_t esp_random(void){safe();return 123;}
bool paused_calibration_begin(paused_calibration*s){safe();assert(!leased);if(fail_lock)return false;s->handle=1;leased=true;return true;}
bool paused_calibration_end(paused_calibration*s){safe();assert(leased&&s->handle);leased=false;s->handle=0;return !fail_dc;}
#include "packet_decimated_dfa.h"
static int instrument_decode(const uint32_t *data,size_t n,pkt_workspace*w,pkt_result*r,unsigned cap) {
 safe();assert(!leased);int rc=pkt_decode(data,n,w,r,cap);
 if(fail_mutate)((uint32_t *)data)[0]^=1;
 if(fail_slow)clock_us+=100001;
 return fail_decode?1:rc;
}
#define pkt_decode instrument_decode
static void *instrument_copy(void *a,const void*b,size_t n){if(n>=65520){safe();assert(!leased);}return memcpy(a,b,n);}
#define memcpy instrument_copy
#include "paused_extract.h"
#undef pkt_decode
#undef memcpy
static void reset(void){px_free();assert(!live&&!mapped&&!leased&&!filtered);memset(regs,0,sizeof(regs));output_n=0;fail_capture=fail_guard=fail_lock=fail_dc=fail_send=stop_now=false;alloc_index=fail_alloc=0;memset(allocated_sizes,0,sizeof(allocated_sizes));stop_at=stop_check=0;fail_short=fail_decode=fail_mutate=fail_slow=late_stop=false;}
int main(int argc,char**argv){
 assert(argc==2);(void)acquisition_option;(void)clear_option;
 reset();assert(paused_extract_command("PEX 64"));assert(px_keep&&live==2&&!mapped&&!leased&&!filtered);assert(allocated_sizes[1]==65520&&allocated_sizes[2]==sizeof(px_context));assert(px_keep->result.count==3);uint64_t first=px_keep->m[PX_GEN];
 FILE*f=fopen(argv[1],"wb");assert(f);fwrite(output,1,output_n,f);fclose(f);
 output_n=0;char cmd[80];snprintf(cmd,sizeof(cmd),"PEXGET %"PRIu64,first);paused_extract_command(cmd);
 char path[1024];snprintf(path,sizeof(path),"%s.iq",argv[1]);f=fopen(path,"wb");assert(f);fwrite(output,1,output_n,f);fclose(f);
 paused_extract_command("STOP");assert(!px_keep&&!live);
 for(int mode=0;mode<7;mode++){reset();if(mode==0)fail_alloc=1;if(mode==1)fail_alloc=2;if(mode==2)fail_lock=true;if(mode==3)fail_capture=true;if(mode==4)fail_guard=true;if(mode==5)fail_dc=true;if(mode==6)stop_at=3;paused_extract_command("PEX 0");assert(!px_keep&&!live&&!mapped&&!leased&&!filtered);if(mode==3){snprintf(path,sizeof(path),"%s.error",argv[1]);f=fopen(path,"wb");assert(f);fwrite(output,1,output_n,f);fclose(f);}}
 reset();paused_extract_command("PEX 0");assert(px_keep&&px_keep->result.count==0&&px_keep->result.output_drops>=3);uint64_t gen=px_keep->m[PX_GEN];assert(gen>first);paused_extract_command("CAPS");assert(px_keep);paused_extract_command("PEXDROP 0");assert(px_keep);clock_us=px_keep->expires;assert(!paused_extract_command("CAPS"));assert(!px_keep&&!live);
 for(int mode=0;mode<4;mode++){reset();if(mode==0)fail_short=true;if(mode==1)fail_decode=true;if(mode==2)fail_mutate=true;if(mode==3)fail_slow=true;paused_extract_command("PEX 64");assert(!px_keep&&!live&&!mapped&&!leased&&!filtered);}
 for(unsigned at=1;at<=12;at++){reset();stop_at=at;paused_extract_command("PEX 64");assert(!px_keep&&!live&&!mapped&&!leased&&!filtered);}
 reset();dual_armed=true;assert(paused_extract_command("PEX 64"));assert(!px_keep&&!live);dual_armed=false;
 reset();rx_ready=false;paused_extract_command("PEX 64");assert(!px_keep&&!live);rx_ready=true;
 reset();px_generation=UINT64_MAX;paused_extract_command("PEX 64");assert(!px_keep&&!live);px_generation=100;
 reset();late_stop=true;paused_extract_command("PEX 64");assert(px_keep&&stop_now);paused_extract_command("STOP");assert(!px_keep&&!live);
 const char*bad[]={"PEX","PEX -1","PEX 65","PEX 1x","PEX 18446744073709551616","PEX 1 2"};for(unsigned j=0;j<sizeof(bad)/sizeof(*bad);j++){reset();uint64_t g=px_generation;paused_extract_command(bad[j]);assert(!px_keep&&px_generation==g);}
 reset();paused_extract_command("PEX 64");fail_send=true;snprintf(cmd,sizeof(cmd),"PEXGET %"PRIu64,px_keep->m[PX_GEN]);paused_extract_command(cmd);assert(!px_keep&&!live);reset();
 puts("wrapper lifecycle PASS (host mocks only)");return 0;
}
