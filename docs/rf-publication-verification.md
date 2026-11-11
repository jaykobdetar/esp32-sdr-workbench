# RF validation publication verification

Published 11 November 2026 as an additive update to the optimized public workbench. No serial device was opened, radio transmitted, or device flashed during preparation. Historical experimental results remain historical; these checks validate the public export and software.

## Checks on the public source copy

- Combined viewer, campaign, coordinator, evidence, synthetic decoder, opt-in retention-patch, receiver-source and transmitter-host suite: **232 tests passed, 5 subtests passed**. Command: `QT_QPA_PLATFORM=offscreen python -m pytest -q tests firmware/tests nrf52840-transmitter/tests`.
- Existing evidence verifier: `python scripts/verify_evidence.py`, passed with unchanged historical headline results.
- New evidence verifier: `python scripts/verify_nrf_evidence.py`, passed. Verified 550 recording rows, all recorded UART CRC flags, 25 known complete packet byte patterns and RF CRCs; recomputed 32.1108% versus 62.3319% ABAB local ON duty, 101.7730/102.8854 candidate-window-per-second cycle excess differences, and paired retention 2/12 versus 3/12. Bootstrap intervals were not recomputed by this verifier.
- Original IQ SHA-256 matched the selected saved analyses for all 550 files during export. The original IQ is not distributed, so public checks cannot independently redo demodulation or UART wire CRC validation.
- Optional retention patch applies in a temporary copy and its mocked C pipeline tests pass at O0 and O2 with undefined-behavior sanitization. The released firmware tree is unchanged.
- Transmitter scheduling, STOP-race and CRC C tests, sanitizer parser test, ARM build and guarded UF2 packaging passed. The rebuild matched the historical application BIN with the tested compiler and pinned dependencies. See [transmitter verification](../nrf52840-transmitter/docs/offline-validation.md) for hashes, exact scope and fresh-download limitations.
- New-source Python compilation, relative Markdown links, Git whitespace checks and privacy-pattern review passed. Known private serials, machine names, personal absolute paths, recovery images, raw RF and secret patterns are absent from staged new files. Generated firmware artifacts are ignored, not published.

## Reproduction scope

Software checks used the existing Python 3.14 research environment (including Qt offscreen), a host C compiler, and the pinned local official transmitter dependencies. No receiver firmware rebuild or hardware rebenchmark was required for this publication because the adopted receiver source is unchanged. No new GitHub Actions workflow was added; local checks do not imply remote CI coverage.

[Source provenance](rf-source-provenance.json) lists unchanged analysis/coordinator source and portability-only campaign edits. [Evidence provenance](evidence/nrf-validation/README.md) explains original/public hashes and omissions. [Transmitter provenance](../nrf52840-transmitter/THIRD_PARTY.md) retains third-party notices and pins. Existing source, historical evidence and personal working records were preserved.

The experiment does not establish packet recall, calibrated sensitivity, continuous reception, two-receiver timing coverage, Quest decoding, or reservoir superiority.

## Subsequent offline statistics verification

The updated verifier now recomputes every archived ABAB and paired-retention bootstrap interval using the original seed, sample count and resampling order. It also recomputes Wilson intervals and exact McNemar p, and enumerates paired sign flips and cycle pair-label permutations. All match the unchanged published measurement JSON. See [the evidence method](evidence/nrf-validation/README.md) for exchangeability and small-sample limits. No new RF measurements are implied by this recalculation.
