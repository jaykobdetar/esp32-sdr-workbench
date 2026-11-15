# Compact versus legacy: controlled physical comparison

## Decision

**Choose compact for the experimental packet-result transport. It is demonstrably smaller and faster in this test, without a serialization/replay mismatch. Do not claim it improves actual packet recovery or continuous coverage, and do not promote the experimental firmware as the normal default on this evidence.**

Compact and legacy are two result formats of the **same exact firmware and decoder**, not two different RF detectors. Every physical capture contains different RF samples. All 480 returned results were individually checked against their retained original IQ, exact native replay and observed 192-bit known-payload/CRC reconstruction for the retained records. This proves the observed results agree with the decoder on their own samples; it does not prove the decoder found every packet in those samples.

## Locked test

Two physical ESP32 receivers tested sequentially, each 240 captures in 60 blocks. Five conditions: source OFF, fixed 2440 MHz at nominal 0 dBm, fixed −12 dBm, four-packet grouped bursts with 6000 us extra gap, and 2438/2440/2442 MHz hopping. Each cell has six adjacent compact/legacy block pairs per receiver, balanced three compact-first / three legacy-first orders and shuffled condition order, seed 20261114. Every block has four captures. Receiver settings remain 2440 MHz, 16 MS/s, 10-bit, hardware gain, LPF AUTO, BGPOLICY 2. Source stable 0.2.2, 2 Mbps, 16-byte numbered RFTX payload, 1000 us interval with 113 us jitter, matched pair seed. No physical movement, desktop/network changes, source firmware rewrite, merges or publication by this task.

Each source ON block had a hard 15-second/20,000-attempt limit, source-running status bracketing all four captures, and verified STOP/status afterward. No automatic retry/restart or outcome-selected tuning. Final completed-END counts include START-ack early packets, capture, processing, UART export and waiting. OFF denominators are null. Six pairs per cell gives limited uncertainty; captures within a block are not independent treatment assignments. All individual values, paired spreads and sample SD are retained, without a universal superiority p-value.

## Timing and size

|Measure, all 240 captures per mode|Compact|Legacy|
|---|---:|---:|
|Mean result wire bytes|696.34|2480.65|
|Mean firmware result-output time|70.110 ms|88.187 ms|
|Mean full audited capture time|937.371 ms|945.031 ms|
|Mean full-IQ output time|728.723 ms|728.731 ms|

Result bytes shrink 71.93%; result output improves 20.50% or 18.076 ms. Compact result output is faster in 60/60 matched block pairs. Full audited capture improves only 0.81% or 7.660 ms on average and is faster in 58/60 pairs. The two reversals remain in the evidence. These are measured intervals with variability, not worst-case bounds or an unaudited production-throughput estimate.

Full IQ export dominates. UART-tail pacing is also deliberate bridge-fault mitigation, not removed by compact formatting; see PACING-OBSERVATION.md. This campaign does not qualify a packet-only/no-IQ production client or removal of those safeguards.

## Packet observations, not conditional recall

|Condition, 48 captures per mode across both receivers|Compact source-consistent unique observations|Legacy|Compact completed source events|Legacy|
|---|---:|---:|---:|---:|
|Fixed 0 dBm|32|39|45175|45544|
|Fixed −12 dBm|21|21|45123|45512|
|Grouped bursts|12|13|18081|18237|
|Narrow hopping|17|18|45209|45576|

Totals: **82 compact versus 91 legacy**, all unique within their own source block. Receiver 0 was 39/39; receiver 1 was 43/52. Each accepted observation has a verified observed known payload/CRC and sequence within that block's completed range. There were zero out-of-completed-range records and zero output drops. Incomplete decoder hypotheses were 12 in each mode, not an attested count of missed source packets; busy-sync counters were zero.

Whole-source-block observed fractions are 82/153588=0.05339% compact and 91/154869=0.05876% legacy. These are low retained observations across all source-on dead time, **not** recall conditional on a packet intersecting a capture and **not** evidence that legacy or compact has a superior detector. The numerical legacy lead is reported, not hidden; this study does not establish reception superiority or non-inferiority.

