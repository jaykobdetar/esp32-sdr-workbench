#include "nrf.h"
#ifndef FW_VERSION
#define FW_VERSION "0.2.2"
#endif
#if defined(CONFIG_NFCT_PINS_AS_GPIOS) || defined(CONFIG_GPIO_AS_PINRESET)
#error "Factory UICR changes are prohibited"
#endif
#include "tusb.h"
#include "schedule.h"
#include "diagnostic.h"
#include "stop_control.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

extern void tusb_hal_nrf_power_event(uint32_t event);
const char recovery_contract[] __attribute__((used,section(".recovery_contract"))) = "UF2_ENTRY_0x57_v1";
static volatile uint32_t ms;
static uint32_t freq=2402,mode=1,length=32,interval=10000,jitter=0,random_seed=1,burst_count=0,burst_gap_us=0,hop_every=1,active_freq=2402;
static int power=-20;
static bool running,busy,reset_pending;
static schedule_t schedule;
static uint16_t hops[16];static uint32_t hop_count,pattern_len;static uint8_t pattern[244];
static uint32_t first_end_us,completion_min_us,completion_max_us,completion_total_us;
static uint32_t attempted,completed,errors,count_limit,start_us,end_us,tx_us,last_end_us,reset_ms,elapsed_us;
static uint8_t packet[256] __attribute__((aligned(4)));
static char line[1024];static unsigned line_n;static bool overflow;
uint32_t board_millis(void){return ms;}
void SysTick_Handler(void){ms++;}
static uint32_t now_us(void){NRF_TIMER2->TASKS_CAPTURE[0]=1;return NRF_TIMER2->CC[0];}
static void record_completion(uint32_t n){
 NRF_RADIO->EVENTS_END=0;uint32_t latency=n-tx_us;completed++;
 if(completed==1){first_end_us=n-start_us;completion_min_us=latency;}
 if(latency<completion_min_us)completion_min_us=latency;
 if(latency>completion_max_us)completion_max_us=latency;
 saturating_add(&completion_total_us,latency,&schedule.saturated);
 last_end_us=n-start_us;busy=false;
}
static void reboot(void);
static void stop_request_disable(void){NRF_RADIO->SHORTS=0;NRF_RADIO->TASKS_DISABLE=1;__DSB();}
static bool stop_is_disabled(void){return NRF_RADIO->STATE==RADIO_STATE_STATE_Disabled;}
static bool stop_end_pending(void){__DSB();return NRF_RADIO->EVENTS_END!=0;}
static void stop_hard_off(void){NRF_RADIO->POWER=0;__DSB();}
static void radio_stop(void){
 static const stop_control_ops ops={stop_request_disable,stop_is_disabled,stop_end_pending,now_us,stop_hard_off};
 stop_control_result result=stop_control(&ops,busy);
 if(result==STOP_ACCOUNT_COMPLETION)record_completion(now_us());
 busy=false;
 if(running)elapsed_us=now_us()-start_us;
 running=false;
 if(result==STOP_DISABLE_TIMEOUT){errors++;reboot();}
}
static void reply(const char *s){tud_cdc_write(s,strlen(s));tud_cdc_write_flush();}
static void error(const char *s){char b[160];snprintf(b,sizeof b,"{\"ok\":false,\"error\":\"%s\"}\n",s);reply(b);}
static void status(void){char b[1900],hop_text[96],hex_text[489];unsigned pos=0;
 const char *digits="0123456789abcdef";for(unsigned i=0;i<pattern_len;i++){hex_text[2*i]=digits[pattern[i]>>4];hex_text[2*i+1]=digits[pattern[i]&15];}hex_text[2*pattern_len]=0;
 hop_text[0]=0;for(unsigned i=0;i<hop_count;i++)pos+=snprintf(hop_text+pos,sizeof(hop_text)-pos,"%s%lu",i?",":"",(unsigned long)hops[i]);
 snprintf(b,sizeof b,
 "{\"ok\":true,\"app\":\"rf-test-tx\",\"version\":\"" FW_VERSION "\",\"protocol\":1,\"updater\":true,\"healthy\":%s,\"running\":%s,\"power_dbm\":%d,\"timing_saturated\":%s,\"payload_hex\":\"%s\",\"hop_list\":[%s],\"frequency_mhz\":%lu,\"active_frequency_mhz\":%lu,\"mode_mbps\":%lu,\"payload_len\":%lu,\"interval_us\":%lu,\"jitter_us\":%lu,\"seed\":%lu,\"burst_count\":%lu,\"burst_gap_us\":%lu,\"hop_every\":%lu,\"payload_pattern_len\":%lu,\"scheduled\":%lu,\"attempted\":%lu,\"completed\":%lu,\"missed_slots\":%lu,\"late_slots\":%lu,\"launch_lateness_min_us\":%lu,\"launch_lateness_max_us\":%lu,\"launch_lateness_total_us\":%lu,\"completion_latency_min_us\":%lu,\"completion_latency_max_us\":%lu,\"completion_latency_total_us\":%lu,\"first_end_us\":%lu,\"last_end_us\":%lu,\"errors\":%lu,\"uptime_ms\":%lu,\"elapsed_us\":%lu}\n",
 errors?"false":"true",running?"true":"false",power,schedule.saturated?"true":"false",hex_text,hop_text,
 (unsigned long)freq,(unsigned long)active_freq,(unsigned long)mode,(unsigned long)length,(unsigned long)interval,(unsigned long)jitter,(unsigned long)random_seed,(unsigned long)burst_count,(unsigned long)burst_gap_us,(unsigned long)hop_every,(unsigned long)pattern_len,(unsigned long)schedule.scheduled,(unsigned long)attempted,(unsigned long)completed,(unsigned long)schedule.missed,(unsigned long)schedule.late,(unsigned long)schedule.late_min,(unsigned long)schedule.late_max,(unsigned long)schedule.late_total,(unsigned long)completion_min_us,(unsigned long)completion_max_us,(unsigned long)completion_total_us,(unsigned long)first_end_us,(unsigned long)last_end_us,(unsigned long)errors,(unsigned long)ms,(unsigned long)(running?now_us()-start_us:elapsed_us));reply(b);}
