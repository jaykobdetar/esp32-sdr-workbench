"""Actual terminal helper with a modeled UART FIFO/idle clock, not USB proof."""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('opt', ['-O0', '-O2'])
@pytest.mark.parametrize('tick_ms', [1, 10])
def test_wire_idle_trailer_bytes_and_faults(tmp_path, opt, tick_ms):
    source = (ROOT/'firmware/main/common/burst_serial.c').read_text()
    helper = source[source.index('bool burst_serial_finish('):source.index('static void serve_reply')]
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define BURST_SERIAL_UART 1
#define CONFIG_ESP_SDR_UART_ENABLED 1
#define UART_NUM_0 0
#define ESP_OK 0
#define pdMS_TO_TICKS(x) ((x)/TICK_MS)
static int active_port=1;
static uint64_t clock_us;
static unsigned pending, drains, gaps, writes, fail_drain, zero_write, negative_write, partial, gap_ready;
static unsigned char output[1024];
static size_t used;
static int64_t esp_timer_get_time(void){return clock_us++;}
static void vTaskDelay(unsigned n){
 clock_us+=(uint64_t)n*TICK_MS*1000;
 if(n==pdMS_TO_TICKS(20)+1){assert(!pending);gaps++;gap_ready=1;}
}
static int uart_wait_tx_done(int port,unsigned timeout){
 assert(port==0&&timeout==pdMS_TO_TICKS(100)+1);drains++;
 if(fail_drain==drains){clock_us+=(uint64_t)timeout*TICK_MS*1000;return -1;}
 clock_us+=pending*10;pending=0;return 0;
}
static int uart_tx_chars(int port,const char*p,size_t n){
 assert(port==0&&n<=32&&gap_ready);writes++;
 if(negative_write)return -1;
 if(zero_write)return 0;
 if(partial&&n>3)n=3;
 memcpy(output+used,p,n);used+=n;pending+=n;return (int)n;
}
static bool burst_serial_send(const void*p,size_t n){memcpy(output+used,p,n);used+=n;return true;}
'''
    tests = r'''
static void reset(void){clock_us=0;pending=drains=gaps=writes=fail_drain=zero_write=negative_write=partial=gap_ready=0;used=0;active_port=1;}
int main(void){
 unsigned char trailer[257];for(unsigned i=0;i<257;i++)trailer[i]=(unsigned char)i;
 // Every preceding wire offset and every allowed trailer length, including
 // exact USB packet-size multiples, with fragmented FIFO acceptance.
 for(unsigned offset=0;offset<64;offset++)for(unsigned n=0;n<=256;n++){
  reset();memset(output,0xa5,offset);used=offset;pending=offset;partial=offset%2;
  assert(burst_serial_finish(trailer,n));
  assert(used==offset+n&&!memcmp(output+offset,trailer,n));
  assert(!pending&&drains==1+(n+31)/32&&gaps==drains);
  assert(clock_us<1500000);
  // No padding, duplicate bytes, queued tail or stale error before next reply.
  assert(burst_serial_send("CLOCK 1\n",8));assert(!memcmp(output+offset+n,"CLOCK 1\n",8));
 }
 reset();assert(!burst_serial_finish(trailer,257));assert(!writes&&!drains);
 reset();assert(!burst_serial_finish(NULL,1));assert(!writes&&!drains);
 reset();fail_drain=1;pending=64;assert(!burst_serial_finish(trailer,8));assert(!used&&!writes);
 reset();fail_drain=2;assert(!burst_serial_finish(trailer,64));assert(used==32&&writes==1);
 reset();negative_write=1;assert(!burst_serial_finish(trailer,8));assert(!used&&writes==1);
 reset();zero_write=1;assert(!burst_serial_finish(trailer,8));assert(!used&&clock_us<1550000);
 reset();active_port=0;assert(burst_serial_finish(trailer,64));assert(used==64&&!drains&&!gaps);
}
'''
    path=tmp_path/'finish.c';path.write_text(harness+helper+tests)
    binary=tmp_path/'finish'
    subprocess.run(['cc','-std=c11',opt,f'-DTICK_MS={tick_ms}','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
