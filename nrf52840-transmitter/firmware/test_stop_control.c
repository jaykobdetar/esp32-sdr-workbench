#include "stop_control.h"
#include <assert.h>
#include <stdio.h>
static bool end,off,requested;static unsigned polls,disabled_at,end_at,ticks,step;
static void disable(void){requested=true;}
static bool disabled(void){assert(requested);polls++;if(end_at&&polls==end_at)end=true;return disabled_at&&polls>=disabled_at;}
static bool pending(void){assert(polls>=disabled_at&&disabled_at);return end;}
static uint32_t now(void){unsigned v=ticks;ticks+=step;return v;}
static void hard_off(void){off=true;}
static const stop_control_ops ops={disable,disabled,pending,now,hard_off};
static void reset(void){end=off=requested=false;polls=end_at=ticks=0;disabled_at=3;step=1;}
int main(void){
 reset();end=true;assert(stop_control(&ops,true)==STOP_ACCOUNT_COMPLETION);assert(!off);
 reset();end_at=2;assert(stop_control(&ops,true)==STOP_ACCOUNT_COMPLETION);assert(!off);
 reset();assert(stop_control(&ops,true)==STOP_NO_COMPLETION);assert(!off);
 reset();end=true;assert(stop_control(&ops,false)==STOP_NO_COMPLETION);assert(!off);
 reset();disabled_at=0;assert(stop_control(&ops,true)==STOP_DISABLE_TIMEOUT);assert(off&&ticks<=1002);
 reset();disabled_at=0;step=0;assert(stop_control(&ops,true)==STOP_DISABLE_TIMEOUT);assert(off&&polls==4096);
 reset();ticks=0xfffffffe;end_at=2;assert(stop_control(&ops,true)==STOP_ACCOUNT_COMPLETION);
 puts("stop-control tests passed: END before/during stop, cancellation, already counted, timeout, stalled timer, wrap");
}
