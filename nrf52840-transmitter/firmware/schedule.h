#ifndef RF_SCHEDULE_H
#define RF_SCHEDULE_H
#include <stdint.h>
#include <stdbool.h>
typedef struct {
 uint32_t next, interval, jitter, random, burst_count, burst_gap;
 uint32_t scheduled, missed, launched, late, late_min, late_max, late_total;
 bool saturated;
} schedule_t;
/* One due slot processed per call: no unbounded catch-up, no USB starvation. */
bool schedule_step(schedule_t *s, uint32_t now, bool available, uint32_t *slot);
void schedule_record_launch(schedule_t *s,uint32_t lateness);
void saturating_add(uint32_t *sum,uint32_t value,bool *saturated);
#endif
