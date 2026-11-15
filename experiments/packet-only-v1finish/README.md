# Bounded packet-only research candidate

**Opt-in prototype, not default firmware, continuous reception, or Quest support.**
This package reconstructs a separately named original-ESP32 app from the pinned
`core-bank-v9` research snapshot. It does not modify that snapshot or install
anything. No app binary, raw RF, device identity, calibration, or recovery image
is included. Physical results must be reported separately from these mock tests.

## Reconstruct and test without hardware

From the repository root (Python3.11+, Git, native C compiler):

```sh
python experiments/packet-only-v1finish/run_tests.py
python experiments/packet-only-v1finish/materialize.py /tmp/packet-only-candidate
```

Use a new destination. The existing `nov14-research/materialize.py` verifies
its frozen overlay and archives base commit
`d23ddddeaabee46d340caba60b038f39946cd534`; the new materializer then verifies and
applies `candidate.patch`, checking every changed source hash. A shallow CI
checkout must first make that pinned base object available, for example with
`git fetch origin d23ddddeaabee46d340caba60b038f39946cd534`.

Tests compile in a temporary directory with ASan/UBSan and never open serial
ports. LeakSanitizer is disabled for compatibility with ptrace-backed runners;
explicit mock allocation accounting still checks command cleanup. The suite
includes1,031 decoder cases, slot admission/accounting cases, and mocked command
bounds/allocation/capture/decode/STOP/send/cap-zero failure cases. It also checks
terminal wire lengths64..512bytes, maximum256-byte finish calls, exact byte order,
and incomplete-send failure without sequence advancement.

## Pinned build (no flashing)

Use ESP-IDF commit `25fe69f946311abdaf9ad56591f25fedbc20ac98`, its managed
Xtensa compiler `esp-16.1.0_20260609`, and a separate build directory. After
activating that SDK with its `export.sh`:

```sh
test "$(git -C "$IDF_PATH" rev-parse HEAD)" = 25fe69f946311abdaf9ad56591f25fedbc20ac98
idf.py -C /tmp/packet-only-candidate/firmware -B /tmp/packet-only-build \
  -DIDF_TARGET=esp32 -DSDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32 \
  -DPACKET_ONLY_PROBE=ON build
```

Variant: `esp32-packet-only-bounded-v1finish`. `PKTONLY` appears in CAPS only
when the opt-in flag is enabled. The source manifest includes one local app
hash/size as an artifact identity, not a claim of bit-identical binaries across
different build paths/timestamps. **Do not run generated generic flash commands.**
They can overwrite bootloader/table and assume an incompatible flash layout.
Any installation requires separate board-specific verified recovery, app-only
layout checks, and independent safety review.

## Command and strict wire contract

`PKTONLY?` returns capability information. `PKTONLY COUNT PERIOD_US CAP` accepts
COUNT1..128, PERIOD_US10000..100000, CAP0..16. It serializes:

1. Validated16380-sample capture at16MS/s (1.02375ms nominal aperture).
2. CPU-owned, bounded fixed-known-source decode. No live dump SRAM reads.
3. Packet metadata readout, without IQ transfer.

No decoder state crosses capture gaps. No queue or overlapping acquisition is
introduced. Workspace/results are internal non-aperture allocations, freed on
all command returns. Existing capture cleanup restores ownership and registers;
RX remains enabled while dump acquisition is disabled for decode. No new NVS
writes, persistent setting changes, or transmitter operations are introduced.

Run lines are `PONLY SEQUENCE BODY *CRC32\n`; CRC32 covers the exact ASCII bytes
before the space-asterisk suffix. Require consecutive wire sequence from0,
BEGIN, ordered WINDOW/PACKET records, matching counters and complete END.
There is no whitespace normalization, transport repair, ACK, or retransmission.

- BEGIN: requested count/period/cap, CPU frequency/core, planned start.
- WINDOW: scheduled slot, actual trigger, scheduled time, capture/decode duration,
  decoder cycles, accepted records, output-cap drops, busy/incomplete candidates.
- PACKET: slot, source sequence, address sample, phase0..7, polarity,
  fixed verified address `efcdab89c3`, observed16-byte payload and airCRC.
- END: status, completed captures, successful decodes, decode errors/status,
  capture faults, skipped/cancelled slots, packets, output drops, busy/incomplete
  counts, send failures, decode duration/cycle totals/maxima, inter-window gaps,
  and session duration measured **before terminal transmission**.

The decoder checks unwhitened2Mbps, length16, `RFTX`, sequence-dependent payload,
address and CRC16(poly1021/initFFFF, LSB-first address/length/payload, transmitted
CRC MSB-first). This is known-source packet extraction, not general GFSK decoding.
Host verification should independently reconstruct payload/airCRC and bind source
sequences to a complete specific source session. Packet observations across
windows are not unique source packets; repeated sequence numbers require dedupe.

Normal runs require status0, no capture/decode/send/integrity errors, exact record
counts, and `requested=completed+faults+skipped+cancelled`. Reject runs with lost
or malformed transport, missing END, or output drops for normal recall claims.
Status3 is a bounded STOP outcome, not a normal completed qualification run.
Output-cap drops count discarded decoder hypotheses, not deduplicated RF losses.
CAP0 intentionally tests loss accounting. No output queue exists.

Slots over50us late at admission are counted and skipped rather than caught up.
Capture setup follows admission; actual trigger lateness must be measured too.
The50us policy is not a qualified timing uncertainty. Inter-window gap sums omit
leading/trailing session time; use full host/source intervals for recall.

## Budget and limitations

The [initial physical controls](../../docs/evidence/packet-only-initial/REPORT.md)
measured 10.932–10.957 ms mean ON decoding for 16,380 samples (1.02375 ms),
about 10.7 times input real time. Capture plus decode alone limits one board to
about 8.5% duty before setup/readout/idle, or roughly 34% summed across four
ideal independent pipelines. These are compute bounds, not packet recall or
continuous coverage. The tested 20 ms slots have a nominal aperture fraction
of 5.12% per receiver before additional losses and source-window slack.

Earlier 6.244 ms / full-window arithmetic mixed benchmark assumptions and is
withdrawn: preserved benchmark capture sizes and algorithms differ. Use the
actual candidate measurements, not those historical timings, for its budget.
Reduced UART volume does not remove the compute bottleneck. Evaluate delivered
unique packets against complete source completed counts, not nominal coverage.

The initial128-byte INFO response exposed a boundary-sensitive delivery issue
in a separate capability-only check. This revision preserves exact wire bytes,
using the existing v9 paced finish helper for INFO and END. END uses at most
three256-byte calls; each helper call is bounded to1.5seconds. Intermediate
records remain fast. Mock boundary tests are not proof of physical delivery or
of a transport root cause. Include terminal readout in measured end-to-end
source denominators; a conservative host deadline may reject a late response.

Before any packet qualification, require source-OFF controls with zero false
matches, independently verified finite source sessions and aggregate completed-transmission
counters, finite source limits,
strict packet/counter checks, and board recovery. Aggregate counters are not an
event-level source trace and do not establish per-packet transmission times.
No physical acquisition success
is claimed by this package.

## Provenance and license

The full-rate integer decoder is preserved from the archived packet-bench
candidate; its interface is preserved from the DSP prototype. Their exact hashes
and archival relative provenance are in `manifest.json`, and full source changes
are in the patch. Original SPDX `GPL-3.0-or-later` notices are retained; this
research package follows the repository's GPL-3.0-or-later license. Fixtures are
synthetic tests, not captured private RF. The default firmware and frozen v9
snapshot are unchanged.
