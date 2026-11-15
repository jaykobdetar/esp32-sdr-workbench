#pragma once
#include <stdint.h>
#include <stdbool.h>
/* Research-only, command task. Single nonblocking lease; no recursive calls.
 * Only cooperating PHY-mutex writers excluded. No universal analog epoch. */
typedef struct { uintptr_t handle; uint8_t before[152], after[152]; } paused_calibration;
bool paused_calibration_begin(paused_calibration *state);
bool paused_calibration_end(paused_calibration *state);
