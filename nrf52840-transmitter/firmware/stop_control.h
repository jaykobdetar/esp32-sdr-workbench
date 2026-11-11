#ifndef STOP_CONTROL_H
#define STOP_CONTROL_H
#include <stdint.h>
#include <stdbool.h>
typedef struct {
 void (*request_disable)(void);
 bool (*is_disabled)(void);
 bool (*end_pending)(void);
 uint32_t (*now_us)(void);
 void (*hard_off)(void);
} stop_control_ops;
typedef enum { STOP_NO_COMPLETION, STOP_ACCOUNT_COMPLETION, STOP_DISABLE_TIMEOUT } stop_control_result;
stop_control_result stop_control(const stop_control_ops *ops,bool tracked_busy);
#endif
