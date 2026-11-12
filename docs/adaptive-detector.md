# Adaptive detector and bounded candidate crops

The current source variant is **esp32-pipeline-adaptive-q16-v7**, identifying the
tie-retention fix, read-only calibration fingerprint query and optional default-off
health instrumentation, with fail-closed NVS startup and strict SPEC parsing added in v5, serial NUL rejection in v6, and the runtime background-rule selector in v7. V7 has been compiled and host-tested only; it has not been installed on a board. This is distinct from the
unchanged released-v3 binary tested during the [adaptive evaluation](evidence/adaptive-evaluation/evaluation-report.md).
Only the separate instrumented, tie-fixed candidate received the boundary matrix
and 30-minute soak. The source publication is not a newly validated release image.
No packet-recall, distance calibration, improved sensitivity or retained-packet
advantage over v2 was established. The verified v2 application was restored; stored
PHY calibration changed during the campaign with unknown timing/cause.

## Exact reference and background policy

`python -m sdr_research.detector_model --policy 2 capture1.sigmf-meta capture2.sigmf-meta`
replays files in the supplied order, prints JSON, and never opens a serial port.
It requires original transport-CRC-validated 10-bit CAP20 cf32 recordings. The
adapter restores signed ADC components using real×512 and −imaginary×512, rejects
noninteger/nonfinite/out-of-range values and 8-bit inputs, and reconstructs the
20 significant raw bits. Q inversion and high metadata bits do not affect energy.

The model matches both C energy kernels: complete 64-sample blocks, signed 10-bit
samples, complex mean removal, integer truncation per block and across blocks,
and ignored partial tail. Policy 1 preserves the historical integer background
and positive latch for comparisons. Policy 2 uses Q16 ADC²: 16-capture warmup,
then compare against the previous background and update on **every** capture,
with 1/64 weight on negatives and 1/256 on positives. The floor is 1/65536 ADC²,
not 1 ADC². Scores saturate at UINT32_MAX. The energy kernel itself still returns
integer ADC², so Q16 improves temporal estimation, not ADC resolution.

The reference and firmware agree under UBSan, including extremes and thousands
of transitions. A sustained synthetic mean/peak step from 2 to 34 ADC² stops
flagging after adaptation; the historical model remains latched. This synthetic
check does not select an optimal time constant or prove improved RF detection.

Saved buffers generally omit intervening captures. Replaying them initializes a
new warmup and **does not reconstruct** the original online run. The CLI rejects
mixed frequency/rate/known gain and rejects detector-selected IQ unless
`--allow-selected` is explicit. Selected buffers are biased; missing capture
chronology and AGC gain changes prevent candidate recall/false-positive estimates.

### Comparing the two rules on one image

Through v6 the firmware ran policy 2 only, so comparing it with the historical
rule meant flashing two images in sequence. The adaptive evaluation shows why that
is weak evidence: the same v2 image gave different source-on minus source-off
contrasts in different sessions, and the stored PHY calibration changed during the
campaign. Its largest difference, at manual gain 60 (+174.76 candidate windows/s
on v2 against +26.57 on v3), therefore cannot be attributed to the rule.

