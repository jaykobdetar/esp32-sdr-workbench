# Original-ESP32 optimized SDR firmware

Source-only GPL-3.0-or-later derivative of [ESPARGOS/esp-sdr](https://github.com/ESPARGOS/esp-sdr). This source's only supported target is **the original ESP32**, not ESP32-S2/S3/C-series. Other upstream backend files are retained for provenance, not advertised as supported by this release. The build catalog and configuration guard permit only `esp32`.

Features: protocol 6 RAW/CAP20/SPEC, finite DET1 and optimized DETPIPE1, exact DC-removed energy, previous-buffer overlap, full-aperture guard checks, full-size-only fused validation/copy, aligned CAP20 retention packing, fixed yielding, and a conditional ASCII END padding workaround for demonstrated CP2102 framing stalls. Diagnostics such as VCTEST/PROF1/FRAMEPROBE are not in the release command path. These are experimental undocumented receiver mechanisms, not calibrated RF instrumentation or a reliable transmitter-identification system.

See [build instructions](../docs/firmware-build.md), [source provenance](SOURCE_PROVENANCE.md), and [LICENSE](LICENSE). The current source variant is `esp32-pipeline-adaptive-q16-v3`; the actual revision/time are embedded honestly when built. Its Q16 background, gain/trigger telemetry and opt-in three-crop retention are host/compile checked but **not flashed or board-soak validated**. Published RF measurements describe the earlier optimized-v2 image. See the [remaining-validation guide](../docs/remaining-validation-guide.md). Build output is not expected to be bit-identical across paths, tool versions or build timestamps.

No firmware binaries, captures, device NVS, flash backups, credentials, recovery data or generated build caches are distributed here.
