# Combined core isolation and alternating banks

## Answer

**The earlier experiments did not combine them. This experiment does, and deliberate staggering makes the combination substantially better at timing. It still does not demonstrate 100% packet capture.**

The earlier bank image was explicitly unicore; earlier core1 v3 used full-size captures. Here the capture/detector command loop runs on CPU1 while Wi-Fi/system tasks remain on CPU0, and the MAC alternates the lower/upper 32 KiB banks. The CPU validates/processes/clears the inactive bank while the other captures. This is not an acquisition-only CPU1 task plus a new CPU0 DSP worker: processing already overlaps hardware acquisition on the same hot-path core.

## Matched design

The unicore v5 control and combined v5 use byte-identical C sources, the same early startup buffer reservation, the same full-word and guard validation, and the same finite bank implementation. Only CPU configuration and build label differ. Both devices were tested with control, combined, then control again. First control and combined each ran 30 paired trials; repeat control ran 10. Every trial captured 1,024 half-sized windows per receiver. Trials covered free-running and 800/820/850/900 us periods, interleaved ON/OFF and reversed order across repeats. This is 70 paired finite trials, 143,360 individual captures, not one uninterrupted stream.

The scheduled mode uses RF-clock-derived half-period staggering and compensates relative clock drift. Eight independent shared known-packet capture pairs bracket each campaign on either side. Leave-one-capture-pair-out errors were 1.832 us (control), 2.180 us (combined), and 1.033 us (repeat control). Only full known payload, address and over-air CRC qualify as anchors. These residuals are empirical consistency checks, not certified uncertainty limits.

## Timing results

Ranges below cover all six first-control or combined trials at each period.

| Period | Control nominal sample union | Combined nominal sample union | Control full-100-us opportunity | Combined full-100-us opportunity |
|---|---:|---:|---:|---:|
| 800 us | 93.2435–98.4418% | 100.0000–100.0000% | 86.6072–95.3280% | 99.9205–99.9515% |
| 820 us | 98.8307–99.4143% | 100.0000–100.0000% | 96.4210–97.8480% | 98.7408–99.7657% |
| 850 us | 99.6061–99.7080% | 100.0000–100.0000% | 95.8197–96.3070% | 96.8351–96.8858% |
| 900 us | 99.7486–99.8060% | 100.0000–100.0000% | 91.1413–91.2361% | 91.5051–91.5061% |

At 800 us, worst observed scheduled lateness fell from 1,721.878 us to 30 us; maximum overlapped work fell from 930 us to 741 us. The repeated unicore control again exhibited gaps and worse full-packet opportunity, supporting that the scheduling improvement was not simply a lucky first comparison.

**No nominal sample holes were observed in the 24 scheduled combined trials.** Each scheduled trial spans only 0.8192–0.9216 seconds. This finite trigger-timestamp result is not a calibrated RF guarantee, a long-duration stability test, or a delivered-packet recall result. A hypothetical 100 us packet must fit in one capture; adjacent windows from different boards cannot be spliced into a coherent packet. The best tested period, 800 us, still yielded only 99.9205–99.9515% full-100-us opportunity. Assuming 20 us error at each endpoint reduces that opportunity to about 92.94%. The 20 us scenario is a sensitivity assumption, not a measured bound. Shorter banks create more packet-boundary exposure.

**Free-running was a regression:** combined nominal union was only 67.54–80.14%, versus 84.65–88.32% control (87.21–88.67% on control repeat). Two more-deterministic receivers can overlap their windows too much. Core isolation and banks alone do not coordinate the receivers; deliberate phase scheduling is essential.

## Whole-session gaps

At 800 us, complete host command/readout coverage for the combined build was only 42.62–49.11%. The entire combined measurement session, including initial/post RF anchors, all waits, UART trace and I/Q readout and inter-trial gaps, was **26.4947% nominal coverage**. Control was 28.1941%; repeat control 21.1513%. The campaign lengths and numbers of anchor attempts differed, so these whole-session percentages are not an isolated firmware speed comparison. No setup or readout gaps were hidden. Host mapping uses USB-midpoint clock estimates, not a calibrated host/RF time reference.

## Retention and actual packets

Each trial retains only the final 8,188-sample snapshot from each board, not all captures. Trace and snapshot CRCs, all payload-word checks and all four guards passed. The source was bounded, known RFTX, 2 Mbps, 16-byte payload, 2440 MHz, 0 dBm, 1 ms nominal interval with 113 us jitter, fixed seed. It was stopped after the full command/readout session; completed transmissions during waits/readout are deliberately included in the denominator.

