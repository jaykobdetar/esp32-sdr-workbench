# Concurrent changing-response control

`scripts/serial_nonce_control.py` is acquisition-free and dry-run by default.
Use repeated `--port` arguments for up to four verified distinct receivers,
`--tx-serial`, and a new private `--output` directory. Add `--run` deliberately.
`--seconds` is bounded to 1–120; `--target-bytes-per-second` defaults to 25600
and is bounded to 1–50000 per receiver.

All receivers run concurrently after verified transmitter STOP. STOP/status is
checked again on exit. No RF capture, firmware flash, or transmitter START occurs.
Each batch contains 16 distinct numeric uint64 SYNC requests (maximum 416 bytes,
below the v9 8192-byte UART RX ring). Every exact newline-terminated reply must
match in order. Nonces increase by four, with distinct receiver lanes. Repeated
old valid replies fail, unlike constant CAPS replies. No CRC checks are bypassed.

Requests are paced by validated response bytes. Reported throughput uses actual
elapsed time, including a final response that may finish after the requested
interval (up to a two-second response deadline plus finite serial timeout).
A target is not a claim of equal DSTREAM load. Command parsing and bidirectional
traffic differ substantially. Startup/diagnostic time is excluded from measured
workload duration. Per-receiver start times need not match exactly.

A failed stream remains failed. Raw failed replies are bounded to 4096 bytes;
same-open-descriptor tail/nonce/CLOCK/calibration diagnostics run before close.
Outputs contain private identities and raw bytes; do not publish them verbatim.
The workload does not resynchronize after a mismatch. Other independent workers
finish their bounded trials, so a failed port cannot stop observation of peers.

Compare with isolated controls and measured DSTREAM failures. Passing does not
prove hardware health, a cable/port fix, gap-free RF coverage, or Quest support.

## Batch-reader revision

The initial physical 5-second and 120-second controls used the earlier
one-byte-at-a-time line reader. Their measured throughput must not be relabeled
as results from this revised reader. The current reader accumulates exactly the
expected 16-reply block using requests of at most 256 bytes under one deadline,
then compares every byte without newline normalization or recovery. It retains
failed blocks (bounded to 4096 bytes), expected/received lengths, and the first
mismatch offset; a matching truncated prefix reports its first missing offset.
A read error retains all bytes received before that error. This reduces Python
read-call overhead; target throughput still requires physical measurement.
