#include "source_trace.h"
_Static_assert(sizeof(trace_record)==20,"trace RAM budget changed");
void trace_reset(source_trace *t,bool enabled){t->count=t->ended=t->aborted=0;t->enabled=enabled;t->overflow=false;}
void trace_launch(source_trace *t,uint32_t sequence,uint32_t slot,uint16_t freq,uint32_t tx){
 if(!t->enabled)return;
 if(t->count>=TRACE_CAPACITY){t->overflow=true;return;}
 t->records[t->count++]=(trace_record){sequence,slot,tx,0,freq,TRACE_PENDING};
}
void trace_finish(source_trace *t,bool ended,uint32_t end){
 if(!t->enabled||!t->count||t->overflow)return;
 trace_record *r=&t->records[t->count-1];if(r->state!=TRACE_PENDING)return;
 r->state=ended?TRACE_END:TRACE_ABORTED;r->end_us=ended?end:0;
 if(ended)t->ended++;else t->aborted++;
}
bool trace_complete(const source_trace *t,uint32_t attempted,uint32_t completed){
 return t->enabled&&!t->overflow&&t->count==attempted&&t->ended==completed&&t->ended+t->aborted==t->count;
}
