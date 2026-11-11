#include "stop_control.h"
stop_control_result stop_control(const stop_control_ops *ops,bool tracked_busy){
 /* Quiesce the peripheral BEFORE the final END observation. END may arrive
  * during disable, but cannot newly arrive from this TX after Disabled. */
 uint32_t start=ops->now_us();
 ops->request_disable();
 for(unsigned polls=0;polls<4096;polls++){
  if(ops->is_disabled())return tracked_busy&&ops->end_pending()?STOP_ACCOUNT_COMPLETION:STOP_NO_COMPLETION;
  if((uint32_t)(ops->now_us()-start)>=1000)break;
 }
 /* A timeout cannot establish packet completion. Force RF peripheral off;
  * caller records an error and resets into recovery, never reports success. */
 ops->hard_off();return STOP_DISABLE_TIMEOUT;
}
