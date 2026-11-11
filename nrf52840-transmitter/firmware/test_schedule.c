#include "schedule.h"
#include <assert.h>
#include <stdio.h>
int main(void){uint32_t slot; schedule_t s={.next=100,.interval=1000,.random=1};
 assert(!schedule_step(&s,99,true,&slot));assert(schedule_step(&s,100,true,&slot)&&slot==0);
 assert(!schedule_step(&s,1100,false,&slot));assert(s.missed==1);
 assert(schedule_step(&s,2110,true,&slot)&&slot==2);schedule_record_launch(&s,0);schedule_record_launch(&s,10);assert(s.late==1&&s.late_min==0&&s.late_max==10&&s.late_total==10);
 assert(!schedule_step(&s,6000,true,&slot));assert(s.missed==2);assert(s.next==4100);
 s=(schedule_t){.next=0xfffffff0,.interval=1000,.random=1};assert(schedule_step(&s,0xfffffff0,true,&slot));assert(schedule_step(&s,984,true,&slot));
 s=(schedule_t){.interval=1000,.random=1,.burst_count=2,.burst_gap=5000};assert(schedule_step(&s,0,true,&slot));assert(schedule_step(&s,1000,true,&slot));assert(s.next==7000);assert(!schedule_step(&s,2000,true,&slot));
 schedule_t a={.interval=1000,.jitter=400,.random=123},b=a;
 for(int i=0;i<20000;i++){uint32_t before=a.next;assert(schedule_step(&a,a.next,true,&slot));assert(schedule_step(&b,b.next,true,&slot));assert(a.next==b.next);assert(a.next-before>=600&&a.next-before<=1400);}
 uint32_t sum=UINT32_MAX-1;bool sat=false;saturating_add(&sum,2,&sat);assert(sat&&sum==UINT32_MAX);
 puts("schedule tests passed: due/missed/late, wrap, bursts, 20000 jitter slots, saturation");
}
