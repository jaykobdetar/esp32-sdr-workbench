#include "source_trace.h"
#include <assert.h>
#include <stdio.h>
static source_trace t;
int main(void){
 trace_reset(&t,false);trace_launch(&t,0,5,2402,7);trace_finish(&t,true,19);assert(!t.count&&!trace_complete(&t,0,0));
 trace_reset(&t,true);trace_launch(&t,0,5,2440,7);trace_finish(&t,true,19);trace_finish(&t,true,21);
 trace_launch(&t,1,9,2480,30);assert(!trace_complete(&t,2,1));trace_finish(&t,false,99);
 assert(trace_complete(&t,2,1)&&t.records[0].slot==5&&t.records[1].sequence==1&&t.records[1].slot==9&&t.records[1].end_us==0&&t.records[1].state==TRACE_ABORTED&&t.records[0].end_us==19);
 assert(!trace_complete(&t,3,1)&&!trace_complete(&t,2,2));
 trace_reset(&t,true);for(unsigned i=0;i<TRACE_CAPACITY;i++){trace_launch(&t,i,3*i,2402,i);trace_finish(&t,true,i+1);}
 assert(trace_complete(&t,TRACE_CAPACITY,TRACE_CAPACITY));trace_launch(&t,4096,9000,2402,9000);assert(t.overflow&&!trace_complete(&t,4097,4096)&&t.count==TRACE_CAPACITY);
 trace_reset(&t,true);assert(trace_complete(&t,0,0));puts("source trace tests passed");
}
