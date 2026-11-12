# Published measurement evidence

This is a curated, privacy-reviewed export of existing research records from 2026-11-10, published on 2026-11-11. No board was queried or flashed and no new RF measurement was performed for this supplement. Local originals were preserved. It contains measured results and explicitly labeled derived checks, not invented serial transcripts.

## Adaptive evaluation supplement

The [adaptive evaluation](adaptive-evaluation/README.md) adds privacy-reviewed
summaries from the later 11–12 November campaign, with image-separated identities,
925 pipeline runs, source-audit findings and explicit calibration/decoding limits.
The source publication performed no new hardware access or firmware installation.

## New controlled RF campaign supplement

The [11 November controlled nRF52840 validation](nrf-validation/README.md) adds 550 recording summaries, hashes, known test-packet bytes, actual-image ABAB comparisons, the parameter screen and the unadopted retention trial. It has a separate offline verifier and preserves the distinction between UART CRC, known RF packet CRC and unmeasured packet recall. No new device access was performed for publication. Earlier evidence and conclusions below retain their historical scope.

## Coverage of the requested evidence

| Request | Published record | Coverage / limitation |
|---|---|---|
| 12 final-image A/B trials | [final-release-v2.json](final/final-release-v2.json), `runs` | All 12 parsed run summaries: three legacy and three optimized, with and without retention. These are archived host-parsed summaries, not raw END bytes. Includes 24 raw CRC checks and three short-buffer fallback checks. |
| 24 retained-event soak runs and heap | [final-release-v2-soak.json](final/final-release-v2-soak.json) | All 24 run summaries, each with the literal `memory_after` DETPIPEMEM response and CRC results, plus final post-clear memory reply. |
| Five GUI runs | [gui/](gui/), `gui-run-01` through `gui-run-05.detpipe1.json`; [gui-result.json](gui/gui-result.json) | All five saved summaries and final GUI statistics/log, with identifiers sanitized. |
| Historical 32.1% DET1 v2 | [v2-B1.json](historical-det1/v2-B1.json), [v2-B2.json](historical-det1/v2-B2.json), [comparison-summary.json](historical-det1/comparison-summary.json) | All 12 v2 trials, not just one favorable run. The two v1 control phases are also included. |
| Measured binary identity | [build/](build/) | Original VERSION reply, sdkconfig, flash_args, export manifest, build-info, verification record and decoded partition table. Application/bootloader/partition binaries are not published. |
| Missing source references | [protocol](../protocol.md), [energy candidates](../energy-candidates.md), [generator](diagnostic-sources/energy-candidates/generate_dispatcher.py) | Release-specific docs plus the original generator, input and generated outputs. |
| INFO/CAPS/LIMITS/VERSION/TRANSPORT/SPECINFO/GAIN handshake | [archived-handshake.json](handshake/archived-handshake.json) | Raw INFO, VERSION and TRANSPORT strings exist. CAPS/LIMITS/SPECINFO were only saved as parsed values. No measured raw GAIN? reply was found. [Replay fixture](handshake/replay-fixture.json) is explicitly synthetic where serialized from parsed data. |
| Kernel, packing and fused-copy microbenchmarks | [microbenchmarks/](microbenchmarks/) | Complete selected campaign summaries, including negative/failed runs and stage distributions; these are separate diagnostic images, not the final release. |
| Screenshot-session clipping | [clipping-counts.json](gui/clipping-counts.json) | Endpoint counts for all five retained captures and original data/metadata hashes, instead of publishing raw RF. |
| Manual-40 vs hardware-AGC matched pairs | Not collected here | Existing final A/B trials use manual 40 and bandwidth 12; GUI runs use hardware gain and bandwidth 0. These are not controlled same-settings gain pairs. |
| Terminated/shielded-input floor | Not available | No such measurement is asserted. |
| Screenshot through `./scripts/launch.sh` | Not collected here | The existing README screenshot is byte-identical to the archived GUI smoke-harness image. It is not relabeled as a launcher capture. |
| Diagnostics / other-chip / ESP-DSP decisions | [diagnostic provenance](../diagnostic-provenance.md) | Keep historical clients and matching instrumentation source selections, clearly unsupported by release. Keep other-chip source as provenance; keep vendored ESP-DSP because it is an actual ESP32 build dependency. |

