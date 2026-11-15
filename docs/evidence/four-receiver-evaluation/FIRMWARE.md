# Four receivers: firmware decision

The four-receiver experiment uses **unmodified `esp32-core1-banks-experimental-v9`**. Adding receivers does not require changing the acquisition scheduler: every board independently accepts its own absolute device-clock deadline and period. The new work belongs in host clock alignment, start staggering, evidence accounting, and display. This avoids silently promoting experimental bank diagnostics or changing timing while measuring a new topology.

## Existing interface used

- `CLOCK?` and `TIMEDCAP` support host probes and RF-anchor captures. Host receipt time is not an RF timestamp.
- `DSTREAM deadline_us duration_ms period_ns yield_phase ratio_milli` accepts 1–600000 ms and 1600000–10000000 ns. The deadline must be 10000–5000000 us ahead in that board's clock.
- `DSTREAMIDLEWAKE` advertises yield selector 34. Period fractions accumulate at nanosecond resolution; actual trigger timestamps remain integer microseconds.
- Streams contain 48-byte CRC-protected records, terminal accounting, skipped/late/overflow telemetry, and cooperative STOP. Missing or inconsistent records invalidate a trial.
- There is no array of two receivers or paired role in this firmware. Host commands translate a common experimental schedule into each board's independent clock. Four receivers do not become phase coherent.

`DSTREAM` discards raw captures after energy processing. Its nominal capture-window union cannot prove continuous retained I/Q, packet recovery, or real Quest compatibility. `DSTREAMIQ` delivers only sparse snapshots. The diagnostic `BANK*` family remains separate and is not made a continuous viewer backend by this experiment.

## Independent reconstruction check

Reconstructed the existing `core-bank-v9` snapshot from base `d23ddddeaabee46d340caba60b038f39946cd534` using the hash-checked materializer. Compiled with pinned ESP-IDF `25fe69f946311abdaf9ad56591f25fedbc20ac98`. Firmware host regressions: **71 passed, 5 subtests passed**. This includes bank ownership/cleanup, scheduling, NVS preservation, command validation, and version tests. These are host/mock tests, not RF qualification.

The fresh app is 715584 bytes, SHA-256 `6e808a35f3e417defd3e8de6152cdee651b71dc241787b50957260efba6d88a0`. It is a build verification artifact and has not been flashed by this verification task. A reconstructed tree has no original Git revision and receives a fresh build timestamp; this is not a bit-for-bit reproduction claim.

The preserved app is 715632 bytes, SHA-256 `8a8b9036a012d80017d05dd494acf8080d825f4b2149d587c70d7f778ee3b2b5`. Use that exact previously verified application for controlled baseline comparisons when board compatibility and recovery have been established. Board-specific installation and RF results must be reported separately.

Never use the build export's generic flash command on an existing board: it includes a bootloader and partition table. Inspect each board's actual partition layout, keep independently verified recovery/calibration, select its actual app offset, and flash only the approved application region. No complete flash backup or private device identity belongs in public evidence.

`firmware-manifest.json` records the reconstructed firmware file hashes and both application hashes. The original snapshot and default firmware source were not modified.
