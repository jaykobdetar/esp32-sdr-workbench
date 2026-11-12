# ESP32 SDR v7 board evaluation

Date: November 12, 2026. Tested main commit [b39c09b88eaeba6bb28f8e3812816444fa906531](https://github.com/jaykobdetar/esp32-sdr-workbench/commit/b39c09b88eaeba6bb28f8e3812816444fa906531), still remote main at completion.

## Verdict

The exact release build passed the bounded functional, transport, and stability tests. The new runtime legacy/adaptive selector works with normal clients and enables useful same-image RF comparisons. Both policies captured real known packets. These tests do not establish that the adaptive policy has better packet recall or retention.

One minor command-parser bug was reproduced on the board. No source fixes were made or published. The known-good optimized-v2 application is restored, its flash contents and receive behavior verified, transmitter stopped, and saved transmitter configuration and receiver gain/selectors restored. Receiver tuning remains at the test configuration (2440 MHz, 16 MS/s, 12 MHz bandwidth).

## Exact identity and preservation

- Variant: esp32-pipeline-adaptive-q16-v7; revision b39c09b88eaeba6bb28f8e3812816444fa906531.
- Application SHA-256: db7ab188ba6c0616eac5be151052ecf26b56f9b3d8284bd35f04c190265dde19.
- Built with the repository's pinned ESP-IDF/toolchain. Installed and verified at application offset 0x10000 only. Bootloader, partition table, PHY-init region and recovery images were preserved.
- Tests used the original ESP32-D0WD-V3 receiver and nRF52840 source, not simulated RF. No desktop windows were opened or forcefully closed.
- 605 host tests and 5 subtests passed. Ruff lint and formatting checks passed. Clean firmware build passed.

## Board coverage

The primary exact-release campaign completed **984 runs and 1,288,396 captures**, saving **1,520 I/Q files** whose transport CRCs all passed:

- 336 boundary combinations: 7 buffer lengths (including odd lengths and crop boundaries), 3 sample rates, 2 kernels, 2 copy settings, 2 retention settings, and both background policies.
- 288 randomized controlled RF runs: 12 temporal blocks for each of 6 power/gain settings, with both policies and transmitter ON/OFF in randomized order within each block.
- 360 five-second soak runs, alternating policies and single/three-crop retention. This is 30 minutes of requested detector-run time and 33.15 minutes including host work. No crash, reset, acquisition error, failed packing, or transport CRC error was observed.

Additional checks covered DET1 under each policy, boot-default selection, malformed inputs, 72 unselected raw captures on v7, and 24 v7 timing runs. V2 received the same 72-raw-capture and 24-timing-run comparison after restoration, plus a final passive health check.

An initial harness attempt stopped on an 88-byte first-use decrease in free heap and a change in largest block. The full rerun recorded rather than ignored that behavior: cleared free heap was exactly **137,456 bytes**, largest block **69,632 bytes**, after every one of the 984 runs. This provides no evidence of a continuing leak in this bounded campaign. It is not a lifetime stability proof. Stack headroom and in-run minimum heap were **not** instrumented on this release binary; earlier instrumented builds' figures are not relabeled as v7 measurements.

## Controlled packet evidence

With a known 64-byte, 2 Mbps transmitter payload:

- Of 144 transmitter-ON detector runs, all retained a recording. **15 recordings contained complete matching payloads; 11 had a verified over-air CRC and address.** There were 16 complete payloads in those 15 recordings.
- Of 144 OFF runs, 141 retained recordings. None contained a complete matching payload.
- Both policies recovered CRC-valid packets. These are recording yields, not transmitted-packet recall. Host timing does not reliably match every transmitted packet to every acquisition window.
- Direct unselected v7 raw controls: 3/24 matched-frequency ON captures contained CRC-valid known packets; 0/24 OFF and 0/24 offset-frequency (2470 MHz receiver, 2440 MHz source) captures did.
- Sequential v2 direct controls: 4/24 matched ON, 0/24 OFF, 0/24 offset. This small sequential sample does not demonstrate a v7 regression or improvement.

Transmitter completion counters were recorded, not inferred from scheduled counts. The strongest tests used 0 dBm; weaker tests used -20 dBm. Geometry, distance and orientation were not measured or changed. These are bench tests, not calibrated sensitivity or Quest-protocol validation.

## Same-image policy comparison

At 0 dBm and manual gain 40, source-associated candidate windows (ON minus OFF) averaged about **176/s for legacy** and **290/s for adaptive**. The adaptive-minus-legacy difference was +114/s, descriptive bootstrap 95% interval +19 to +210, exact paired sign-flip p=0.0415. This does **not** survive a conservative correction across the six tested settings.

At gain 60 and hardware AGC, rule differences were not convincing. At -20 dBm, environmental variation prevented a reliable source-associated effect. Candidate rates are not packet counts; an increase is not automatically better packet retention. No global winning rule is established.

The saved statistics include all ON/OFF runs, including those with no retained event. Twelve temporal pairs per condition are still a small sample; sign-flip results depend on the paired comparison assumptions. The bootstrap intervals are descriptive rather than a guarantee of coverage.

## Duty and whole-image comparison

A later source-OFF timing screen used v7 policy 1 and the preserved v2 binary:

| Image | No retention (12 runs) | Single full-buffer retention (12 runs) |
|---|---:|---:|
| v7 legacy policy | 62.82% | 61.57% |
| measured v2 binary | 62.91% | 62.54% |

These are nominal local RF listening duty, not whole-session coverage. Tests were sequential, not alternating images; event-copy load and RF/calibration differences limit causal interpretation. V7 policy 1 reproduces the historical decision rule, not all timing/layout of the old binary.

## Calibration

The stored calibration **refreshed between the pre-install snapshot and v7 startup**. Both old and new records pass NVS entry/blob CRCs and the radio library's internal checksum. The new fingerprint then remained unchanged through every observed v7 stage boundary, including RF and soak tests. Thus same-image rule comparisons shared a stable stored calibration, but historical/whole-image comparisons retain a calibration caveat. No calibration bytes were manually replaced. This is consistent with the previously observed refresh behavior, not evidence of corruption; the exact trigger was not established.

## Confirmed issues and limits

1. **Minor BGPOLICY parser bug:** `BGPOLICY1`, `BGPOLICY 4294967297`, and `BGPOLICY -4294967295` all replied `BGPOLICY 1` and changed state on the actual board. The documented contract says malformed/out-of-range values reject without changing state. The `%u` parser accepts missing separation and wraps these numbers. Use strict token/range parsing and regression tests. Normal typed Python clients already reject these inputs. These malformed probes ran after the main RF/soak campaign, so they did not change its selected policies.
2. At evaluation time, `docs/firmware-build.md` contained one stale parenthetical naming v6 below its correct v7 heading. That documentation-only reference is corrected in this publication.
3. The safe-idle NVS failure path passes production-code host tests at O0/O2. An actual NVS failure was not induced on the board, because intentionally damaging calibration/settings would be inappropriate. The normal boot path was tested.
4. Three-crop mode passed bounded transport/heap tests, but its previously documented packet-containment limitations remain. This evaluation does not recommend it over full-buffer retention.
5. No claim of continuous reception, calibrated RF sensitivity, exact packet recall, or Quest controller decoding is warranted.

## Public evidence and reproduction

- [Run summaries](run-summaries.json): all 984 primary runs, with no-event runs retained in the denominators.
- [RF decoder summaries](rf-decoder-summaries.json) and [paired statistics](rf-statistics.json).
- [Extra v7 checks](extra-v7.json), [v2 controls](extra-v2.json), and [build/preservation record](preservation-and-build.json).
- [Publication manifest](publication-manifest.json): hashes of this curated export.

Run `python scripts/verify_v7_evidence.py` from the repository root to independently recalculate the published counts, duty means and exact paired sign-flip p-values.

This export contains measured summary data, not fresh measurements. It omits raw RF, flash/recovery backups, device identifiers, absolute local paths, calibration fingerprints and observed packet-byte strings. Decoder summaries preserve counts and CRC/address flags, but without the private I/Q they cannot independently prove RF decoding. Source hashes provide provenance, not proof that a measurement occurred. Bootstrap intervals are retained from the recorded analysis; the verifier recomputes exact sign-flip p-values, not the bootstrap intervals.

The evaluation made no source fixes. This subsequent publication adds only documentation, sanitized evidence and an offline verifier. The parser issue remains open.
