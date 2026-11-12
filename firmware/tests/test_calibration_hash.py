"""Read-only NVS command contract, bounds and cleanup under UBSan."""

import subprocess
from pathlib import Path

import pytest

HEADER = Path(__file__).resolve().parents[1] / 'main/targets/esp32/calibration_hash.h'


@pytest.mark.parametrize('opt', ['-O0', '-O2'])
def test_calibration_hash_command(tmp_path, opt):
    (tmp_path / 'sha').mkdir()
    for name in ('nvs.h', 'esp_phy_init.h', 'sha/sha_parallel_engine.h'):
        (tmp_path / name).write_text('/* Test doubles are in the translation unit. */\n')
    source = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
typedef int esp_err_t;
typedef unsigned nvs_handle_t;
typedef struct {unsigned char opaque[1904];} esp_phy_calibration_data_t;
#define NVS_READONLY 0
#define ESP_OK 0
#define SHA2_256 2
static unsigned opens, closes, reads, allocations, frees, hashes;
static int open_error, size_error, read_error;
static bool fail_alloc, short_read;
static size_t stored_size=1904;
static char output[256];
static void reply(const char*fmt,...) {
 va_list ap;va_start(ap,fmt);int n=vsnprintf(output,sizeof(output),fmt,ap);va_end(ap);
 assert(n>0 && (size_t)n<sizeof(output));
}
static int nvs_open(const char*name,int mode,nvs_handle_t*h) {
 assert(!strcmp(name,"phy") && mode==NVS_READONLY);opens++;*h=9;return open_error;
}
static void nvs_close(nvs_handle_t h){assert(h==9);closes++;}
static int nvs_get_blob(nvs_handle_t h,const char*key,void*out,size_t*size) {
 assert(h==9 && !strcmp(key,"cal_data"));reads++;
 if(!out){*size=stored_size;return size_error;}
 assert(*size==1904);memset(out,42,*size);
 if(short_read)(*size)--;
 return read_error;
}
static void*test_malloc(size_t size){assert(size==1904);if(fail_alloc)return NULL;allocations++;return malloc(size);}
static void test_free(void*p){assert(p);frees++;free(p);}
static void esp_sha(int kind,const unsigned char*p,size_t n,unsigned char*out){
 assert(kind==SHA2_256 && n==1904);for(unsigned i=0;i<n;i++)assert(p[i]==42);
 hashes++;for(unsigned i=0;i<32;i++)out[i]=(unsigned char)i;
}
static int64_t esp_timer_get_time(void){return 123456789;}
#define malloc test_malloc
#define free test_free
#include "HEADER"
#undef malloc
#undef free
int main(void){
 assert(!calibration_hash_command("CALHASH? extra") && opens==0);
 assert(calibration_hash_command("CALHASH?"));
 assert(strstr(output,"\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\""));
 assert(strstr(output,"\"bytes\":1904") && strstr(output,"\"device_us\":123456789"));
 assert(opens==1 && closes==1 && reads==2 && allocations==frees && hashes==1);
 open_error=7;assert(calibration_hash_command("CALHASH?"));assert(!strcmp(output,"ERR calhash_open 7\n"));assert(closes==1);open_error=0;
 stored_size=0;assert(calibration_hash_command("CALHASH?"));assert(strstr(output,"ERR calhash_size"));
 stored_size=1000000;assert(calibration_hash_command("CALHASH?"));assert(allocations==1);
 stored_size=1904;size_error=8;assert(calibration_hash_command("CALHASH?"));assert(strstr(output,"ERR calhash_size 8"));size_error=0;
 fail_alloc=true;assert(calibration_hash_command("CALHASH?"));assert(strstr(output,"ERR calhash_memory"));fail_alloc=false;
 read_error=9;assert(calibration_hash_command("CALHASH?"));assert(strstr(output,"ERR calhash_read 9"));read_error=0;
 short_read=true;assert(calibration_hash_command("CALHASH?"));assert(strstr(output,"ERR calhash_read"));short_read=false;
 assert(calibration_hash_command("CALHASH?"));assert(hashes==2);
 assert(allocations==frees && opens==closes+1);
}
""".replace('HEADER', str(HEADER))
    cfile = tmp_path / 'test.c'
    cfile.write_text(source)
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
            '-I' + str(tmp_path),
            str(cfile),
            '-o',
            str(tmp_path / 'test'),
        ],
        check=True,
    )
    subprocess.run([str(tmp_path / 'test')], check=True)
