# Workbench improvement checklist, 11 November 2026

Work started by fast-forwarding a clean checkout from `f94a761` to the updated
remote main `d979748`. The separate private research/recovery workspace was not
replaced. Implementation was prepared on `improve/workbench-19-items` as commit `a07083e`.
The owner subsequently authorized publishing these changes and a
[remaining-validation guide](remaining-validation-guide.md). No public tag or
release is created by this publication.

## Later evaluation update

This checklist records the earlier implementation checkpoint. The subsequent
[adaptive evaluation](evidence/adaptive-evaluation/evaluation-report.md) completed
released-v3 smoke/matched tests and a separate instrumented, tie-fixed candidate's
boundary, memory/stack and 30-minute soak checks. Its results supersede the earlier
unflashed/open-bench status below, not the historical measurements themselves.
No retained-packet advantage was established; calibration changed at an unknown
point. The verified v2 application was restored. A new default-off release image
still requires validation, and no tag or release is created by this publication.

## Implementation status (earlier checkpoint)

| Item | Result |
|---|---|
| 1. Compile firmware in CI | Added pinned-SDK current ESP32 and immutable historical-retention builds, plus nRF ARM build. All three also compiled locally. |
| 2. Transmitter C checks | Parser, schedule, stop-control and CRC checks are now pytest-collected. |
| 3. Verify uncertainty | Recomputed all 31 published bootstrap intervals, four Wilson intervals and McNemar p. Added exact pair sign flips and cycle permutations with assumptions stated. |
| 4. Detector reference | Bit-exact C-checked energy/background model and lossless original CAP20 SigMF adapter/replay CLI. Missing/selected capture history is not represented as online replay. |
| 5. Atomic summaries | Final JSON is renamed into place only after capture saving succeeds or its error is recorded. |
| 6. Split GUI | Acquisition and recording moved to Qt-free `acquisition.py`. |
| 7. Headless recorder | `esp32-sdr record`: bounded runs/duration, raw or detector modes, graceful signals, errors and optional three-crop recording. |
| 8. Serial picker | Editable discovered-port list and refresh preserve manual input without opening ports. |
| 9. AGC warning | Visible GUI warning and CLI warning for AGC with detector mode. |
| 10. Types and validation | Shared strict summary validator plus accurate return/parameter hints in core protocol, analysis, detector, pipeline and profiling APIs. Not a claim of complete static typing. |
| 11. Packaging | `nrf_tx` and `nrf_campaigns` packages remove campaign path manipulation; single host version source, changelog, wheel/source distribution and release guide. Public tag/release remains uncreated. |
| 12. Latest dependencies | Weekly/on-demand workflow deliberately tests latest Qt beyond the production constraint, including a real offscreen paint loop. It becomes active only after publication to the relevant branch. |
| 13. Background latch | Versioned Q16 policy updates positives slowly and negatives faster. Host/C parity and sustained-step recovery checked. |
| 14. Fine arithmetic | Q16 temporal background with one-quantum floor; energy kernel remains integer ADC². |
| 15. Multiple candidates | Opt-in three peak-centered 5120-sample crops within the previous full-size packed-byte budget. Default remains one. Board fragmentation, stack, CRC and soak checks remain open. |
| 16. Gain and timing | Raw gain-register start/end snapshots, requested mode, acquisition-trigger device uptime and retained candidate offsets/generations. Not calibrated RF arrival or complete AGC history. |
| 17. Matched gain runs | Completed 24 bounded runs on unchanged optimized-v2, with all retained transport CRCs valid. See [results](matched-gain-comparison.md). |
| 18. Measured geometry | Not run: antenna distance/orientation/height/obstructions need actual physical measurement. No distance was invented. |
| 19. Launcher screenshot | [Actual launcher screenshot](viewer-launcher-demo.png) shows ADC endpoint column. Explicitly synthetic raw-IQ mode, not new hardware-performance evidence. |

## Important limits and next steps

The new `esp32-pipeline-adaptive-q16-v3` firmware has **not been flashed**. Its
behavior, cropping cost, heap fragmentation, stack high-water mark and long-run
hardware performance are not validated by compilation or host tests. Historical
RF performance numbers remain attributed to the exact old measured image.

The [adaptive detector guide](adaptive-detector.md) documents crop duration,
peak/boundary limitations, metadata and safe validation needs. A 5120-sample crop
spans 320 µs at 16 MS/s but only 128/64 µs at 40/80 MS/s; higher rates cannot fit
the known 292 µs test frame in that crop. Even at 16 MS/s packet containment is not
guaranteed.

The existing transmitter was stopped and its initial configuration restored after
the gain trial. Receiver gain was restored. No firmware/recovery data, OS security
or network settings were changed. CI workflow files are included with publication;
check the runs for the exact published commit before claiming remote CI success.
The local verification below is separate from remote CI.

## Verification completed locally

- Full suite: **383 tests plus 5 subtests passed on Python 3.10 and 3.14**.
- Ruff 0.16.9 lint and formatting, `git diff --check`, both offline evidence
  verifiers, and the new matched-gain evidence recomputation passed.
- Integrated current-pipeline C mock passed under UBSan at `-O0` and `-O2`,
  exercising both kernels/copy modes, indexed crop CRCs, failed allocations and
  rejected ranges, cleanup, final pending-capture drain and one-shot policy reset.
- Clean Python wheel/source distribution built; wheel-installed recorder, campaign,
  analysis and detector-model CLI help passed from outside the checkout.
- Pinned ESP-IDF current source and immutable historical-retention builds, and
  nRF ARM compilation/application-only UF2 validation passed locally.
- Screenshot verification used the actual launcher in explicit demo mode. All
  subsequent UI tests were offscreen; the screenshot is not a hardware test.
- Publication follow-up: explicitly install Newlib headers on clean ARM CI
  runners, and test the recorder lifecycle with both discovered and fallback
  serial-port choices rather than assuming a host-specific device name.

These results are local checks, not remote CI results. No new firmware was flashed.
