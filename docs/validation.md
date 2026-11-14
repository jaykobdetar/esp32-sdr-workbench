# Validation record and measurement limits

Latest: [streaming-v7 review validation](#streaming-v7-review-validation-13-november-2026).
Historical sections below retain their original build identities and test counts.

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
- The first CI run exposed a crash that predates this pass: with PySide6 6.12.0 on Python 3.10 or 3.11 the viewer aborts within seconds of starting (`Fatal Python error: none_dealloc`), because that PySide6 release over-releases `None` while pyqtgraph paints. Python 3.12 and newer are unaffected because `None` is immortal there, which is why the original Python 3.13 environment never showed it. PySide6 6.8.3, 6.9.3, 6.10.3 and 6.11.3 were checked on Python 3.10 and do not crash. The dependency is now constrained to PySide6 below 6.12 on Python older than 3.12.

The viewer and evidence suite passed **160 tests** on Python 3.10, 3.11, 3.12 and 3.13, and the firmware host suite **6 tests plus 5 subtests**. The GUI tests were run offscreen. The viewer changes have not been exercised against real hardware.

Analysis of the published summaries adds two detector limitations, now listed in the README: 5–48% of post-warmup captures were candidate-positive depending on the run, and the adaptive background does not update on positive captures. Under manual gain index 40 the recorded background was 2–34 ADC² units; under hardware AGC it was about 14,000–16,750, where the highest possible score is bounded by the converter's full scale. A matched manual-gain/AGC comparison and a terminated-input floor are still missing.

## Integration with the controlled-source publication, 11 November 2026

The maintenance pass above was combined with the [controlled nRF52840 validation](nrf-validation-summary.md) published the same day. Again no firmware source was edited, nothing was built or flashed and no device was opened.

- The fifteen campaign, analysis and test sources whose hashes are recorded in `rf-source-provenance.json` were left byte-for-byte unchanged and excluded from the formatter. A new test checks those hashes, and the hash of the retention patch, on every run. The other new Python files were formatted, with identical syntax trees before and after.
- Two GUI tests read run summaries while the worker was still rewriting them, which failed intermittently on Python 3.10. They now wait for the final rewrite. One of the two was an assertion added in the maintenance pass; the other predates it.
- `pytest` now collects all three host suites, and CI runs them together. The combined suite passed **238 tests plus 5 subtests** on Python 3.10 and 3.13, and both offline evidence verifiers passed.
- Index pages were added for `docs/` and `scripts/`.

The controlled-source data changes two statements made earlier in this record. A known transmitter now shows that part of the candidate rate is source-dependent, although roughly 193–202 candidate windows per second remained with the source off for the optimized image. A manual gain sweep now exists (index 60 usable, up to 10% clipping at index 80), but a matched hardware-AGC comparison and a terminated-input floor are still missing.

## Automated build and compatibility coverage

`firmware.yml` compiles the current ESP32 release with the exact pinned SDK and
the nRF52840 application with pinned vendor sources. The retention matrix entry
applies the archived patch to its original base, not to the evolving release.
No compile job accesses hardware. Transmitter C checks are collected by pytest.

`latest-dependencies.yml` runs weekly and on demand, deliberately installing the
latest Qt independently of production constraints. It runs the host suite and a
six-second real Qt/PyQtGraph paint loop in a subprocess. A crash fails the job;
success alone is not grounds to remove the production pin without review.

## Subsequent 19-item improvement pass

The [checklist](improvement-checklist.md) separates implemented software from remaining board/physical checks. All three firmware variants compile locally, but the new adaptive-Q16 image was not flashed. A separate [24-run matched AGC/manual trial](matched-gain-comparison.md) used unchanged installed optimized-v2 firmware, fixed −20 dBm source power and unmeasured bench geometry. Its transmitter was stopped and prior settings restored. The new launcher screenshot is explicitly synthetic UI evidence. At initial local completion, the new CI/schedule files had not yet been published or run. The owner then authorized publication with the [remaining-validation guide](remaining-validation-guide.md); remote results must be checked for the exact published commit.

## Rule selector and startup idle: v7 source, 12 November 2026

This pass changed firmware source, so it is identified as `esp32-pipeline-adaptive-q16-v7`. **It was compiled and host-tested only. Nothing was installed on a board, and no hardware number in this record describes v7.**

- **Selectable background rule.** `BGPOLICY 1|2` chooses the rule for the next DET1 or DETPIPE1 run; 2, the Q16 rule, remains the boot default. Rule 1 is the historical optimized-v2 rule. Host C tests under UndefinedBehaviorSanitizer step it alongside lines quoted from the archived v2 source and alongside the Python reference model over the same inputs, and all three agree exactly. Every END summary reports the rule that ran. The Python clients set the rule, read it back and verify the summary; without an explicit choice they select 2, so a legacy selection left by an earlier client is never inherited.
- **Why.** The adaptive evaluation could not separate the effect of the new rule from session drift and the calibration change, because the two rules lived in different images run in sequence. With the selector, runs under both rules can be interleaved within one session on one image.
- **Startup failure idles.** On NVS initialization failure v5 and v6 called `ESP_ERROR_CHECK`, which aborts; the archived release configuration reboots on panic with no delay, so the device would have restarted repeatedly. V7 repeats an `ERR nvs_init` notice every five seconds and does nothing else. Storage is preserved in both versions. The path is exercised by host fault injection only.
- **Documentation.** The README's status paragraph became a table of images and their board evidence.

The combined suite passed **605 tests plus 5 subtests** on Python 3.10 and 3.13; lint, format and the three offline evidence verifiers passed. CI results for the exact commit, including the pinned-SDK ESP32 compile, are the authority for whether v7 builds.

Before v7 results are used: flash it by the build guide's application-only route, confirm the variant, `BGPOLICY` in `CAPS`, and stack and heap headroom, then run rules 1 and 2 interleaved with the source on and off. Rule 1 inside v7 reproduces the v2 decision rule, not the v2 binary's timing or duty.

## V7 board result and the v8 selector fix, 12 November 2026

The [exact-release v7 evaluation](evidence/v7-evaluation/README.md) installed the v7 image and ran both background rules interleaved on it. Its findings change two things in this record.

- **The same-image comparison answered the open question.** At 0 dBm and manual gain 60 the two rules gave +205.0 and +190.5 source-associated candidate windows per second. The +174.76 against +26.57 seen across separately flashed images in the adaptive evaluation was therefore not caused by the background rule. One setting, 0 dBm at manual gain 40, nominally favored the Q16 rule (+114 windows/s, p = 0.0415, not surviving correction across six settings). Neither rule retained more CRC-valid packets. The reference-model prediction of a legacy advantage, recorded in the previous section's pass, was not borne out; the detector guide now says so.
- **The evaluation found a defect in the selector added in that pass.** `BGPOLICY1`, `BGPOLICY 4294967297` and `BGPOLICY -4294967295` were all accepted as rule 1, although the protocol document said malformed values are rejected. The parser used `sscanf` with `%u`, which tolerates a missing separator and wraps out-of-range numbers. The host tests of that pass covered `-1`, `0`, `3` and trailing text but not those cases. The Python clients never send such text, and the probes ran after the RF and soak campaign, so no published run was affected.

The source is now `esp32-pipeline-adaptive-q16-v8`. The selector accepts only the exact text `BGPOLICY 1` or `BGPOLICY 2`. The regression test uses the three board-reproduced inputs and seventeen other malformed forms, from both stored rules; it fails against the v7 parser and passes against the fix. **V8 is compiled and host-tested only, and differs from the evaluated v7 image in this parser alone.**

The same `sscanf` pattern remains in older commands, including `PIPEKERNEL`, `PIPEKEEP`, `PIPECOPY`, `ACQOPT`, `CLEAROPT`, `DET1`, `DETPIPE1`, `GAIN MANUAL`, `BANDWIDTH`, `LPF`, `FREQ`, `CAP` and `RXRUN`. They range-check the parsed value, so a wrapped number can be accepted only if it wraps into the valid range. They were left unchanged here because they are long-standing, board-validated paths shared with other targets.

The combined suite passed **610 tests plus 5 subtests** on Python 3.10 and 3.13; lint, format and the four offline evidence verifiers passed.

## Streaming v7 review validation, 13 November 2026

This records the fixes and validation following the PR #4 review of `688b5a4`.
The new firmware family is `esp32-dual-sparse-iq-experimental-v7` so that the
published v6 campaigns are not mistaken for measurements of this changed binary.

### Implemented

- **Capture-SRAM ownership:** all acquisition callers share a coarse scheduling
  wait before setup, ADC/filter overrides, or handing SRAM to the MAC. The final
  trigger wait contains no cooperative yield. This covers first deadlines,
  `TIMEDCAP`, traces, and every capture at long periods. C regression tests run
  the actual acquisition function with ownership-checking mocks at `-O0` and
  `-O2` under UndefinedBehaviorSanitizer. They are not a hardware timing model.
- **Complete capabilities:** send `CAPS` from a compiler-sized constant, bypassing
  `reply()`'s 256-byte scratch buffer. Tests compile all four CP2102/health
  combinations, including the one whose line exceeds 255 bytes.
- **Background policy:** the host checks BEGIN against an explicitly expected
  policy. The Studio worker passes its verified policy; campaigns expect the
  rule 1 they select. Bench session/campaign defaults are rule 1. Studio and the recorder
  explicitly select and read back rule 2 when using the default on firmware with
  `BGPOLICY`; they do not inherit a previous client's sticky selection. Those are
  different defaults, not equivalent algorithms.
- **Failure diagnostics:** read optional deferred `ERR` text after a failed stream
  summary with a one-second bound and include it in the error. Success and normal
  STOP do not wait for a nonexistent diagnostic; missing text never makes a
  failed stream valid.
- **Evidence in CI:** recompute all 14 published archives / 36 timing trials and
  compare their analysis fields with `summary.json`, including sensitivity and
  whole-burst metrics. Verify manifest hashes/sizes and all 12 packet-proof runs.
  Verifiers support direct-script and module invocation. Historical evidence and
  measurement source identities are unchanged; only the documentation checksum
  changes with its documented command examples.
- **Installed launcher:** `esp32-sdr studio` now launches Studio, with normal
  `--help` and `--demo` support and dispatch regressions.
- **Source distribution:** checking the installed-command/package path exposed
  missing allowlist entries for this PR's firmware headers and evidence. Add
  exact public files, not a broad directory graft, so an sdist can build the
  firmware and run the evidence tests without shipping local backups or raw RF.
- **Build guide:** correct its stale claim that the current tree is adaptive v8,
  identify the experimental build and the pre-stream source commit explicitly,
  and correct the NVS-error behavior to idle rather than reboot.

### Deferred changes

The pre-merge choices for evidence distribution and the default experimental
firmware are documented in [Preparing a release](releasing.md#pr-4-pre-merge-decisions).
They are not resolved by passing validation. No history rewrite, release tag, or
merge was performed.

- **Larger sparse-I/Q chunks:** worthwhile to benchmark separately, but it changes
  the 48-byte wire format and queue/latency tradeoff. It is not a safe mechanical
  substitution in a protocol with existing firmware, hosts and measured-binary
  evidence. The 70,272-byte wire cost per snapshot remains documented.
- **Splitting the PR:** would improve review organization, but rewriting the
  published series would disturb review context. The PR's review map separates
  firmware, host UI, and historical evidence without changing that history.

### Validation scope

The follow-up includes host regressions, full-suite validation, source/wheel
packaging checks and pinned-SDK compilation. Hardware checks are bounded
control/CRC and known-source ON/OFF checks, not a repeated coverage campaign or a
30-minute soak.
Only the exact installed image and settings from a hardware check can support its
results. No v6 coverage, packet count, or throughput result is reassigned to v7.
Device identities, flash backups, calibration fingerprints and incidental RF stay
private. Application-only validation must preserve each board's different layout
and protected regions; it must not rewrite bootloader, partition table or NVS.

#### Review-fix validation result

- 1,022 host tests plus 5 subtests passed; Ruff lint and formatting passed.
- The pinned SDK compiled the normal v7 image and the combined `UARTBAUD` +
  `DETPIPEHEALTH` configuration. The latter contains the complete 259-byte CAPS
  line, including its newline. The four host capability-combination tests pass.
- An isolated source archive contains all new public resources and no unexpected
  files; private-file exclusion sentinels stayed excluded. Ten extracted-archive
  checks passed. An isolated wheel loaded nine Studio/stream/campaign/verifier
  modules and its `esp32-sdr studio --help` entrypoint exited successfully.
- CI exposed one host-C extraction-test portability issue: its old end marker
  accidentally included the new adjacent helper. The test now extracts only the
  intended function and treats implicit function declarations as errors even on
  older local compilers. This follow-up does not change production firmware.

#### Calibration clarification and resumed board validation

The first installation attempt stopped **before writing** because a normal boot
of the existing v6 application made the earlier whole-flash backup stale. This
was a backup-freshness check, not a permission rejection. The changed fingerprint
alone was not evidence of corruption; the initial triage had not yet applied the
[previous conditional-refresh investigation](evidence/adaptive-evaluation/calibration-follow-up.md).

The follow-up compared the actual original and current records on both boards:

- Only logical `phy/cal_data` changed, by 140 and 121 of its 1,904 bytes. All other
  logical NVS values, calibration format version, and device-identity fields
  matched, as did every byte outside NVS.
- NVS page, entry, and blob CRCs and the reconstructed internal PHY checksums all
  passed for both old and new data. The v6/v7 128-byte PHY initialization data are
  identical; both use the SDK's ordinary partial-calibration/storage behavior.
- This supports valid conditional PHY refresh, not storage corruption. The exact
  transient measurement or library return that triggered these particular
  refreshes was not recorded. Validity does not prove unchanged RF sensitivity.
- Original backups were retained. New current-state full backups were verified
  against each board in the same bootloader session as installation. Both
  application-only writes and readbacks passed, with the entire prefix and suffix
  outside the application's erase sectors unchanged **before the new app booted**.
  No calibration rollback, NVS erase, or persistence suppression was performed.

The installed image is `esp32-dual-sparse-iq-experimental-v7`, from source
`e462bde90dc99a43fec8cc8a8a61247cdd476c99`, application SHA-256
`74d1264470c16344a685786602993f5bf011cb242508a118d0966020cf7f736c`.
Later review follow-ups change documentation, packaging tests and a host comment
only; the firmware source has not changed since that installed revision.

Both receivers passed the bounded passive checks:

| Check | Total across both boards | Result |
|---|---:|---|
| `TIMEDCAP`, 15 ms and 5 s scheduled starts | 4 captures | Transport CRC and full decoding pass; observed trigger lateness 12–13 us |
| `DSTREAM` / `DSTREAMIQ`, 15 ms and 5 s starts, 1.875 ms and 10 ms periods | 16 runs | Status 0, complete transport and sparse-I/Q CRC checks |
| Cooperative STOP, both stream modes | 4 runs | Status 3 and consistent final counters/CRC |

Stored calibration was stable between post-startup test boundaries. Frequency,
gain, filter and background policy were restored and read back after the tests.
The reference is the measured fresh-boot state, not an unobserved frequency from
before the PC restart. This distinguishes installer preservation from later SDK
runtime refresh; see [calibration interpretation](calibration-fingerprints.md).

A separate paired sparse-I/Q smoke used one 10-second known-source ON run and one
10-second OFF run at 2440 MHz, Nordic 2 Mbps, -4 dBm, with a 1.875 ms receiver
period. Each receiver delivered five complete snapshots per condition. ON decoded
4 and 5 distinct known-payload/address/over-air-CRC-valid packets respectively
(union 9); OFF decoded zero on both. Transport checks passed and no scheduled slots
were skipped. Receiver state and transmitter configuration were restored; the
source was healthy and stopped at cleanup, and stored calibration was stable at
all observed post-startup boundaries. Raw RF and device-derived records remain
private. These are bounded functionality/packet checks, not packet recall,
clock-aligned coverage, calibrated sensitivity, or a long-duration soak.

#### Documentation consolidation and pre-merge audit

The later documentation-only review folded this record into `validation.md`,
corrected the PR description to distinguish historical sparse-v6 coverage/soak
results from bounded sparse-v7 validation, and fixed the stale deferred-error
comment. It also corrected this record's policy-default wording: Studio and the
recorder select/read back rule 2, not a previous client's sticky choice.
The full suite again passed **1,022 tests plus 5 subtests**, with Ruff lint and
formatting clean. The source-distribution allowlist check covers the relocated
record. No firmware source, device state or historical evidence bytes changed;
no hardware was used for this documentation pass.
