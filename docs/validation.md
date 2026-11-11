# Validation record and measurement limits

## Hardware campaign, 10 November 2026

The final tested variant was `esp32-pipeline-optimized-v2` on an ESP32-D0WD-V3 rev. 3.1, 4 MB flash, CP2102 UART at 1,000,000 baud. Firmware was built with ESP-IDF commit `25fe69f946311abdaf9ad56591f25fedbc20ac98` and Xtensa 16.1.0. The private final application SHA256 was `8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad`; rebuilding this public Git checkout can change revision metadata and binary hash, so this is provenance, not a promise of bit-identical output.

### Final-image checks

- 12 alternating detector trials with/without event retention.
- 24 raw sample-rate/precision/size combinations across 16/40/80 MS/s, 8/10-bit I/Q and 256/2048/8192/16380 samples.
- Three short-buffer fallback checks.
- Five live GUI runs, each producing a JSON summary and a CRC-valid SigMF recording.
- 24 × 5-second retained-event soak: 73,745 on-device captures, stable heap readings, successful retained and post-run raw CRC checks per run.
- Host/UI research suite: 260 tests passed.
- Final firmware research suite: 69 tests plus 70 subtests passed.
- Original and earlier DET1 v2 recovery checksums verified privately.

Not every on-device capture was transferred and CRC-checked. Every capture was subject to firmware aperture/status guards; retained data and post-run raw health checks were CRC-checked each run. These are distinct checks.

The complete campaign test corpus is deliberately not included in this compact public repository. Selected source-level tests remain for maintainability. Historical counts above describe the original campaign, not a claim that this small public suite contains all those tests.

## Method

Final A/B benchmark settings: 2440 MHz, nominal 16 MS/s, 16,380 samples, manual gain index 40, analog bandwidth setting 12 MHz, 4× adaptive energy threshold; three alternating 2-second trials per condition. Local wall time includes pipeline startup and final drain. Host duty includes commands and retained transfer; the soak's host-run figure excludes additional health checks between runs. GUI figures include recording and display-session gaps and used different gain defaults.

The sample-rate assumption is supported by capture-duration slopes, not an independent RF timing instrument. Short incomplete blocks and warmup are excluded from decision exposure. Local RF duty, analyzed duty and decision duty are therefore separate quantities.

## Additional correctness and negative-result work

- Eight exact energy kernels were compared with independent host and target references; the wider arithmetic corpus covered 1,089,622 cases with no mismatch. Selected full-buffer processing fell from about 1,257 µs to 848 µs.
- Exact CAP20 packing was checked against an independent bitstream reference across 80,881 size/tail/page/random/extreme cases, with sanitizer checks. Diagnostic packing time fell from approximately 2.64 ms to 0.82 ms. UART download remains much longer.
- Fused validation/copy was checked with target faults/canaries and host reconstruction. It is used only at the full validated size; smaller buffers take the guarded fallback.
- IRAM placement, several unroll/accumulator choices and less-frequent yielding did not improve the selected configuration. A fair later dual-core comparison regressed relative to the single-core pipeline.
- Gain-marker experiments showed late circular overwrite, but not safe live CPU access or coherent chronological streaming. Overwritten samples were not counted as coverage.
- A reproducible CP2102 ASCII END-message boundary stall was isolated with length controls. Conditional JSON whitespace avoids the specific boundary while leaving binary framing/CRC and timeouts unchanged.
- Intel AX200/BlueZ BLE OFF/ON tests, including counterbalanced phases, were inconclusive. Ambient activity and adaptive-threshold drift prevented a clear source-correlated event-rate result. Ordinary advertising hops channels and supplied no ground-truth packet counts or RF timestamps.

## Interpretation

This is a validated improvement in nominal finite-acquisition listening time, not proof of better sensitivity, identical detection probability, continuous IQ or an absolute hardware maximum. Faster sampling cadence changes observed RF windows and the wall-time behavior of the adaptive background even when arithmetic is exactly preserved. A stronger detector-quality claim requires an isolated, timed RF source. A new memory-ownership design needs independent validation before continuous-coverage claims would be warranted.

The screenshot is from the real final firmware session. It is included without raw captured IQ; it contains only the application window, generic serial port, RF settings, measurements and local relative recording paths. No device flash images, personal account data or credentials are included.

## Public-source packaging check

The selected viewer suite passed 147 tests after a clean installation into a fresh isolated Python environment. The installed `esp32-sdr --help` entry point also passed outside the checkout. This recheck did not access hardware or modify the installed device firmware. Firmware clean-build results are recorded in the build guide.

The combined selected public suite passed **153 tests plus 5 subtests** (147 viewer tests and 6 firmware tests plus 5 subtests). A clean original-ESP32 firmware build from the public tree also succeeded using the pinned SDK/toolchain. No rebuilt image was flashed for this publication pass; hardware numbers above remain those of the original final campaign image.

## Evidence publication check, 11 November 2026

The [curated evidence supplement](evidence/README.md) publishes all final A/B, soak and GUI summaries, historical DET1 trials, build identity, microbenchmarks and selected diagnostic sources. Offline recalculation reproduces the README numbers. Every sampled post-run soak heap reply is preserved; this is not a claim about unobserved transient heap behavior.

The supplement's local tests passed **156 viewer/evidence tests plus 6 firmware tests and 5 subtests**. The additional evidence tests cover integrity hashes, headline recalculation, an explicitly synthetic handshake replay, and endpoint-count handling. No new firmware build, serial query, hardware measurement or flashing was performed for this supplement. Earlier clean-build results above remain historical.

Endpoint analysis of the five screenshot-session retained captures found Q-channel endpoint occupancy of **0.20–12.76%**. The [published counts and method](evidence/gui/clipping-counts.json) support a clipping/saturation concern but do not identify its cause. Raw RF remains private. A complete raw handshake, matched manual-gain/AGC comparison, terminated-input floor and launcher-created screenshot were not available and are explicitly recorded as gaps.

## Maintenance pass, 11 November 2026

This pass changed host-side code, packaging and documentation only. **No firmware source was edited, no firmware was built, and no board was queried or flashed**, so every hardware number above still describes the original campaign image.

- Python sources were reformatted with ruff. The syntax tree of every file was compared before and after the formatter and was identical; the only hand edits were explicit `zip(strict=True)`, exception chaining and named field tuples for the spectrum frames.
- The viewer now reports the share of samples on an ADC endpoint code for each displayed capture, adds it to the event table, flags 1% or more as likely clipping, and stores the counts in SigMF metadata and in each detector-run summary. It uses the same convention as `scripts/count_sigmf_endpoints.py`.
- Each detector-run summary now records the requested gain mode, gain index, bandwidth, rate and sample count. This is the host's request, not a firmware readback of the gain hardware AGC selected.
- SciPy was removed from the dependencies because nothing imports it; the suite passes in an environment without it. The unused `validation` extra was dropped.
- CI was added for lint, format and both host suites. It does not build firmware.

The viewer and evidence suite passed **160 tests** and the firmware host suite **6 tests plus 5 subtests**. The GUI tests were run offscreen. The viewer changes have not been exercised against real hardware.

Analysis of the published summaries adds two detector limitations, now listed in the README: 5–48% of post-warmup captures were candidate-positive depending on the run, and the adaptive background does not update on positive captures. Under manual gain index 40 the recorded background was 2–34 ADC² units; under hardware AGC it was about 14,000–16,750, where the highest possible score is bounded by the converter's full scale. A matched manual-gain/AGC comparison and a terminated-input floor are still missing.
