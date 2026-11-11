#include "schedule.h"
void saturating_add(uint32_t *sum,uint32_t value,bool *saturated){if(UINT32_MAX-*sum<value){*sum=UINT32_MAX;*saturated=true;}else *sum+=value;}
bool schedule_step(schedule_t *s,uint32_t now,bool available,uint32_t *slot){
 if((int32_t)(now-s->next)<0)return false;
 uint32_t due=s->next;*slot=s->scheduled++;
 s->random^=s->random<<13;s->random^=s->random>>17;s->random^=s->random<<5;
 int32_t j=s->jitter?(int32_t)(s->random%(2*s->jitter+1))-(int32_t)s->jitter:0;
 s->next=due+s->interval+j;
 if(s->burst_count&&s->scheduled%s->burst_count==0)s->next+=s->burst_gap;
 /* A slot whose successor is already due is expired, never burst catch up. */
 if(!available||(int32_t)(now-s->next)>=0){s->missed++;return false;}
 return true;
}
void schedule_record_launch(schedule_t *s,uint32_t lateness){
 s->launched++;
 if(lateness)s->late++;
 if(s->launched==1||lateness<s->late_min)s->late_min=lateness;
 if(lateness>s->late_max)s->late_max=lateness;
 saturating_add(&s->late_total,lateness,&s->saturated);
}
