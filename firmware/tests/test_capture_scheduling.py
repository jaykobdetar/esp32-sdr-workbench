"""Execute the production acquisition/clock waits with instrumented register mocks.

A cooperative delay with RF ownership, forced ADC, or filter overrides fails the
C test. This is a host invariant check, not a timing/performance measurement.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / 'main/targets/esp32'


@pytest.mark.parametrize('optimization', ['-O0', '-O2'])
def test_coarse_wait_precedes_acquisition_and_never_yields_with_rf_ownership(
    tmp_path, optimization
):
    receiver = (ROOT / 'receiver.c').read_text()
    acquisition = receiver.split('static bool acquire_iq_with_validation', 1)[1]
    acquisition = (
        'static bool acquire_iq_with_validation'
        + acquisition.split('\nstatic bool acquire_iq_with_work', 1)[0]
    )
    mocks = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <stdlib.h>
#define BIT(n) (1u << (n))
#define CAPACITY 16384u
#define MAX_SAMPLES (CAPACITY - 4)
#define SENTINEL 0xa55aa55au
#define DUMP_CTRL 0
#define DUMP_STATUS 1
#define DUMP_BYTES 2
#define ADC_CTRL 3
#define DPORT_IRAM_DRAM_AHB_SEL_REG 4
#define DPORT_MAC_DUMP_MODE_S 0
#define DPORT_MAC_DUMP_MODE_M 3u
#define ADC_ON_FORCE (BIT(9) | BIT(8))
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_DMA 4
static uint32_t registers[5], samples[CAPACITY];
static uint64_t now, capture_trigger_device_us, capture_pretrigger_max_us;
static unsigned acquisition_option, clear_option, delays;
static bool filter_overridden, stale;
static bool owns_rf(void){return (registers[DPORT_IRAM_DRAM_AHB_SEL_REG]&3)==3;}
static int64_t esp_timer_get_time(void){return now++;}
static void vTaskDelay(unsigned ticks){
 assert(!owns_rf() && !filter_overridden && !(registers[ADC_CTRL]&ADC_ON_FORCE));
 assert(ticks==1);delays++;now+=1000;
}
static void esp_rom_delay_us(unsigned us){now+=us;}
static void filter_apply(void){assert(!owns_rf());filter_overridden=true;now+=10;}
static void filter_restore(void){assert(!owns_rf());filter_overridden=false;}
static bool rx_recalibration_stale(void){return stale;}
static void prepare_rx(void){assert(!owns_rf());vTaskDelay(1);now+=3000;stale=false;}
static void clear_unroll8(uint32_t*p){for(unsigned i=0;i<CAPACITY;i++)p[i]=SENTINEL;}
static unsigned validate_split(const uint32_t*p,unsigned n){(void)p;(void)n;return UINT_MAX;}
static unsigned validate_aggregate(const uint32_t*p,unsigned n){return validate_split(p,n);}
static unsigned validate_unroll4(const uint32_t*p,unsigned n){return validate_split(p,n);}
static void reply(const char*fmt,...){(void)fmt;assert(!"Unexpected acquisition error");}
static void *heap_caps_malloc(size_t n,int flags){(void)flags;return malloc(n);}
static void heap_caps_free(void*p){free(p);}
#define REG_READ(address) registers[address]
#define REG_WRITE(address,value) (registers[address]=(value))
#define DPORT_REG_READ REG_READ
#define DPORT_REG_WRITE REG_WRITE
static void trigger(unsigned address,unsigned bits){
 assert(address==DUMP_CTRL && bits==BIT(19));assert(owns_rf()&&filter_overridden);
 assert((registers[ADC_CTRL]&ADC_ON_FORCE)==ADC_ON_FORCE);
 unsigned n=registers[DUMP_CTRL]&0xffff;
 for(unsigned i=0;i<n;i++)samples[i]=i;
 registers[DUMP_CTRL]|=bits|BIT(18);registers[DUMP_STATUS]=n;now+=1024;
}
#define REG_SET_BIT trigger
#define REG_CLR_BIT(address,bits) (registers[address]&=~(bits))
"""
    checks = r"""
int main(void){
 /* No schedule preserves ordinary immediate captures and causes no delay. */
 unsigned elapsed=0;
 assert(acquire_iq_with_validation(MAX_SAMPLES,0,0,&elapsed,NULL,NULL,NULL,NULL));
 assert(delays==0&&!owns_rf()&&!filter_overridden);
 const unsigned starts[]={10000,5000000},periods[]={0,1875,10000};
 for(unsigned s=0;s<2;s++)for(unsigned p=0;p<3;p++){
  uint64_t deadline=now+starts[s];dual_next=deadline;dual_period=periods[p];
  dual_period_ns=periods[p]*1000;dual_fraction_ns=0;unsigned before=delays;
  for(unsigned i=0;i<4;i++){
   assert(acquire_iq_with_validation(MAX_SAMPLES,0,0,&elapsed,NULL,NULL,NULL,NULL));
   assert(capture_trigger_device_us>=deadline);
   assert(!owns_rf()&&!filter_overridden&&!(registers[ADC_CTRL]&ADC_ON_FORCE));
   assert(capture_pretrigger_max_us<2000);
   if(!dual_period){assert(!dual_next);break;}
   deadline+=periods[p];assert(dual_next==deadline);
  }
  assert(delays>before);
 }
 /* Delayed setup still skips expired slots; it must not schedule another yield
  * after handoff, and the coarse wait is excluded from setup telemetry. */
 dual_next=now+10000;dual_period=1875;dual_period_ns=1875000;stale=true;
 unsigned skipped=dual_skipped;
 assert(acquire_iq_with_validation(MAX_SAMPLES,0,0,&elapsed,NULL,NULL,NULL,NULL));
 assert(dual_skipped>skipped && !owns_rf());
 return 0;
}
"""
    source = tmp_path / 'acquisition.c'
    source.write_text(mocks + f'\n#include "{ROOT / "dual_timing.h"}"\n' + acquisition + checks)
    binary = tmp_path / 'test'
    subprocess.run(
        [
            'cc',
            '-std=c11',
            optimization,
            '-Wall',
            '-Wextra',
            '-Werror',
            '-Wno-unused-function',
            '-Wno-unused-variable',
            '-fsanitize=undefined',
            '-fno-sanitize-recover=all',
            str(source),
            '-o',
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
