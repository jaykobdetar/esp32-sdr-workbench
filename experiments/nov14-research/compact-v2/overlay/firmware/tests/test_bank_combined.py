"""Finite bank command lifecycle and failure cleanup, with hardware ownership mocks."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
TARGET = ROOT / 'main/targets/esp32'


@pytest.mark.parametrize('optimization', ['-O0', '-O2'])
def test_bank_lifecycle_and_fail_closed(tmp_path, optimization):
    header = '\n'.join(line for line in (TARGET / 'bank_bench.h').read_text().splitlines()
                       if not line.startswith(('#include', '#pragma')))
    mocks = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
#include "pipeline_energy3.h"
#include "bank_energy_clear.h"
#define BIT(n) (1u<<(n))
#define SENTINEL 0xa55aa55au
#define DUMP_CTRL 1
#define DUMP_STATUS 2
#define DUMP_BYTES 3
#define ADC_CTRL 4
#define ADC_ON_FORCE 0x300
#define DPORT_IRAM_DRAM_AHB_SEL_REG 5
#define DPORT_MAC_DUMP_MODE_M 0x60
#define DPORT_MAC_DUMP_MODE_S 5
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_DMA 4
static uint32_t storage[16384],*samples=storage,ctrl,own,adc,bytes;
static uint64_t clock_us=100000,trigger_time;
static unsigned triggers,allocs,frees,live_allocs,fail_alloc_at,filter_on,filter_off,corrupt_after,stale_after;
static bool dual_armed,dual_next,timeout_fault,stop_now,memory_fault;
static char message[256];
static uint64_t esp_timer_get_time(void){return clock_us+=50;}
static void esp_rom_delay_us(unsigned us){clock_us+=us;}
static uint32_t reg_read(unsigned r){
 if(r==DUMP_CTRL)return ctrl|(!timeout_fault && triggers && clock_us-trigger_time>=512?BIT(18):0);
 if(r==DUMP_STATUS)return 8188;
 if(r==DUMP_BYTES)return bytes;
 if(r==ADC_CTRL)return adc;
 if(r==DPORT_IRAM_DRAM_AHB_SEL_REG)return own;
 assert(false);return 0;
}
static void reg_write(unsigned r,uint32_t v){
 if(r==DUMP_CTRL)ctrl=v;
 else if(r==DUMP_BYTES)bytes=v;
 else if(r==ADC_CTRL)adc=v;
 else if(r==DPORT_IRAM_DRAM_AHB_SEL_REG)own=v;
 else assert(false);
}
static void reg_set(unsigned r,uint32_t v){
 assert(r==DUMP_CTRL);
 if(v==BIT(19)){
  unsigned mode=(own>>5)&3;assert(mode==1||mode==2);unsigned b=mode==1?1:0;
  for(unsigned i=0;i<8188;i++)samples[b*8192+i]=0x12345u+i;
  triggers++;trigger_time=clock_us;
  if(corrupt_after==triggers)samples[b*8192+8191]=1;
 }
 ctrl|=v;
}
#define REG_READ(r) reg_read(r)
#define REG_WRITE(r,v) reg_write(r,v)
#define REG_SET_BIT(r,v) reg_set(r,v)
#define REG_CLR_BIT(r,v) reg_write(r,reg_read(r)&~(v))
#define DPORT_REG_READ(r) reg_read(r)
#define DPORT_REG_WRITE(r,v) reg_write(r,v)
static void prepare_rx(void){assert(own==0);}
static bool rx_recalibration_stale(void){assert(own==0);return stale_after && triggers>=stale_after;}
static void filter_apply(void){assert(own==0);filter_on++;}
static void filter_restore(void){assert(own==0);filter_off++;}
static void bank_discard(void);
static void bank_release_other_retention(void){bank_discard();}
static unsigned heap_caps_get_free_size(unsigned c){(void)c;return 100000;}
static unsigned heap_caps_get_largest_free_block(unsigned c){(void)c;return 65536;}
static bool esp_ptr_in_dram(const void*p){return p!=NULL;}
static void *heap_caps_malloc(size_t n,unsigned caps){assert(own==0 && caps==7);allocs++;if(memory_fault||allocs==fail_alloc_at)return NULL;live_allocs++;return malloc(n);}
static void heap_caps_free(void*p){assert(own==0 && p && live_allocs);frees++;live_allocs--;free(p);}
static bool burst_serial_stop_requested(void){assert(own==0);return stop_now;}
static bool send_fault;static unsigned finish_calls;
static bool burst_serial_send(const void*p,size_t n){assert(own==0 && p && n);return !send_fault;}
static bool burst_serial_finish(const void*p,size_t n){finish_calls++;assert(own==0 && !ctrl && p && n==8);assert(!memcmp(p,"BANKEND\n",8));return true;}
static void reply(const char *fmt,...){assert(own==0);if(!strcmp(fmt,"BANKEND\n"))return;va_list a;va_start(a,fmt);vsnprintf(message,sizeof(message),fmt,a);va_end(a);}
static void vTaskDelay(unsigned n){assert(own==0);clock_us+=n*1000;}
static uint32_t esp_rom_crc32_le(uint32_t c,const void*p,size_t n){assert(p&&n);return c+123;}
typedef struct {unsigned observed,fallbacks;} dstream_idle_t;
static bool dstream_wake_begin(dstream_idle_t*s){(void)s;assert(own==0);return true;}
static void dstream_wake_end(dstream_idle_t*s){(void)s;assert(own==0);}
static void dstream_wake_service(dstream_idle_t*s){assert(own==0);s->observed++;}
'''
    checks = r'''
static void reset(void){
 if(bank_keep){bank_bench_command("BANKDROP");}
 assert(!live_allocs);allocs=frees=fail_alloc_at=0;
 clock_us=100000;ctrl=own=adc=bytes=triggers=filter_on=filter_off=corrupt_after=stale_after=0;
 timeout_fault=stop_now=memory_fault=send_fault=false;finish_calls=0;message[0]=0;
}
int main(void){
 assert(!bank_bench_command("UNRELATED"));
 const char *bad[]={"BANKRUN 0 0","BANKRUN 4294967304 0","BANKRUN -4294967288 0","BANKRUN +8 0","BANKRUN 8 4294967296","BANKRUN8 0","BANKRUN  8 0","BANKAT 8 0 18446744073709551616 800000","BANKAT 8 0 200000 4295767296","BANKRUN 1025 0","BANKRUN 8 2","BANKRUN 8 0 extra","BANKAT 8 0 500000 749999","BANKAT 8 0 100100 800000","BANKAT 8 0 3000000 800000","BANKAT 8 0 500000 800000 extra"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(*bad);i++){reset();assert(bank_bench_command(bad[i]));assert(!strcmp(message,"ERR bank_args\n"));assert(!triggers);}
 for(unsigned fused=0;fused<2;fused++){
  reset();char cmd[64];snprintf(cmd,sizeof(cmd),"BANKRUN 8 %u",fused);assert(bank_bench_command(cmd));assert(!strncmp(message,"BANKRUN 8 8188",14));assert(triggers==8 && bank_keep_valid && own==0 && filter_on==filter_off && !ctrl);
  assert(bank_bench_command("BANKGET"));assert(!bank_keep && !bank_keep_valid);assert(bank_bench_command("BANKGET"));assert(!strcmp(message,"ERR bank_empty\n"));
 }
 reset();assert(bank_bench_command("BANKAT 8 0 200000 800000"));assert(!strncmp(message,"BANKRUN 8 8188",14));assert(bank_keep_trigger>=205600 && triggers==8);bank_bench_command("BANKDROP");
 reset();corrupt_after=2;bank_bench_command("BANKRUN 8 0");assert(!strncmp(message,"ERR bank_run 2",14) && !bank_keep_valid && !bank_keep && own==0 && filter_on==filter_off && !ctrl);
 reset();stale_after=2;bank_bench_command("BANKRUN 8 0");assert(!strncmp(message,"ERR bank_run 5",14) && !bank_keep && triggers==2 && own==0 && !ctrl);
 reset();timeout_fault=true;bank_bench_command("BANKRUN 8 0");assert(!strncmp(message,"ERR bank_run 1",14) && !bank_keep && own==0 && filter_on==filter_off && !ctrl);
 reset();stop_now=true;bank_bench_command("BANKAT 8 0 200000 800000");assert(!strncmp(message,"ERR bank_run 3",14) && !triggers && !bank_keep && own==0 && !ctrl);
 reset();memory_fault=true;bank_bench_command("BANKRUN 8 0");assert(!strcmp(message,"ERR bank_memory\n") && !triggers);
 reset();fail_alloc_at=2;bank_bench_command("BANKRUN 8 0");assert(!strcmp(message,"ERR bank_memory\n") && !bank_keep && !live_allocs);
 reset();bank_bench_command("BANKRUN 8 0");assert(bank_keep_valid && live_allocs==1);bank_bench_command("BANKRUN 8 0");assert(bank_keep_valid && live_allocs==1);bank_bench_command("BANKDROP");assert(!live_allocs);
 reset();send_fault=true;bank_bench_command("BANKRUN 8 0");assert(!finish_calls && own==0 && !ctrl);
 reset();bank_bench_command("BANKRUN 8 0");assert(finish_calls==1);
 reset();bank_bench_command("BANKSTATUS?");assert(strstr(message,"\"retained_bytes\":0"));
 reset();return 0;
}
'''
    source = tmp_path / 'bank.c'
    source.write_text(mocks + header + checks)
    exe = tmp_path / 'bank'
    subprocess.run(['cc', '-std=c11', optimization, '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I', str(TARGET),
                    str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
