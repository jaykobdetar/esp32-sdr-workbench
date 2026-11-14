# Documentation index

Current work: [19-item improvement checklist](improvement-checklist.md) · [Full remaining-validation guide](remaining-validation-guide.md).

## Using the project

| Document | Contents |
|---|---|
| [RF Studio](rf-studio.md) | Task-first Listen / Test a signal / Compare receivers workflows, settings and recording. |
| [Combined receivers](continuous-dual-receivers.md) | Display combining, persistent telemetry and clock-aligned coverage are different claims. |
| [Sparse-I/Q protocol](sparse-iq-stream.md) | Experimental wire format, bounds and transport costs. |
| [Firmware build and flashing](firmware-build.md) | Pinned ESP-IDF, build command, backup and manual flashing steps for the original ESP32. |
| [Headless recording](headless-recording.md) | Qt-free recorder CLI, atomic summaries, serial picker and AGC warning. |
| [Serial protocol](protocol.md) | Commands the release firmware answers, capture framing, the detector decision rule and summary fields. |
| [Controlled-source campaign guide](nrf-controlled-source-campaign.md) | How to run new measurements with the nRF52840 transmitter and your own receiver. |
| [Multi-receiver preparation](multi-receiver-preparation.md) | The finite multi-port coordinator; tested with fake devices and one real receiver only. |

[Calibration fingerprints](calibration-fingerprints.md) documents private read-only boundary logging.
[Measured-v2 source](measured-v2-source.md) records the retrospective tag provenance.

[Review follow-up](review-follow-up.md) records v4 fixes and bounded passive validation.

## Latest adaptive evaluation

[Report and public evidence](evidence/adaptive-evaluation/README.md): released-v3
versus v2, separate instrumented tie-fixed soak, calibration caveat and six source
review concerns. Supporting guides: [matched trials](matched-adaptive-gain-trials.md)
and [optional heap/stack telemetry](pipeline-health-telemetry.md).

## Results and their limits

| Document | Contents |
|---|---|
| [Validation record](validation.md) | Historical benchmark and maintenance passes, plus [current streaming-v7 review checks](validation.md#streaming-v7-review-validation-13-november-2026). |
| [Controlled RF validation summary](nrf-validation-summary.md) | Known-packet results of 11 November 2026 with the nRF52840 source. |
| [Matched gain comparison](matched-gain-comparison.md) | 24 bounded AGC/manual ON/OFF runs on unchanged firmware, with per-run evidence and limits. |
| [Controlled RF analysis](controlled-rf-analysis.md) | Detailed tables, statistics and caveats behind that summary. |
| [RF publication verification](rf-publication-verification.md) | What was checked when the controlled-source material was published. |

## Evidence and provenance

| Document | Contents |
|---|---|
| [Streaming evidence](evidence/dual-stream-evaluation/README.md) | Build-specific intermediate candidates and sparse-v6 timing/packet/soak evidence, not sparse-v7 performance. |
| [Benchmark evidence](evidence/README.md) | A/B, soak and GUI summaries, build identity, microbenchmarks and diagnostic sources. |
| [Controlled-source evidence](evidence/nrf-validation/README.md) | Scrubbed per-recording data, known-packet bytes and comparison statistics. |
| [RF source provenance](rf-source-provenance.json) | Recorded hashes of the campaign and analysis sources; enforced by `tests/test_source_provenance.py`. |
| [Diagnostic provenance](diagnostic-provenance.md) | Why the historical lab clients, other-chip backends and vendored ESP-DSP are kept. |
| [Energy candidates](energy-candidates.md) | Arithmetic bounds and the generator for the energy kernel variants. |

Related material outside this folder: the [transmitter](../nrf52840-transmitter/README.md), the [unadopted retention patch](../experiments/retention/README.md), the [firmware source provenance](../firmware/SOURCE_PROVENANCE.md) and the [script index](../scripts/README.md).

[Preparing a release](releasing.md#pr-4-pre-merge-decisions) records the pre-merge evidence-size and default-firmware choices.
