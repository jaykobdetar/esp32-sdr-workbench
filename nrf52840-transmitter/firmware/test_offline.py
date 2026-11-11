#!/usr/bin/env python3
"""Compile actual parser/status source fragments into a host-only test harness."""

import subprocess
from pathlib import Path

Path('build').mkdir(exist_ok=True)
s = Path('main.c').read_text()
parser = s[s.index('static bool parse_num') : s.index(' if(seen!=3')] + '\n}\n'
status_start = s.index('static void status')
status = s[status_start : s.index('static void reboot(void){', status_start)]
prefix = """#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "schedule.h"
#define FW_VERSION "0.2.1"
static uint32_t ms,freq=2402,mode=1,length=32,interval=10000,jitter=0,random_seed=1,burst_count=0,burst_gap_us=0,hop_every=1,active_freq=2402;
static int power=-20;static bool running,busy,reset_pending;
static uint32_t first_end_us,completion_min_us,completion_max_us,completion_total_us,attempted,completed,errors,start_us,last_end_us,reset_ms,elapsed_us;
static schedule_t schedule;static uint16_t hops[16];static uint32_t hop_count,pattern_len;static uint8_t pattern[244];static char line[1024];
static unsigned error_count;static char output[2048];
static struct {uint32_t STATE;} mock_radio;
#define NRF_RADIO (&mock_radio)
#define RADIO_STATE_STATE_Disabled 0
static void diagnostic_device(char *out,size_t n){snprintf(out,n,"device_mock");}
static uint32_t now_us(void){return 10;}
static void radio_stop(void){running=false;}
static void reply(const char*s){assert(strlen(s)<1900);strcpy(output,s);}
static void error(const char*s){(void)s;error_count++;}
"""
tests = """static void run(const char*s){strcpy(line,s);command();}
int main(void){
 run("CONFIG length=32 payload_hex=deadbeef hop_list=2402,2440,2480 hop_every=3 seed=123 burst_count=5 burst_gap_us=5000");
 assert(!error_count&&pattern_len==4&&pattern[0]==0xde&&pattern[3]==0xef&&hop_count==3&&hops[2]==2480&&random_seed==123&&burst_count==5);
 run("CONFIG frequency_mhz=2490 seed=1");assert(error_count==1&&freq==2402&&random_seed==123);
 run("CONFIG hop_list=2402, seed=2");assert(error_count==2&&random_seed==123&&hop_count==3);
 run("CONFIG length=8");assert(error_count==3&&length==32);
 run("CONFIG payload_hex=off hop_list=off length=8");assert(error_count==3&&pattern_len==0&&hop_count==0&&length==8);
 run("CONFIG length=8 payload_len=8");assert(error_count==4);
 run("CONFIG seed=0");assert(error_count==5&&random_seed==123);
 run("CONFIG mode_mbps=0");assert(error_count==6&&mode==1);
 run("CONFIG payload_hex=gg");assert(error_count==7&&pattern_len==0);
 run("CONFIG hop_list=2402,2403,2404,2405,2406,2407,2408,2409,2410,2411,2412,2413,2414,2415,2416,2417");assert(error_count==7&&hop_count==16);
 run("CONFIG hop_list=2402,2403,2404,2405,2406,2407,2408,2409,2410,2411,2412,2413,2414,2415,2416,2417,2418");assert(error_count==8&&hop_count==16);
 pattern_len=244;memset(pattern,0xff,sizeof pattern);
 schedule.scheduled=schedule.late_total=schedule.late_max=schedule.late_min=UINT32_MAX;status();puts(output);
 running=true;unsigned before=error_count;run("DEVICE");assert(error_count==before+1);running=false;mock_radio.STATE=1;run("DEVICE");assert(error_count==before+2);mock_radio.STATE=0;run("DEVICE");assert(!strcmp(output,"device_mock"));
 puts("parser/status tests passed: atomic config, aliases, hex, hops, seed, numeric bounds, duplicate keys");
}
"""
Path('build/test_parser_generated.c').write_text(prefix + status + parser + tests)
subprocess.run(
    [
        'cc',
        '-std=c11',
        '-I.',
        '-fsanitize=undefined,address',
        'build/test_parser_generated.c',
        '-o',
        'build/test_parser',
    ],
    check=True,
)
subprocess.run(['build/test_parser'], check=True, env={'ASAN_OPTIONS': 'detect_leaks=0'})