## Recompute the headline numbers without hardware

From the repository root, using standard-library Python 3.10+:

```sh
python3 scripts/verify_evidence.py
```

The verifier checks published source-file hashes and recalculates duty from sample counts and elapsed times. Expected output is [summary.json](summary.json); regression tests compare it directly. Duty in percent is:

```
100 * total_samples / sample_rate_hz / (wall_elapsed_us / 1_000_000)
```

Host-run duty substitutes `host_total_elapsed_us`. GUI cumulative duty sums all completed runs' samples and divides by the final `host_session_elapsed_through_recording_s`. Retained CRC flags are preserved original observations; without RF payloads the public verifier cannot independently recheck capture CRCs.

- Final A/B intervals reproduce the README exactly to its displayed precision.
- Soak total: **73,745 captures**, 24/24 retained and post-run raw CRC checks recorded true. Every post-run reply is **`DETPIPEMEM 96688 65536`**; after `DETPIPECLEAR`, it is **`DETPIPEMEM 137688 73728`**. This supports stable sampled heap readings over this soak, not proof that every transient allocation was leak-free or that arbitrarily long operation is stable.
- Historical DET1 v2 mean: **32.1047666724%**. Final optimized no-retention mean divided by that historical mean is **1.9606697642×**. The historical build differs from the final image; it is not the same-image legacy control.
- GUI **62.4178005780%** is the **last run's local duty**, while **42.9268378023%** is **cumulative host-session duty through the fifth recording**. They are different aggregation windows, not two means over identical windows. A subsequent GUI status update adds a tiny additional elapsed interval (42.9258228382% in `stats.nominal_duty * 100`). Both display as 42.93%.

[methods/](methods/) preserves the relevant original campaign/harness source as non-executable `.py.txt` files, with device identifiers removed. It records settings, ordering, gains, durations and collection logic. These are historical procedures referencing a private research layout, not turnkey scripts for the release. They must not be executed blindly on an arbitrary board.

## Build identity and partition provenance

Measured application SHA-256:

```
8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad
```

The [export manifest](build/manifest.json) and [final installed verification](final/final-installed-verification.json) agree with the A/B record. VERSION identifies `esp32-pipeline-optimized-v2`, build timestamp `2026-11-10T23:21:02Z`, revision **`unknown`**. That is the original value, not a missing Git commit filled in later. A fresh source rebuild need not reproduce this binary byte-for-byte because timestamps and layout can differ.

The generated [sdkconfig](build/sdkconfig) is byte-identical to the archived measured configuration. [partition-table.csv](build/partition-table.csv) was decoded offline from the exported partition binary using the pinned ESP-IDF decoder after hash verification. Its factory partition is **0x10000, 1 MiB**; the legacy source `partitions.csv` is not the active generated table. The export uses 2 MB flash-size settings on the tested 4 MB device.

[archive-integrity-check.json](build/archive-integrity-check.json) records an offline check of every entry in the original [SHA256SUMS](build/SHA256SUMS), including withheld binaries/source archive. This old manifest intentionally names artifacts not present publicly. It is provenance, not a promise of downloadable binaries. Use SOURCE_MANIFEST for public-file integrity. `BUILD_VERIFICATION.json` retains its original `built_pending_target_rebenchmark` status because it was frozen before later tests; the subsequent final trial/soak records supply the measured results. No historical record was retroactively rewritten as a pass.

## Microbenchmarks and negative evidence

