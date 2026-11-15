# Single paused-capture research candidate

## Implemented

An **opt-in, single-capture packet extraction path** in the real ESP32 application. It captures 16,380 words using the established full-bank register sequence, restores memory ownership, copies the stopped input, runs the unchanged exact DFA, and returns framed results. `PEXGET` exports the same immutable input; `PEXDROP` or `STOP` releases it.

This recognizes only the known synthetic RFTX format: 16-byte payloads at 2 Mbps, sampled at 16 MS/s. It is **not** generic or Quest decoding, hopping support, continuous capture, or a replacement for normal raw-IQ GUI operation.

The build option defaults to **OFF**. Ordinary receiver commands, serial implementation, capability string, calibration constants and normal host code remain unchanged. Enabling the option adds a distinct research VERSION record and the explicit PEX command family. While an explicitly created retention lease exists, other application commands return busy until it is released or expires.

The host component is an offline wire parser and native verifier. It checks transport integrity, full decoder-result equality, and independently reconstructed observed bits and packet CRC. It contains no serial import or device-opening launcher.

## What passed offline

- Both default-OFF and opt-in-ON builds with the pinned SDK and compiler.
- **1,046 source tests plus 5 subtests.** These are shared host/source tests, not on-device GUI tests.
- **11 PEX verifier tests**, including three synthetic packet observations, cap-zero drop accounting, corrupted/truncated/duplicated frames, wrong identities, impossible timing and integer ranges, forged decoder results, and failed-attempt accounting.
- Wrapper lifecycle and calibration-lease mocks at **O0 and O2 with ASan and UBSan**. These cover allocation order and failures, lock contention/staleness, capture timeout, short count, guard corruption, DC changes, cancellation boundaries, input mutation, decode failure, expiry, generation limits and transfer failure. Mock assertions reject UART, allocation, yielding and full input copying while capture memory is mapped. LeakSanitizer was disabled for the ptrace environment; allocation/free accounting was checked explicitly.
- Static ELF checks: no allocated section overlaps the capture aperture or its instruction alias; the reserved-region descriptor is correct; new static state and the PHY mutex-handle variable are outside the aperture; default-OFF has no PEX symbols.
- The original DFA, header and prefix table match the frozen v6 source archive exactly.

The independent final review is recorded separately when complete. Native mocks are not peripheral emulation and provide no MCU timing, RF recall or live resource-admission evidence.

## Artifact identities

| Item | Identity |
|---|---|
| Base | Modified v9 source checkpoint; base commit `d23ddddeaabee46d340caba60b038f39946cd534`, plus archived changes |
| Base archive SHA256 | `dc1cc29803e24c20eaccc3e3885222f6930f9e9334e7ff8cc007ebf2a8526fae` |
| SDK | `25fe69f946311abdaf9ad56591f25fedbc20ac98` |
| Compiler | Xtensa `esp-16.1.0_20260609` |
| Opt-in variant | `esp32-paused-extract-research-v1`, PEX protocol 1 |
| ON application | 721,792 bytes; SHA256 `7227fb602a9b64e32e771c7b8048fe519f437b2247c03c8199f5b0e7953033ba` |
| OFF application | 715,584 bytes; SHA256 `71d8be85c8c845a9f67797756012838a9c106fffab088114af155f5a68e4a6a2` |

Embedded revision is `unknown`: the source archive has no Git metadata. Neither application is installed. The OFF build is a newly built control, not the byte-identical recovery image. Use the original verified per-board v9 recovery artifacts for restoration.

## Important limits

Read `CONTRACT-v4.md` and `LOCK-PREFLIGHT.md` for exact semantics.

The target-compiled context is **3,288 bytes**, plus a **65,520-byte input allocation**, before allocator overhead. Input is allocated first to avoid fragmenting the only suitable block; context failure frees it exactly once. Historical v9 tests allocated a full input successfully, but that does not establish availability in this image or current hardware. Before/after allocation snapshots are not continuous peak-heap measurements.

The calibration lease excludes only writers that honor the existing PHY mutex. It does not freeze modem interrupts or autonomous radio behavior. DC fingerprints are not a universal calibration epoch. PBUS and ROM I2C calls remain outside the lease; memory ownership is restored before unlock, and filter restoration follows unlock.

ESP-IDF reports stack high-water in **bytes**. The preliminary 1,024-byte rejection gate and static function frames are not complete task, libc or interrupt stack bounds. Heap objects and full runtime stack placement still require qualification.

Cancellation is checked at safe boundaries. The 20 ms capture wait and 100 ms decoder check are not preemptive guarantees under arbitrary scheduling delays. Body transfer has a 15 s deadline; the legacy terminal drain can add 1.5 s without polling STOP. Error accounting uses two such bounded terminal writes. A late STOP can therefore be processed after the current terminal completes. Deliberate UART idle periods make this an audit path, not a throughput benchmark.

A retention lease survives disconnect and serial `RELEASE`. It is freed by `PEXDROP`, `STOP`, or the next application command after 60 seconds; there is no background expiry timer. Missing terminal or memory-accounting lines mean incomplete evidence. A valid wire CRC is not packet air CRC, source truth, recall or sample-time coverage.

## Still untested on hardware

Live heap/stack admission, PHY-lock interaction with actual acquisition, timing and cancellation latency, UART/USB bridge behavior, normal GUI return, and actual RF packet recovery. No installation, serial access, RF transmission, default change, merge or publication occurred.

Before physical use: obtain supported access approval, ensure the user is awake and available for recovery, preserve exact per-board offsets and calibration/recovery evidence, and qualify one board at a time. Start with source-OFF controls, then bounded fixed-frequency known-source tests. Export and verify every initial capture. Finish with ordinary capture/GUI checks, guarded restoration to the original verified v9 image, and source OFF.

## Reproducibility and prior failures

`build-offline.sh` uses at most two compiler jobs and contains no flashing commands. `verify.py`, `test_verify.py`, `mock.c`, `lease-test.c` and `audit.py` provide the offline checks. Source, decoder and SDK pins are adjacent JSON files; raw logs and prior review snapshots are preserved.

Earlier checks caught missing source-package includes, an incorrectly global research variant, and a signedness error in the CRC argument. These were corrected rather than suppressed. An initial cap-zero mock assumed three drops; the unchanged decoder can count more hypotheses than unique packets, so the test now checks its actual semantics. Old unused-function compiler warnings remain. No decoder mathematics or historical RF result was changed to improve a score.
