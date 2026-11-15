#ifndef SOURCE_TRACE_H
#define SOURCE_TRACE_H
#include <stdint.h>
#include <stdbool.h>
#define TRACE_CAPACITY 4096u
#define TRACE_CHUNK 16u
enum { TRACE_PENDING=0, TRACE_END=1, TRACE_ABORTED=2 };
typedef struct { uint32_t sequence,slot,tx_us,end_us; uint16_t frequency_mhz,state; } trace_record;
typedef struct { trace_record records[TRACE_CAPACITY]; uint32_t count,ended,aborted; bool enabled,overflow; } source_trace;
void trace_reset(source_trace *t,bool enabled);
void trace_launch(source_trace *t,uint32_t sequence,uint32_t slot,uint16_t freq,uint32_t tx);
void trace_finish(source_trace *t,bool ended,uint32_t end);
bool trace_complete(const source_trace *t,uint32_t attempted,uint32_t completed);
#endif