- [energy-test-v1-kernels.json](microbenchmarks/energy-test-v1-kernels.json): three full-buffer same-input trials plus shorter checks, 63 repetitions per variant after three warmups. At recorded 240 MHz, flash candidate 0 median **1256.6208–1256.6250 µs**, candidate 3 **847.5417 µs**. Target mismatch counts/masks are zero; host reference results are retained. Raw RF inputs are withheld.
- [packing-v1.json](microbenchmarks/packing-v1.json): three profiled same-image pairs and three unprofiled pairs. Profiled retention-stage means are **2642.8–2644.5714 µs** for option 0 and **815.1818–821.8333 µs** for option 1. These are occasional strongest-event repackings, not UART transfer time or every capture. [Stage notes](notes/pipeline-stage-distributions.md) describe overlapping/nested timing and profiling overhead.
- [validate-copy-v1.json](microbenchmarks/validate-copy-v1.json): full-buffer separate validate4+memcpy median **533.1625 µs**, fused-unroll4 **461.0792–464.7917 µs**. Scalar fusion regressed to **614.5750 µs**; unroll8 was **533.1792 µs**. Full result sets retain counts, extrema and mismatch checks.
- [pipeline-v4fused.json](microbenchmarks/pipeline-v4fused.json) preserves the failed run/timeout rather than hiding it. [pipeline-v4frame.json](microbenchmarks/pipeline-v4frame.json), [frame-probe-v4.json](microbenchmarks/frame-probe-v4.json) and the [transport finding](notes/serial-packet-boundary-finding.md) give the later framing controls. Original binary wire drains named in historical notes are not included here.
- [pipeline-profile-v1.json](microbenchmarks/pipeline-profile-v1.json) retains its host-side memory-rejection handling failure after completed trials; [pipeline-compact-v1.json](microbenchmarks/pipeline-compact-v1.json) retains the compact follow-up. Diagnostic overhead and allocation constraints preclude substituting these stage timings for an exact decomposition of the final release.

## Endpoint counts and RF privacy

The existing screenshot SHA-256 matches its archived smoke-session image. The screenshot was captured before that session's final run completed, so no unsupported assertion ties its trace to one particular saved capture. Counts are supplied for all five (16,380 samples each):

| Run | I at an endpoint | Wire-Q at an endpoint | Either component |
|---|---:|---:|---:|
| 1 | 0 | 1,354 | 8.2662% |
| 2 | 0 | 166 | 1.0134% |
| 3 | 0 | 2,090 | 12.7595% |
| 4 | 0 | 55 | 0.3358% |
| 5 | 0 | 33 | 0.2015% |

Endpoints are exact signed-10-bit codes **−512 or 511**, not complex magnitude ≥1. The saved convention is `(I - j*wire_Q)/512`. These endpoint concentrations support concern about saturation/clipping, especially in Q; they do not identify analog overload, AGC behavior or a digital-path cause. Absence of exact endpoints would not prove absence of clipping either. Do not infer false positives or sensitivity from this count alone.

To reproduce counts against a privately held original pair without transmitting it:

```sh
python3 scripts/count_sigmf_endpoints.py /path/to/capture.sigmf-meta
```

The script validates the exact ADC lattice and prints only counts and a data hash. The metadata/data hashes in the report allow the owner to select the exact archived inputs. No RF samples, SigMF files, device NVS/full-flash backups, recovery images or credentials are included in this publication.

## Integrity, sanitization and boundaries

[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) maps primary evidence exports to original relative source identities, original SHA-256 and published SHA-256/size. [Diagnostic source provenance](diagnostic-sources/SOURCE_PROVENANCE.json) separately covers source selections. [SHA256SUMS.public](SHA256SUMS.public) covers every published evidence file except itself.

Numeric measurements, firmware metadata and timestamps were preserved. Personal absolute paths were made relative/redacted; serial paths, device-derived GUI basenames and host identifiers were replaced with neutral labels. Generic firmware family/capability metadata and the SDK's default `espressif` hostname are not device identities. Original report references to RF files remain provenance labels, not public downloadable links. Hashes provide integrity, not signatures or independent measurement attestation.

No controlled gain comparison, isolated false-positive floor, fresh full raw handshake, new launcher screenshot, hardware regression, or independent RF timing calibration was performed. Those remain follow-up measurement gaps, not implied successes of this evidence publication.
