# Four-receiver evaluation, 15 November 2026

## Current conclusion

Four original ESP32 receivers now run the exact preserved v9 application and work in the viewer. Four-clock scheduling is implemented and physically exercised. **Continuous retained I/Q or gap-free packet reception has not been achieved.** One added receiver has reproducible corruption even without RF acquisition. Longer multi-receiver trials also exposed valid-CRC sequence gaps and corruption on other receivers. Sustained reliability is not established with or without that added receiver; rejected trials are not counted as successful coverage. Root causes remain unresolved.

This report distinguishes (1) no-retention nominal acquisition windows, (2) actual known-packet recovery from sparse raw snapshots, and (3) the asynchronous diversity viewer. None establishes real Quest compatibility.

## Recovery and firmware

Private, board-specific 4 MB recovery images were verified against device-side block and whole-flash digests before writes. Device identity, security state, flash capacity, active application offset and partition layout were checked. Failed reads were retained and retried conservatively, never relabeled valid. The application offsets were `0x10000` for receiver A and `0x100000` for B/C/D.

A/B kept exact v9. C/D received that same application-only image, with exact readback and unaffected-region checks. Their legacy tables lacked the MD5 footer required by the modern SDK. The firmware initially failed closed with NVS error 261, preserving storage. The checksum-only compatibility repair left all partition entries/layout unchanged. A transport failure during C's table verification triggered a verified exact rollback before a later successful retry. See [setup and offline helper](../../four-receiver-setup.md).

Postboot audits verified all four application images, unchanged bootloader and PHY-init regions, and unchanged OTA/customization regions where present. C/D table differences are the intended footer. **NVS is not byte-identical to the original backups.** Offline decoding also found the stored 1904-byte PHY calibration differs from original backups on all four, including unchanged-application A/B. The SDK can regenerate calibration when saved data fails its loading/validation checks, but the exact trigger here was not logged. Original calibration remains in each verified private recovery image; do not describe current calibration bytes as unchanged across resets. Fingerprints were stable within accepted individual campaigns.

The reconstructed v9 firmware compiled with the pinned SDK and passed 71 firmware tests plus 5 subtests. Fresh build and preserved image hashes are documented in [FIRMWARE.md](FIRMWARE.md); the fresh binary was not substituted for the exact preserved application. No default firmware source was promoted.

## Timing: nominal windows only

At a 1.875 ms period with idle-wakeup selector 34 and independently RF-anchored clocks:

| Trial | Requested window | Nominal acquisition union | Nominal decision-valid union | Largest acquisition gap | Outcome |
|---|---:|---:|---:|---:|---|
| Initial smoke | 10 s | 99.9998700% | 99.69999% | 13 µs | Verified |
| Repeat 1 | 30 s | 99.9999567% | 99.8999966667% | 13 µs | Verified |
| Repeat 2 | 30 s | 99.9999833% | 99.8999966667% | 5 µs | Verified |
| Repeat 3 | 30 s requested | Not reported | Not reported | Not reported | Rejected: stream framing/CRC failure on C |

The accepted gaps were at the requested startup edge, not trimmed away. Each accepted run passed complete record/terminal accounting and every receiver-to-reference clock fit's bracketing and held-out checks. The 10-second run's maximum held-out error was below 0.83 µs, an empirical screen rather than a certified error bound. Its ±20 µs endpoint-erosion scenario retained 99.99967% nominal union.

Decision-valid windows exclude exactly the first 16 warmup records from **each receiver**. In every accepted 10-, 30- and 120-second trial documented here, the combined decision-valid union first starts 30,001 µs after the requested start. It has that single startup gap and no interior union gap within the requested window under the nominal timing model. Its denominator still includes the full requested window, including warmup. This is eligibility for a detector decision, **not a positive detection, decoded packet, packet-recovery percentage or host delivery-time measurement**. The acquisition union includes warmup; the decision-valid union does not.

These are trigger-plus-nominal-sample-duration windows. DSTREAM discards raw I/Q. Clock anchors are selected common packets, not a recall denominator. Complete host-session preparation, anchor collection and delivery are not hidden inside the requested timing denominator; they are outside that particular measurement.

## Sustained transport controls

After the rejected four-board trial, all four reconnected and returned CRC-valid passive captures. Source-off isolated controls alternated C and A for up to 60 seconds each:

- C failed twice, after 26,184 and 9,315 validated records. Both offending 48-byte records were entirely `FF`, not valid `DSV1` records.
- A completed both 60-second controls with 32,001 records each.

An acquisition-free static-CAPS control targeted the same 25.6 kB/s response rate. C failed after 43.26 seconds at 25,597 bytes/s: exactly the first 64 bytes of a 254-byte reply became FF, while the remaining 190 bytes were exact. Recovery without reopening the serial descriptor found a consistent device clock and unchanged calibration. A completed the corresponding 60-second control at 25,602 bytes/s with exact responses. This establishes that the observed corruption is not specific to RF capture or four-receiver scheduling; it does not uniquely identify the physical component at fault.