static void reboot(void){NRF_RADIO->TASKS_DISABLE=1;NRF_POWER->GPREGRET=0x57;__DSB();NVIC_SystemReset();}
void HardFault_Handler(void){reboot();}
void WDT_IRQHandler(void){reboot();}
void tud_umount_cb(void){radio_stop();}
void tud_suspend_cb(bool wake){(void)wake;radio_stop();}
static bool parse_num(char *s,long *out){bool neg=false;unsigned long n=0;if(*s=='-'){neg=true;s++;}if(!*s)return false;while(*s){if(*s<'0'||*s>'9'||n>200000000)return false;n=n*10+(*s++-'0');}if(n>2000000000)return false;*out=neg?-(long)n:(long)n;return true;}
static int hexval(char c){if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;if(c>='A'&&c<='F')return c-'A'+10;return -1;}
static bool parse_hops(char *s,uint16_t *list,unsigned *count){
 *count=0;if(!strcmp(s,"off"))return true;
 while(*s){if(*count>=16)return false;char *comma=strchr(s,',');if(comma)*comma=0;long n;
 if(!parse_num(s,&n)||n<2402||n>2480)return false;
 list[(*count)++]=n;
 if(!comma)return true;
 s=comma+1;if(!*s)return false;}return false;
}
static void command(void){
 if(reset_pending){error("reset_pending");return;}
 if(!strcmp(line,"DEVICE")){if(running||busy||NRF_RADIO->STATE!=RADIO_STATE_STATE_Disabled){error("stop_before_device");return;}char b[1200];diagnostic_device(b,sizeof b);reply(b);return;}
 if(!strcmp(line,"HELLO")||!strcmp(line,"STATUS")){status();return;}
 if(!strcmp(line,"STOP")){radio_stop();status();return;}
 if(!strcmp(line,"BOOTLOADER")){radio_stop();reply("{\"ok\":true,\"bootloader\":true}\n");reset_pending=true;reset_ms=ms+300;return;}
 bool config=!strncmp(line,"CONFIG ",7),start=!strncmp(line,"START ",6);
 if(!config&&!start){error("unknown_command");return;}
 if(running||busy){error("stop_before_config_or_start");return;}
 long f=freq,m=mode,p=power,l=length,in=interval,j=jitter,c=100,d=1000,sd=random_seed,bc=burst_count,bg=burst_gap_us,he=hop_every;unsigned seen=0;
 uint16_t hh[16];unsigned hc=hop_count,pl=pattern_len;uint8_t pp[244];memcpy(hh,hops,sizeof hh);memcpy(pp,pattern,sizeof pp);
 for(char *t=strtok(line+(config?7:6)," ");t;t=strtok(NULL," ")){
  char *eq=strchr(t,'=');long n=0;if(!eq){error("expected_key_value");return;}*eq++=0;unsigned bit=0;
  if(config&&!strcmp(t,"hop_list")){bit=64;if(!parse_hops(eq,hh,&hc)){error("invalid_hop_list");return;}}
  else if(config&&!strcmp(t,"payload_hex")){bit=128;pl=0;if(strcmp(eq,"off")){size_t z=strlen(eq);if(!z||(z&1)||z>488){error("invalid_payload_hex");return;}for(unsigned k=0;k<z;k+=2){int a=hexval(eq[k]),b=hexval(eq[k+1]);if(a<0||b<0){error("invalid_payload_hex");return;}pp[pl++]=(a<<4)|b;}}}
  else {
   if(!parse_num(eq,&n)){error("invalid_number");return;}
   if(config){if(!strcmp(t,"frequency_mhz")){f=n;bit=1;}else if(!strcmp(t,"mode_mbps")){m=n;bit=2;}else if(!strcmp(t,"power_dbm")){p=n;bit=4;}else if(!strcmp(t,"payload_len")||!strcmp(t,"length")){l=n;bit=8;}else if(!strcmp(t,"interval_us")){in=n;bit=16;}else if(!strcmp(t,"jitter_us")){j=n;bit=32;}else if(!strcmp(t,"seed")){sd=n;bit=256;}else if(!strcmp(t,"burst_count")){bc=n;bit=512;}else if(!strcmp(t,"burst_gap_us")){bg=n;bit=1024;}else if(!strcmp(t,"hop_every")){he=n;bit=2048;}}
   else{if(!strcmp(t,"count")){c=n;bit=1;}else if(!strcmp(t,"duration_ms")){d=n;bit=2;}}
  }
  if(!bit||(seen&bit)){error("unknown_or_duplicate_key");return;}seen|=bit;
 }
 if(config){if(!seen||f<2402||f>2480||(m!=1&&m!=2)||(p!=-40&&p!=-20&&p!=-16&&p!=-12&&p!=-8&&p!=-4&&p!=0)||l<8||l>252||in<1000||in<(l+10)*8/m+300||in>1000000||j<0||j>in/2||sd<1||sd>2000000000||bc<0||bc>20000||bg<0||bg>1000000||he<1||he>20000||pl>(unsigned)(l-8)){error("config_out_of_range");return;}
 freq=f;mode=m;power=p;length=l;interval=in;jitter=j;random_seed=sd;burst_count=bc;burst_gap_us=bg;hop_every=he;hop_count=hc;pattern_len=pl;memcpy(hops,hh,sizeof hh);memcpy(pattern,pp,sizeof pp);active_freq=freq;status();return;}
 if(seen!=3||c<0||c>20000||d<1||d>60000){error("require_count_0_20000_and_duration_ms_1_60000");return;}
 if(!tud_cdc_connected()){error("cdc_not_connected");return;}
 NRF_RADIO->POWER=1;NRF_RADIO->MODE=mode==1?RADIO_MODE_MODE_Nrf_1Mbit:RADIO_MODE_MODE_Nrf_2Mbit;
 NRF_RADIO->FREQUENCY=freq-2400;NRF_RADIO->TXPOWER=(uint32_t)power;
 NRF_RADIO->PCNF0=8;NRF_RADIO->PCNF1=(252<<RADIO_PCNF1_MAXLEN_Pos)|(4<<RADIO_PCNF1_BALEN_Pos);
 NRF_RADIO->BASE0=0x89abcdef;NRF_RADIO->PREFIX0=0xc3;NRF_RADIO->TXADDRESS=0;NRF_RADIO->RXADDRESSES=0;
 NRF_RADIO->CRCCNF=2;NRF_RADIO->CRCINIT=0xffff;NRF_RADIO->CRCPOLY=0x11021;
 NRF_RADIO->PACKETPTR=(uint32_t)packet;NRF_RADIO->SHORTS=RADIO_SHORTS_READY_START_Msk|RADIO_SHORTS_END_DISABLE_Msk;
 attempted=completed=errors=last_end_us=elapsed_us=first_end_us=completion_min_us=completion_max_us=completion_total_us=0;count_limit=c?c:20000;start_us=now_us();
 schedule=(schedule_t){.next=start_us,.interval=interval,.jitter=jitter,.random=random_seed,.burst_count=burst_count,.burst_gap=burst_gap_us};
 end_us=start_us+d*1000;running=true;status();
}
static void radio_task(void){
 uint32_t n=now_us();
 if(busy&&NRF_RADIO->EVENTS_END)record_completion(n);
 if(!running)return;
 if(!tud_mounted()||!tud_cdc_connected()||(int32_t)(n-end_us)>=0){radio_stop();return;}
 if(busy&&n-tx_us>10000){errors++;radio_stop();return;}
 if(attempted>=count_limit){if(!busy)radio_stop();return;}
 uint32_t slot,due=schedule.next;
 if(!schedule_step(&schedule,n,!busy&&NRF_RADIO->STATE==RADIO_STATE_STATE_Disabled,&slot))return;
 active_freq=hop_count?hops[(slot/hop_every)%hop_count]:freq;
 NRF_RADIO->FREQUENCY=active_freq-2400;
 packet[0]=length;memcpy(packet+1,"RFTX",4);uint32_t seq=attempted;
 for(unsigned k=0;k<4;k++)packet[5+k]=(uint8_t)(seq>>(8*k));
 for(unsigned k=8;k<length;k++)packet[1+k]=pattern_len?pattern[(k-8)%pattern_len]:(uint8_t)(k+seq);
 NRF_RADIO->EVENTS_END=0;NRF_RADIO->EVENTS_DISABLED=0;NRF_RADIO->EVENTS_READY=0;
 attempted++;busy=true;tx_us=now_us();NRF_RADIO->TASKS_TXEN=1;
 schedule_record_launch(&schedule,tx_us-due);
}
int main(void){
 __disable_irq();SCB->VTOR=0x23000;
 for(unsigned i=0;i<8;i++){NVIC->ICER[i]=0xffffffff;NVIC->ICPR[i]=0xffffffff;}
 NRF_RADIO->TASKS_DISABLE=1;NRF_RADIO->SHORTS=0;NRF_RADIO->INTENCLR=0xffffffff;
 NRF_POWER->GPREGRET=0x57; /* Every unexpected reset enters the preserved recovery loader. */
 NRF_CLOCK->LFCLKSRC=0;NRF_CLOCK->TASKS_LFCLKSTART=1;
 NRF_WDT->CONFIG=1;NRF_WDT->CRV=5*32768;NRF_WDT->RREN=1;NRF_WDT->INTENSET=1;NVIC_EnableIRQ(WDT_IRQn);NRF_WDT->TASKS_START=1;
 NRF_TIMER2->MODE=TIMER_MODE_MODE_Timer;NRF_TIMER2->BITMODE=TIMER_BITMODE_BITMODE_32Bit;NRF_TIMER2->PRESCALER=4;NRF_TIMER2->TASKS_CLEAR=1;NRF_TIMER2->TASKS_START=1;
 SysTick_Config(64000);NVIC_SetPriority(USBD_IRQn,2);__enable_irq();tusb_init();
 bool detected=false,ready=false;
 for(;;){
  NRF_WDT->RR[0]=0x6e524635;
  uint32_t u=NRF_POWER->USBREGSTATUS;
  if((u&POWER_USBREGSTATUS_VBUSDETECT_Msk)&&!detected){tusb_hal_nrf_power_event(0);detected=true;}
  if(detected&&!ready&&(u&POWER_USBREGSTATUS_OUTPUTRDY_Msk)){tusb_hal_nrf_power_event(2);ready=true;}
  if(detected&&!(u&POWER_USBREGSTATUS_VBUSDETECT_Msk)){radio_stop();tusb_hal_nrf_power_event(1);detected=ready=false;}
  tud_task();radio_task();
  /* This legacy TinyUSB CDC driver does not drain TX on completion. */
  if(tud_cdc_connected())tud_cdc_write_flush();
  if(reset_pending&&(int32_t)(ms-reset_ms)>=0)reboot();
  /* Limit parsing per iteration so USB traffic cannot starve deadline checks. */
  for(unsigned budget=0;budget<64&&tud_cdc_available()&&tud_cdc_write_available()>=1900;budget++){
   char ch=(char)tud_cdc_read_char();if(ch=='\r')continue;
   if(ch=='\n'){line[line_n]=0;if(overflow)error("line_too_long");else if(line_n)command();line_n=0;overflow=false;}
   else if(line_n<sizeof(line)-1)line[line_n++]=ch;else overflow=true;
  }
 }
}