All 96 source OFF captures returned zero records, a finite negative control only. They total about 98.28 ms of nominal retained sample time, not 96 seconds of continuous negative observation. Across all 480 captures, nominal retained duration is 0.4914 seconds over 461.978 seconds of the two sequential run-wall intervals, approximately 0.1064%. Nominal samples/rate and trigger-to-done timestamps do not establish calibrated RF sample-time coverage. No two-board simultaneous coverage union was tested. No 100%packet-capture or Quest-protocol claim is made.

Source sequence numbers restart at each START and are namespaced by block. Source-END counters do not independently attest emitted waveform bits or provide an END-to-IQ clock alignment. Hops follow scheduled slots; missedslots prohibit sequence-to-frequency inference. Nominal transmitter power is not measured received power. Full symbol-support qualification remains unevaluated, as explicitly disclosed by the frozen verifier.

## Integrity, stability and recovery

Both campaigns passed all 240 captures/board, 120 blocks total. All 480 frames matched native replay, with clean schema 3 transport journals, retention DROP/RELEASE, one stable boot and generations 1..240 per board. Calibration hashes stayed constant within each candidate run; 243 readbacks per board were checked. Independent capture and safety reviews checked all 4,390 files per run, source journals, original configuration restoration and closed descriptors. No failures, dropped output records, wrong-source sequence range or output corruption were omitted.

Before each install, each board's MAC/USB identity, distinct app partition (receiver 0: 0x10000, receiver 1: 0x100000), current exact v9 bytes, fresh full 4 MiB backup, recovery image and protected ranges were verified. Only app bytes were written. NVS/calibration regions were preserved by the flash operations; stored calibration hashes can change across SDK boots, so cross-boot equality was not falsely asserted or forced by restoring old NVS.

**Final state:** both boards restored to exact v9 application SHA256 8a8b9036a012d80017d05dd494acf8080d825f4b2149d587c70d7f778ee3b2b5, protected-region verification passed, exact VERSION and normal raw 256-sample CRC/settings/RELEASE checks passed. Source remains unchanged 0.2.2, healthy / errors 0 / OFF with its original settings before close. All descriptors and experiment processes closed, hardware ownership released. No default promotion, PR update, merge or publication occurred during the measurement campaign; this document is a later publication.

## Exact artifacts and reproduction

- Candidate application SHA256 fc629ff663647f3e27c4b9494ef78e220ce74ac46cf5137ac8362edf3a73bea5, 722,144 bytes, variant esp32-paused-extract-compact-research-v2, build 2026-11-14T16:18:56Z. Same image for both result modes.
- Runner SHA256 3185941015e03462315bf658fc5a8531317a9bffb3b4597bc9b2e5ad2044d973; SOURCE-PINS SHA256 4a9883c5a908283d98cf4f6d5e3697584a6a512fffb9667eab94bf93b795f7a4. Locked schedule and 13 small tests preserved with independent source review.
- Frozen host manifest SHA256 0ea4d1c63a756a941293097edc7218dbc7a52d3cfeed31ed74b10ee0eacb3d44, 57 files; no decoder/host acceptance changes between runs.
- Per-board originals: runs/rx0 and runs/rx1. Each FILES.json binds every completed evidence file. Source commands include exact raw TX/RX JSON and host times; every capture includes original result/IQ, collector transcript and bounded adapter journal.
- Independent scoring outputs: [private-source-path] and rx1-results. Exactly one additional saved native replay per capture, no extra physical captures.
- SOURCE-PINS, PREPARATION-SHA256SUMS, independent-safety-rx0/rx1, final-recovery-review.md and combined-summary.json retain detailed provenance and limitations. summarize.py only aggregates completed saved audits; it does not execute hardware or re-decode IQ.
- Live invocation was the reviewed runner with --execute --receiver 0 then --receiver 1, scientific Python 3.14.7 and numerical threads limited to 1. Both one-shot output directories are intentionally non-reusable. Reproduction on hardware requires a newly reviewed output namespace and the same recovery/identity/source safety gates, not blindly rerunning completed directories.

This is a sanitized public report. The original private package contains raw ambient IQ, device identifiers and recovery/calibration flash backups, which are deliberately excluded here. Published numerical projections cannot independently reproduce RF decoding without those private samples. The sensible next optimization target is reducing full-IQ/audit export and safe protocol overhead while preserving recovery and evidence, not claiming that serialization alone solved reception.