From v7, `BGPOLICY 1` or `BGPOLICY 2` selects the rule per run on the installed
image ([protocol](protocol.md#background-rule-selector-v7)). Runs can then be
interleaved (1, 2, 2, 1, ...) within one session, at one calibration state, with
the source on and off for each. From the host:

```sh
esp32-sdr record --port PORT --output NEW_PRIVATE_DIR --mode DETPIPE1 \
  --gain 60 --bandwidth-mhz 12 --run-ms 1000 --runs 1 --background-policy 1
```

or pass `background_policy=1` to `run_pipeline()` / `run_detection()`. Every
summary records the requested and read-back selection and the rule the firmware
reports. A reference-model simulation of a source present all run (frames in two
thirds of captures) predicts the rules differ only at moderate strength: for
bursts about 8 times the floor the legacy rule flags roughly 42% of source-bearing
captures and the Q16 rule roughly 28%, because the Q16 rule absorbs part of the
source into its background. Weaker bursts are missed and stronger ones caught by
both alike. `tests/test_detector_model.py` pins that prediction; it is a model
result, untested on hardware.

Policy 1 here is the historical *decision rule* running inside v7. It is checked
line for line against the archived v2 source by host tests, but duty, timing and
calibration behavior belong to v7, so results are not measurements of the
optimized-v2 binary.

## Multiple candidate retention, explicitly opt-in

`run_pipeline_candidates(...)` requests `PIPEKEEP 3`, verifies its readback,
retrieves all available CRC-checked crops and returns `(summary, captures)` with
the strongest first. `run_pipeline(...)` remains the legacy single full-capture
API by default. The headless recorder exposes the opt-in choice. No automatic
firmware update occurs.

The one-shot `PIPEKEEP 3` applies to the next valid `DETPIPE1` command, then resets
the pending setting to 1 even if allocation fails. Retained retrieval continues
to use the completed run's policy until its data is cleared/replaced. `PIPEKEEP?`
queries the **pending** setting. `PIPEKEEP 1` explicitly cancels a pending choice.

A maximum of three distinct positive captures are retained by highest score
(ties keep earlier captures after the published tie fix), each cropped to min(floor(N/8)×8,5120) samples.
The crop is centered around the first highest-energy 64-sample block and clamped
to input bounds with an eight-sample-aligned offset. This is a candidate policy,
not an RF classifier. `DETPIPEGET` retrieves the strongest; `DETPIPEGET 0`, `1`
or `2` retrieve occupied slots listed in the END summary. All use the existing
`DATA samples crc32 capture_us` header and CAP20 framing. Empty slots fail clearly.

At the full capture length, 3×5120×20/8 = **38,400 packed bytes**, below the original
40,950-byte full-capture buffer. Twelve bounded page allocations replace ten;
the immutable raw buffer is unchanged. Allocation/range/alias checks and safe
failure cleanup remain mandatory. Smaller requested acquisitions may require
more retention bytes than their legacy single-buffer equivalent. Memory arithmetic
is verified. The separate instrumented candidate passed its recorded heap/stack,
CRC and soak checks, with [SDK-specific limits](pipeline-health-telemetry.md).
These measurements do not validate every task or a new default-off release binary.

Each 5120-sample crop lasts 320 µs at 16 MS/s, 128 µs at 40 MS/s, or 64 µs at
80 MS/s. Only the 16 MS/s duration can contain the known 292 µs frame. Peak
position or boundary truncation can still cut a packet; even at 16 MS/s the crop
selection **does not guarantee** containment. The independent synthetic alignment sweep in the evaluation report demonstrates
shape-dependent truncation; it is not general packet recall.

## Gain and timing semantics

Additive END fields identify background policy/Q16, the raw `RX_GAIN` register
at run start and end, requested manual gain index, hardware-AGC mode, first/last
successful acquisition trigger times, and retained generation/trigger time.
Candidate descriptors include slot, sample count, sample offset, generation,
score, capture latency and original acquisition trigger time.

Trigger values are **device monotonic microseconds sampled immediately before
the dump-trigger register write**. They are not UTC, synchronized between radios,
calibrated sample-clock time or packet arrival time. Crop offset/sample rate is
only nominal timing. Gain snapshots do not capture every AGC transition or prove
which analog gain was active during every capture. The host request UTC timestamp
is preserved separately. Packet-recall measurement still needs source schedules,
calibrated timing and complete coverage information.

## Research status of three crops

Keep single full-capture retention as the default. Three-crop mode remains an
opt-in experiment, not a recommended packet-recovery improvement. The recorded
synthetic sweep fully contained a 4,672-sample burst in only 57/1,464 aligned
placements (3.893%) for uniform, first-block or last-block emphasized energy,
versus all placements with center-block emphasis. This is energy-shape-dependent
synthetic containment, not measured RF packet recall.

In the sequential stronger-source trial, mean nominal duty was 61.20% for v3
single versus 59.88% for v3 three. Mean accumulated retention-copy time per run
was 5.347 ms versus 25.304 ms (about 4.7 times), not a fixed cost per crop.
Replacement activity and other confounders prevent treating this as an isolated
causal benchmark. No retained full-packet advantage was established.

No further crop optimization or expanded three-crop RF campaign is warranted
without a new packet-linked design and predeclared containment objective. Preserve
the existing implementation/tests for reproducibility rather than silently
changing or deleting the experiment. See the [original evaluation](evidence/adaptive-evaluation/evaluation-report.md).