No firmware path intentionally produces an all-FF DSTREAM record. This narrows the failure beyond aggregate four-device load, but does not prove a cable, bridge, power, MCU-memory or software cause. There were no contemporaneous kernel USB disconnect/re-enumeration events. New diagnostics retain bounded failed frames and reject the entire trial; they never repair or resynchronize corrupted observations into accepted coverage. Earlier failures cannot retrospectively gain missing frame evidence.

## Longer A/B/D comparison, excluding C

Two 120-second trials passed all clock-fit, CRC/accounting and calibration screens:

| A/B/D trial | Requested window | Nominal acquisition union | Nominal decision-valid union | Largest acquisition gap | Outcome |
|---|---:|---:|---:|---:|---|
| Repeat 1 | 120 s | 99.9999892% | 99.9749991667% | 13 µs | Verified |
| Repeat 2 | 120 s | 99.9999958% | 99.9749991667% | 5 µs | Verified |
| Repeat 3 | 120 s requested | Not reported | Not reported | Not reported | Rejected: stream sequence/framing failures |

Both accepted decision-valid unions exclude the same 30,001 µs startup gap described above, with no interior union gap in the requested interval under the nominal model. The third requested 120-second trial was rejected after approximately 26 seconds: B first produced a valid-CRC ordinary record with a four-record sequence gap. A subsequently had an eight-record gap and D an all-zero frame. Group cancellation was being requested, but normal STOP semantics do not intentionally produce these records; exact causality is not established. Complete per-peer diagnostics remain private and no coverage is reported for the rejected run.

This is evidence of two successful bounded trials, **not sustained three-receiver reliability**. It also prevents attributing all long-run failures exclusively to C's independently observed FF corruption. All four subsequently recovered to passive CRC-valid captures without firmware or physical-connection changes.

## Actual sparse packet recovery

All accepted packets require the expected full payload, address and over-air CRC, separately from UART transport CRC. Completed nRF transmissions are the denominator. Source-OFF controls returned no accepted packets. The source remained stable firmware 0.2.2 and every transmission run was finite.

| Control | Captures per receiver per condition | Source | Unique / completed | Recovery | Duplicated observations |
|---|---:|---:|---:|---:|---:|
| Low-power repeat | 8 | -20 dBm, 8 s | 7 / 7,947 | 0.08808% | 1 |
| Positive control, simultaneous requests | 16 | 0 dBm, 16 s | 22 / 15,890 | 0.13845% | 30 |
| Positive control, 100 ms host stagger | 16 | 0 dBm, 16 s | 41 / 15,950 | 0.25705% | 0 |
| Simultaneous repeat 2 | 16 | 0 dBm, 16 s | 25 / 15,900 | 0.15723% | 25 |
| Staggered repeat 2 | 16 | 0 dBm, 16 s | 50 / 15,946 | 0.31356% | 0 |
| Simultaneous repeat 3 | 16 | 0 dBm, 16 s | 18 / 15,907 | 0.11316% | 18 |
| Staggered repeat 3 | 16 | 0 dBm, 16 s | 44 / 15,938 | 0.27607% | 0 |

All four recovered packets in the 0 dBm controls. Across these three runs per schedule, simultaneous requests recovered 65 / 47,697 completed transmissions (0.13628%) with 73 duplicate observations; staggered requests recovered 135 / 47,834 (0.28223%) with none. This small descriptive comparison is promising for reducing duplicate retained snapshots, not proof of a general or statistically established recall improvement. These are separate runs with potentially different start phase and cross-session calibration, not a calibration-identical efficacy comparison. Delays are host-side request spacing, **not RF synchronization**. Results remain far from continuous capture because each approximately 1 ms raw buffer takes roughly 410 ms to transfer at the configured UART rate. Four receivers do not remove that bandwidth limit.

An earlier low-power run collected valid evidence but the analyzer incorrectly required START's live `elapsed_us` field to equal zero; it was 7 µs. The original run remains marked failed. A separate, explicitly labeled corrected analysis yields 2 / 7,952 unique/completed. The source code confirms that field advances while formatting the reply; reset transmission counters and completion ordering are now checked instead. Fresh physical controls above passed the corrected analyzer.

## Viewer verification

The physical offscreen viewer displayed four distinct live CRC-valid receivers, then stopped, restarted and joined all workers. A restart defect that left overlapping retired status labels was fixed and regression-tested. A separate private test-harness teardown defect was reproduced in simulation and fixed by correctly processing deferred Qt deletion. The corrected physical two-session test exited cleanly; the earlier process crash is not counted as a clean pass. Screenshots and raw device paths remain private.

The viewer labels asynchronous captures and stale/error connections and excludes stopped/failed receivers from live combined power. Its waterfall is successive retained snapshots, not uninterrupted time; combined power is noncoherent diversity.

## Evidence boundaries

JSON files are reviewed numeric projections, not raw RF replay packages. Complete raw I/Q, wire records, source logs, device identities, calibration fingerprints and full recovery images remain private. Failures are retained beside successful trials. Software, diagnostic controls and additional verification are tracked in draft PR #7, stacked on unmerged preservation PR #6. Neither is merged by this work.
