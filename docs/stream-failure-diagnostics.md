# Rejected stream diagnostics

A framing, CRC, sequence, accounting or calibration failure still rejects the
entire multi-receiver trial. Diagnostics cannot repair its coverage or promote a
successful peer into accepted union evidence. Existing saved trials cannot gain
these fields retroactively.

## Ordering cancellation

`run_stream` records host monotonic timestamps around each STOP write and flush,
the number of bytes reported written, its reason (shared cancellation observed
or primary-error cleanup), and any write/flush error. These timestamps bracket
host API operations, **not the instant the device received STOP**. The campaign
also brackets `Event.set()`. Error-detection timestamps, event timestamps and
per-receiver writes help distinguish the primary rejection from later peer
failures. They do not prove that cancellation caused a peer's corrupted bytes.

A STOP failure is attached to the primary stream exception, never substituted
for it. Completed peer summaries retain STOP timing too. Rejected attempts live
in `rejected_runs`, separate from accepted `runs`.

## Same-descriptor diagnosis

After every worker has finished and the rejection is saved, the multi-receiver
campaign attempts diagnostics on each failed receiver's **existing open serial
descriptor**. There is no competing stream reader at this point. It does not
close/reopen the port, change DTR/RTS, or change its timeouts. It skips diagnosis
if the descriptor is not verified open or existing read/write timeouts are not
finite and short enough (read <=0.25 seconds, write <=3 seconds).

A short tail (<=4096 bytes) is retained, followed by a bounded STOP/RELEASE and
unique SYNC nonce handshake. Only an exact nonce echo permits CLOCK and CALHASH
queries. The logical budget is five seconds; an already-started write can add
up to its configured three-second timeout. No diagnostic `flush`/`tcdrain` is
used because it has no portable deadline. The original protocol object remains
failed even when this separate diagnosis succeeds.

The clock is compared with the last validated record's device trigger. A
regression is evidence of a reset/clock discontinuity; no regression does not
prove absence of one. The logical stored calibration hash is compared with the
last valid campaign observation when available. This is not a comparison of
live radio coefficients or proof that calibration never changed between queries.
Diagnostic errors are retained without hiding the original failure.

## Optional Linux serial counters

The host attempts read-only `TIOCGICOUNT` before streaming and after a completed
stream, and during post-failure diagnosis. Supported drivers expose RX/TX,
framing, overrun, parity, break and other counters. These are snapshots, not a
complete end-to-end integrity proof. `unsupported` is explicit and must never
be interpreted as zero errors. No kernel, USB, termios or security settings are
changed to obtain counters.

Raw frame bytes, tails, descriptors/ports and calibration fingerprints are
private evidence. Publish only an intentional sanitized projection. A missing
multiple of 64 bytes, zeros, or `FF` patterns can guide controlled comparisons
but cannot identify a faulty cable, board, driver or firmware on their own.
