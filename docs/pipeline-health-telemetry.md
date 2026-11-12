# Validation-only pipeline heap and stack telemetry

This instrumentation is opt-in with CMake `-DDETPIPE_HEALTH=ON`. Release builds
leave it OFF. It is not board validation and does not authorize flashing or RF
operation. The `CAPS` response adds `DETPIPEHEALTH` only in instrumented builds.
Legacy `DETPIPE1` framing, summary JSON, `DETPIPEMEM?`, retention, allocation
checks, RF ownership checks and scheduler yields are unchanged. An instrumented
image is a different artifact and its timing must not be pooled with release data.

`DETPIPEHEALTH?` returns one newline-terminated `DETPIPEHEALTH {JSON}` record.
The query is observational, does not clear retained data or reset measurements,
and uses bounded output chunks to respect the existing 256-byte reply buffer.
Disabled builds return `{"version":1,"enabled":false}`. Enabled builds return:

- `version`: 1; `enabled`: true.
- `caps`: numeric `MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT | MALLOC_CAP_DMA`.
  All reported heap bytes except the monitor preflight use this exact intersection.
- `run_id`: increments for each syntactically valid `DETPIPE1` attempt, including
  allocation failures. Starts at zero; unsigned counter eventually wraps.
- `run_valid`: true only after monitoring starts/stops successfully and the final
  summary is formatted, framed and accepted by the serial send function. It does
  not certify acquisition success: inspect the separate pipeline `status` too.
- `monitor_start_error`, `monitor_stop_error`: ESP-IDF status integers, zero on
  success. A start preflight rejection is `ESP_ERR_NO_MEM`. Stop is only attempted
  after successful start; zero stop status alone does not prove a stop happened.
- `free_now_bytes`, `largest_now_bytes`: current heap availability when queried.
- `free_before_bytes`: before clearing previous pipeline/legacy retained buffers.
- `free_allocated_bytes`: after all run allocations, before receiver preparation.
- `free_drained_bytes`: after final pending capture commit, before freeing raw copy.
- `free_after_bytes`: after raw-copy release, summary transmission and monitor stop.
  Retained pages remain allocated until clear or the next run.
- `run_min_bytes`: allocator-tracked **local** minimum, from monitor start before
  previous-buffer cleanup through final summary transmission. Captures transient
  lows between boundaries, including other tasks and monitor overhead.
- `lifetime_min_before_bytes`, `lifetime_min_after_bytes`: SDK lifetime heap lows
  before start and after stop has restored lifetime accounting, respectively.
- `stack_before_bytes`, `stack_after_bytes`: calling command task's **lifetime
  minimum free stack**, sampled before monitoring and after summary transmission.
  The pinned ESP-IDF `uxTaskGetStackHighWaterMark(NULL)` already returns **bytes**,
  unlike upstream FreeRTOS's word convention. No multiplication is applied. This
  is not a resettable run-local stack measurement, nor all-task stack telemetry.

Unmeasured values are JSON null, including before the first run or boundaries
not reached after allocation failure. Invalid command arguments leave the
previous record untouched. `DETPIPECLEAR` preserves the record, so compare its
fresh `free_now_bytes` to a baseline rather than to the saved `free_after_bytes`.
Allocation/guard failures stop monitoring, mark the record invalid and retain
existing cleanup behavior. Alias failures still avoid unsafe frees and require
reset. Acquisition failures drain the valid previous capture as before; telemetry
can be valid while pipeline status indicates that acquisition failed.

## SDK-specific limitations and overhead

Pinned SDK: `25fe69f946311abdaf9ad56591f25fedbc20ac98` (ESP-IDF 6.2 development).
`components/heap/include/esp_heap_caps.h` documents that minimum-free queries sum
**per-region minima**. Regions may reach lows at different times, so `run_min_bytes`
is a conservative lower bound on simultaneous total free heap, not an exact
instantaneous global minimum. Runtime-added heaps are excluded by this SDK API.
The measurement is allocator-tracked, not an approximation from boundary samples.

The monitor is global. This firmware is its sole caller; do not add concurrent
or nested monitor users. The pinned implementation does not reject nested starts
as its public comment suggests. Start allocates a small per-region bookkeeping
array with DEFAULT capabilities and asserts if that allocation fails. A 4096-byte
largest-DEFAULT-block preflight avoids obvious exhaustion but cannot reserve
memory against other tasks or eliminate this SDK assertion risk. The snapshot
allocation is removed by stop. It can affect measured lows and memory placement.

Heap traversal and stack scanning occur only at boundaries, never in the
RF-owned overlap callback or capture loop. The monitor's allocator tracking and
summary transmission are included in the local heap interval, while the reported
pipeline wall time retains its original narrower definition. Stack scan and
reporting overhead mean timing and stack numbers describe this instrumented
image. Health query output itself is outside the saved run interval. Stack
watermarks inspect untouched stack fill, not a proof against every stack bug.

## Host verification and future bench interpretation

`python firmware/tests/test_pipeline_health.py` runs integrated live pipeline
code with mocked SDK telemetry at O0/O2 under UBSan. It checks transient lows
missed by boundary samples, byte units, saved-vs-current readings, initial nulls,
run identity, allocation failures, monitor failures, low-memory preflight and
summary-send failure, then repeats the existing pipeline retention/failure suite.
The default-off original state suite runs separately. These are host mocks, not
measurements of an ESP32's heap, task stack, fragmentation or RF behavior.

For an attended, separately authorized board test, compare like-for-like cleared
heap snapshots, require monitor success and a valid summary, and record both
release and validation image hashes. Predeclared evaluation gates of 8192 free
DMA-capable bytes and 2048 free command-task stack bytes are screening thresholds,
not proven production requirements. This instrumentation does not measure every
task, simultaneous RF correctness, reset causes or thermal/power behavior.