| Campaign | Unique full packets delivered | Completed source transmissions | Full-packet OFF matches |
|---|---:|---:|---:|
| Unicore control | 7 | 23310 | 0 |
| Combined | 9 | 23307 | 0 |
| Unicore repeat | 2 | 7768 | 0 |

A packet requires full known payload, address and air CRC, and is deduplicated within each source START. These deliberately sparse output counts do not establish improved receiver sensitivity or conditional packet recall. In particular, 9 versus 7 packets is not evidence of an end-to-end breakthrough. OFF controls tested only the retained snapshots for packet identity; finite zero matches do not establish a zero false-positive rate. Energy observations were not treated as identified packets.

## Correctness and safety

- Both cores/configurations passed inactive-bank read/write integrity, ordinary/retained finite pipeline modes, malformed-argument rejection and cooperative STOP-before-start checks. Across the three campaigns there were 96 inactive-bank hardware trials. Calibration fingerprints remained stable within every campaign.
- Full final combined host suite: **1,028 passed, 5 subtests passed**. After the last packaging allowlist change, all 10 affected tests passed; Ruff and diff whitespace checks passed. The first full suite caught a missing source-distribution header allowlist entry, which was fixed and rerun. The initial command-lifecycle mock overwrote the success header with its terminal line; that test harness was corrected and rerun.
- Mocked fault tests cover corrupted bank guards, stale calibration, timeout, allocation failure, invalid/deadline bounds, STOP, ownership restoration and retained-buffer release. They check that explicit PHY/allocator/UART calls in the bank path occur only with CPU ownership. Hardware tests do not claim exhaustive fault injection or long-term concurrency proof.
- The MAC aperture stays limited to the vendor-identified two pools. No active-bank CPU read, live-ring assumption, reduced validation, watchdog disabling, mass erase, NVS erasure, bootloader/partition-table replacement, or cross-board calibration copying was introduced. The rejected fused kernel was not used for the comparative trials.
- Application writes used each verified device identity, separate physical USB path and partition table: receiver A offset `0x10000`, receiver B offset `0x100000`. Each write had a complete device-verified recovery snapshot and verified unchanged non-app flash. SDK calibration refresh at boot is distinct from those non-app write checks. Private identities, NVS and flash snapshots are not included here.
- Both original v7 applications were restored and verified. Both receivers passed final full raw and retained-capture CRC tests. Hardware AGC, LPF AUTO and background policy 2 were restored; receivers are idle on the 2440 MHz lab channel. The nRF remains v0.2.2, healthy, zero errors, stopped, with its initial operational configuration restored. No desktop/network changes or extra hardware were used. Nothing was merged or published.

## Recommendation

The combined path is worth further development, with deliberate staggering around the tested 800 us period. It is a timing candidate, not a production continuous receiver. The next meaningful step is a bounded on-device packet decoder with CRC/sequence output, plus a genuinely persistent paired bank stream and long-duration drift/recalibration/restart testing. The current UART cannot deliver continuous 16-MS/s, 20-bit I/Q: that is 40 MB/s per receiver against at most 100 kB/s payload at 1 Mbaud 8N1. Making packets or validated decimation the output would address this bottleneck; it has not been implemented or qualified here.

## Reproduction and artifacts

This is an opt-in experiment. Default v7 firmware is unchanged. See the [experiment instructions](../../../experiments/combined-core-banks/README.md) for temporary source preparation, host tests and deliberate build commands. The source patch includes the exact measured firmware C changes; publication adds a guarded collector entry point and offline verification without touching hardware.

Run `python scripts/verify_combined_banks.py` to recompute trace CRCs, clock fits, sample-window union, full-packet opportunities, endpoint erosion, whole-session denominators and known-packet CRCs. The compressed evidence contains all capture trigger/energy rows, host clocks and known source-packet proofs. Raw I/Q is not published, so this verifies archived packet bytes and transport evidence, not fresh demodulation or RF sensitivity.

The tested source commit and current-main publication base have identical trees. Build labels and exact application hashes are in `application-versions.json`; measured C source hashes are in `shared-source-identity.json`. New CI builds have different build metadata and are not claimed byte-identical to hardware-tested images. Private recovery material remains local. No application or recovery binaries are included in the PR.
