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
typedef struct {unsigned generation,n,observed_us;uint64_t trigger_device_us;uint32_t *copy;bool pending;} detpipe_state_t;
static bool detpipe_safe_buffer(const void *p,size_t n){return p&&n;}
static void *heap_caps_malloc(size_t n,unsigned caps){(void)caps;return malloc(n);}
static void heap_caps_free(void *p){free(p);}
static uint32_t esp_rom_crc32_le(uint32_t c,const uint8_t *p,size_t n){
 c=~c;while(n--){c^=*p++;for(unsigned i=0;i<8;i++)c=(c>>1)^((c&1)?0xedb88320u:0u);}return ~c;}

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
 uint32_t raw[16380]={0};detpipe_state_t p={.generation=1024,.n=16380,.copy=raw,.trigger_device_us=123,.pending=true};
 assert(dstream_iq_allocate(raw));assert(detpipe_page_count==10);
 dstream_iq.every=1024;dstream_iq_snapshot(&p);assert(dstream_iq.produced==1);
 dstream_iq_snapshot(&p);assert(dstream_iq.skipped==0); /* same generation is not retried */
 p.generation=2048;dstream_iq_snapshot(&p);assert(dstream_iq.skipped==1);
 budget=1000;dstream_pump();assert(used==0); /* not CRC ready or timing committed */
 for(unsigned i=0;i<19;i++){unsigned before=dstream_iq.crc_offset;dstream_iq_crc_step();assert(dstream_iq.crc_offset-before<=2048);}
 assert(!dstream_iq.crc_ready);dstream_iq_crc_step();assert(dstream_iq.crc_ready);
 assert(dstream_iq.packed_crc==detpipe_crc());assert(dstream_iq.packed_crc==3731264685u);
 budget=1000;dstream_pump();assert(used==0); /* CRC alone cannot publish metadata */
 dstream_iq.timing_committed=true;
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
 /* Saturated UART: spend the whole bounded 128-byte budget across frames. */
 used=0;p.generation=3072;dstream_iq_snapshot(&p);
 while(!dstream_iq.crc_ready)dstream_iq_crc_step();dstream_iq.timing_committed=true;
 budget=1000;dstream_pump();assert(used==128 && dstream_iq.cursor==32);
 dstream_enqueue((dstream_record_t){.sequence=2});
 budget=1000;dstream_pump();assert(used==256 && dstream_iq.cursor==16);
 uint32_t magic;memcpy(&magic,wire+144,4);assert(magic==0x31565344);
 /* No progress must preserve exact cursor/state and return immediately. */
 budget=0;dstream_pump();assert(used==256 && dstream_iq.cursor==16);
 budget=32;dstream_pump();assert(used==288 && dstream_iq.cursor==0);
 budget=0;dstream_pump();assert(used==288 && dstream_iq.cursor==0);
 budget=1;dstream_pump();assert(used==289 && dstream_iq.cursor==1);
 while(dstream_iq.busy || dstream_count){unsigned before=used;budget=1000;dstream_pump();assert(used-before<=128);}
 assert(dstream_iq.sent==2 && used==48*(1464+1));
 for(unsigned at=0;at<used;at+=48){uint32_t crc;memcpy(&crc,wire+at+44,4);assert(crc==esp_rom_crc32_le(0,wire+at,44));}
 pack_fail=true;p.generation=4096;dstream_iq_snapshot(&p);assert(dstream_iq.errors==1 && !dstream_iq.busy);
 /* STOP/final drain finishes pending CRC before publishing any frame. */
 pack_fail=false;p.generation=5120;dstream_iq_snapshot(&p);dstream_iq.timing_committed=true;
 assert(!dstream_iq.crc_ready);budget=1000;assert(dstream_drain());
 assert(dstream_iq.sent==3 && !dstream_iq.busy && dstream_iq.crc_ready);
 for(unsigned j=0;j<detpipe_page_count;j++)free(detpipe_pages[j]);
 return 0;}
""",
    )


def test_overlap_callback_cpu_only_order_and_final_commit_gating(tmp_path):
    source = (ROOT / 'firmware/main/targets/esp32/detector_stream.h').read_text()
    start = source.index('static void dstream_during_wait(')
    end = source.index('typedef struct { detpipe_state_t *p;', start)
    wrapper = source[start:end]
    for forbidden in (
        'samples',
        'REG_READ',
        'REG_WRITE',
        'burst_serial',
        'heap_caps',
        'vTaskDelay',
    ):
        assert forbidden not in wrapper
    compile_run(
        tmp_path,
        r"""
#include <assert.h>
typedef struct {int marker;} detpipe_state_t;
static int order;
static void detpipe_compute(void *p){assert(((detpipe_state_t*)p)->marker==7);assert(order++==0);}
static void dstream_iq_crc_step(void){assert(order++==1);}
static void dstream_iq_snapshot(detpipe_state_t *p){assert(p->marker==7);assert(order++==2);}
"""
        + wrapper
        + r"""
int main(void){detpipe_state_t p={7};dstream_during_wait(&p);assert(order==3);return 0;}
""",
    )
    commit = source[source.index('static void dstream_commit(') : start]
    assert commit.index('dstream_enqueue(') < commit.index('dstream_iq.timing_committed=true')
    assert 'dstream_iq.generation==p->generation' in commit
    assert 'dstream_iq_snapshot(p)' in commit  # Final capture/failure fallback.
