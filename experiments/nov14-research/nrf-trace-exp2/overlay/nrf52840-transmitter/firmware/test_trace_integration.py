"""Compile the actual completion/STOP implementation with fake peripherals."""
from pathlib import Path
import subprocess
s = Path('main.c').read_text()
code = s[s.index('static void record_completion'):s.index('static void reply')]
prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include "source_trace.h"
#include "schedule.h"
#include "stop_control.h"
static struct {uint32_t EVENTS_END,SHORTS,TASKS_DISABLE,STATE,POWER;} radio;
static struct {uint32_t CC[2];} timer;
static struct {uint32_t CHENCLR;} ppi;
#define NRF_RADIO (&radio)
#define NRF_TIMER2 (&timer)
#define NRF_PPI (&ppi)
#define RADIO_STATE_STATE_Disabled 0
#define __DSB() ((void)0)
static source_trace trace;
static schedule_t schedule;
static bool busy,running,rebooted;
static uint32_t tx_us,start_us,completed,first_end_us,completion_min_us,completion_max_us,completion_total_us,last_end_us,elapsed_us,errors,clock_us,inject;
static uint32_t now_us(void){if(inject&&clock_us==1001){radio.STATE=0;radio.EVENTS_END=1;timer.CC[1]=1001;}return clock_us++;}
'''
tests = r'''
static void reboot(void){rebooted=true;}
static void setup(void){
 trace_reset(&trace,true);trace_launch(&trace,0,9,2440,100);
 start_us=900;tx_us=1000;clock_us=1000;inject=0;busy=running=true;
 completed=errors=0;rebooted=false;radio.STATE=0;radio.EVENTS_END=0;timer.CC[1]=1050;
}
int main(void){
 setup();radio.EVENTS_END=1;radio_stop();assert(completed==1&&trace.records[0].end_us==150&&trace_complete(&trace,1,1));radio_stop();assert(completed==1&&trace.ended==1);
 setup();radio_stop();assert(!completed&&trace.aborted==1&&trace_complete(&trace,1,0));
 setup();radio.EVENTS_END=1;record_completion(1100);assert(trace.records[0].end_us==150&&last_end_us==200);radio_stop();assert(completed==1&&trace.ended==1);
 setup();radio.STATE=1;inject=1;radio_stop();assert(completed==1&&trace.records[0].end_us==101&&trace_complete(&trace,1,1));
 setup();radio.STATE=1;radio_stop();assert(rebooted&&errors==1&&!trace_complete(&trace,1,0)&&trace.records[0].state==TRACE_PENDING&&radio.POWER==0);
}
'''
Path('build').mkdir(exist_ok=True)
Path('build/test_trace_integration.c').write_text(prefix+code+tests)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined,address','-I.','build/test_trace_integration.c','source_trace.c','schedule.c','stop_control.c','-o','build/test_trace_integration'],check=True)
subprocess.run(['build/test_trace_integration'],check=True,env={'ASAN_OPTIONS':'detect_leaks=0'})
