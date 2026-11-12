"""Compile the actual sparse pack/framing/multiplex helpers without hardware."""

from pathlib import Path

from test_dstream_c_review import compile_run

ROOT = Path(__file__).resolve().parents[1]


def test_sparse_actual_frame_multiplex(tmp_path):
    directory = ROOT / 'firmware/main/targets/esp32'
    src = (directory / 'detector_stream.h').read_text()
    src = src[src.index('#define DSTREAM_QUEUE') : src.index('static void dstream_commit')]
    src = src.replace(
        '#include "detector_stream_iq.h"',
        (directory / 'detector_stream_iq.h').read_text().replace('#pragma once', ''),
    )
    compile_run(
        tmp_path,
        r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#define MAX_SAMPLES 16380u
#define DETPIPE_MAX_PACKED 40950u
#define DETPIPE_PAGE_BYTES 4096u
#define DETPIPE_MAX_PAGES 12u
#define DETPIPE_ALLOC_CAPS 0
static uint8_t *detpipe_pages[12];
static size_t detpipe_page_sizes[12];
static unsigned detpipe_page_count,frequency_mhz=2440;
static uint8_t wire[150000];static unsigned used,budget=1000;
static bool pack_fail;
typedef struct {unsigned generation,n,observed_us;uint64_t trigger_device_us;uint32_t *copy;} detpipe_state_t;
static bool detpipe_safe_buffer(const void *p,size_t n){return p&&n;}
static void *heap_caps_malloc(size_t n,unsigned caps){(void)caps;return malloc(n);}
static void heap_caps_free(void *p){free(p);}
static uint32_t esp_rom_crc32_le(uint32_t c,const uint8_t *p,size_t n){while(n--)c=c*33+*p++;return c;}
static bool detpipe_pack(const uint32_t *p,unsigned n){(void)p;(void)n;if(pack_fail)return false;for(unsigned j=0;j<40950;j++)detpipe_pages[j/4096][j%4096]=j%251;return true;}
static uint32_t detpipe_crc(void){uint32_t c=0;for(unsigned j=0;j<detpipe_page_count;j++)c=esp_rom_crc32_le(c,detpipe_pages[j],detpipe_page_sizes[j]);return c;}
static unsigned burst_serial_try_send(const void *p,unsigned n){if(n>budget)n=budget;memcpy(wire+used,p,n);used+=n;budget-=n;return n;}
static bool burst_serial_send(const void *p,unsigned n){memcpy(wire+used,p,n);used+=n;return true;}
static int64_t esp_timer_get_time(void){return 0;}
static void vTaskDelay(unsigned n){(void)n;budget=1000;}
"""
        + src
        + r"""
int main(void){
 uint32_t raw[16380]={0};detpipe_state_t p={.generation=1024,.n=16380,.copy=raw,.trigger_device_us=123};
 assert(dstream_iq_allocate(raw));assert(detpipe_page_count==10);
 dstream_iq.every=1024;dstream_iq_snapshot(&p);assert(dstream_iq.produced==1);
 dstream_iq_snapshot(&p);assert(dstream_iq.skipped==1);
 budget=7;dstream_pump();assert(dstream_iq.cursor==7);
 dstream_enqueue((dstream_record_t){.sequence=1});
 while(dstream_iq.busy || dstream_count){budget=13;dstream_pump();}
 assert(dstream_iq.sent==1 && used%48==0);
 unsigned offset=0,timing=0;
 for(unsigned at=0;at<used;at+=48){uint32_t w[12];memcpy(w,wire+at,48);
 assert(w[11]==esp_rom_crc32_le(0,wire+at,44));
 if(w[0]==0x31565344){timing++;continue;}
 if(at==0){assert(w[0]==0x31495344);continue;}
 assert(w[0]==0x31515344 && w[1]==1024 && w[2]==offset);
 for(unsigned j=0;j<w[3];j++)assert(wire[at+16+j]==(offset+j)%251);
 offset+=w[3];}
 assert(offset==40950 && timing==1);
 pack_fail=true;p.generation=2048;dstream_iq_snapshot(&p);assert(dstream_iq.errors==1 && !dstream_iq.busy);
 for(unsigned j=0;j<detpipe_page_count;j++)free(detpipe_pages[j]);
 return 0;}
""",
    )
