# Build the original-ESP32 firmware

Current source is **`esp32-dual-sparse-iq-experimental-v7`**, the experimental
streaming firmware in this draft PR, not the historical adaptive v8 release.
The build below selects this current source by default. Its v7 review follow-up
moves cooperative scheduled waiting before acquisition setup and sends the full
capability line without the 255-byte formatting limit. See
[sparse I/Q](sparse-iq-stream.md) and the [review follow-up](pr4-review-follow-up.md).
The earlier v6 measurements do not establish v7 timing or performance.

The pre-stream adaptive-v8 source is preserved at commit
`2c06109317d0ad13af5f0273f5ca12e5befc2e0d` (the PR's current `main` base). To build
that source instead, use a separate detached worktree at that commit. This PR
does not tag, merge, rewrite history, or move historical evidence to LFS/releases.

Historical adaptive lineage: V5 added fail-closed NVS startup and strict SPEC parsing to v4. V6 also rejects embedded NUL at the shared serial line boundary. V7 adds the runtime [background-rule selector](protocol.md#background-rule-selector-v7) and idles, instead of rebooting, when NVS initialization fails. V7 passed the [exact-release board evaluation](evidence/v7-evaluation/README.md), including a 30-minute soak. Packet-retention superiority was not established. V8 fixes the malformed-selector parsing issue that evaluation found, and is otherwise identical; it is compiled in CI and host-tested, not board-tested.
See the [review fixes and validation limits](safety-review-fixes.md).
The earlier identified v4 build passed a [bounded passive smoke check](review-follow-up.md),
not a soak or RF-performance validation.
Historical optimized-v2 measurements do not validate this new detector. See the
[remaining-validation guide](remaining-validation-guide.md) before board trials.

## Scope and pins

Only original ESP32 is supported by this optimized release. Do not flash it to ESP32-S2/S3/C-series. The development hardware was an original ESP32 with a CP2102 UART bridge; the profile uses UART at 1,000,000 baud and uses a 2 MB flash-size setting and the SDK default 1 MB factory-application partition (boards need at least 2 MB flash). No hardware flashing is performed by the build command.

Pinned upstream SDK commit: `25fe69f946311abdaf9ad56591f25fedbc20ac98` from https://github.com/espressif/esp-idf, development 6.2. The tested Xtensa compiler is `xtensa-esp-elf-gcc (crosstool-NG esp-16.1.0_20260609) 16.1.0`. Use the pinned SDK's own tool installer; do not substitute an arbitrary stable/latest IDF. The build script verifies the exact SDK Git commit before compiling. ESP-DSP source at `a53a0756833c045311ea1d79a2badf495cdfde4c` is already vendored with its Apache license; no submodule initialization is needed for this package.

## Clean setup and build (Linux shell)

Install Git, CMake, Ninja, a C/C++ compiler and Python 3 with venv support as required by ESP-IDF. Then, outside this repository:

```sh
git clone https://github.com/espressif/esp-idf.git esp-idf
cd esp-idf
git checkout 25fe69f946311abdaf9ad56591f25fedbc20ac98
git submodule update --init --recursive
export IDF_TOOLS_PATH="$HOME/.espsdr-idf-tools"
./install.sh esp32
. ./export.sh
```

From the public repository root, with that environment still active:

```sh
python firmware/tools/build_firmware.py \
  --profile esp32 \
  --version "$(git rev-parse HEAD)" \
  --jobs 4 \
  --build-root /tmp/esp-sdr-build \
  --output /tmp/esp-sdr-artifacts
```

Use a fresh output directory for each build: the exporter refuses to overwrite an existing profile. Build outputs and export manifests are deliberately outside the repository. `firmware/sdkconfig.defaults.esp32` is the authoritative source configuration; generated sdkconfig is local output. No credentials, device calibration/NVS or complete flash images are needed to compile. Do not publish your device flash/NVS backups.

`VERSION?` embeds the actual source revision (or `unknown` without Git), UTC build time, target and `firmware_variant` read from `firmware/FIRMWARE_VARIANT` (currently `esp32-dual-sparse-iq-experimental-v7`). The variant is a truthful source-family identifier, not a replacement for the Git revision. Rebuilding changes timestamps and may change layout; do not equate an arbitrary rebuild with an already measured binary.

## Manual flashing: backup first, then choose the correct path

These commands operate on your board. Close serial viewers first and replace PORT with its verified serial device. Do not run them on a different ESP32-family chip. Stop if flash encryption or secure boot is enabled, or the bootloader/partition layout is unknown: this generic workflow is not a secure-device recovery procedure.

```sh
PORT=/dev/serial/by-id/YOUR_VERIFIED_BOARD
python -m esptool --chip esp32 --port "$PORT" chip-id
python -m esptool --chip esp32 --port "$PORT" flash-id
```

Read the detected flash capacity. The following 4 MB value is only an example; replace it with the detected size before reading. Save the backup outside this repository, privately. It can contain credentials, MAC addresses and device-specific calibration.

```sh
umask 077
mkdir -p "$HOME/private-esp32-backups"
FLASH_BYTES=0x400000  # Example: 4 MB. Use YOUR detected capacity.
BACKUP="$HOME/private-esp32-backups/before-update-$(date -u +%Y%m%dT%H%M%SZ).bin"
python -m esptool --chip esp32 --port "$PORT" read-flash 0 "$FLASH_BYTES" "$BACKUP"
sha256sum "$BACKUP"
```

Verify the saved file size equals FLASH_BYTES and retain the hash and backup. Do not upload it. A backup alone is not a tested recovery procedure, especially on encrypted/secure-boot devices.

### Existing compatible layout: application only

First verify the existing bootloader uses the standard partition-table offset 0x8000. If it does not, stop and use the board's documented layout. Decode the existing and newly built partition tables, then compare them:

```sh
python -m esptool --chip esp32 --port "$PORT" read-flash 0x8000 0x1000 "$HOME/private-esp32-backups/current-partition.bin"
python "$IDF_PATH/components/partition_table/gen_esp32part.py"   "$HOME/private-esp32-backups/current-partition.bin" /tmp/current-partition.csv
python "$IDF_PATH/components/partition_table/gen_esp32part.py"   /tmp/esp-sdr-build/build-esp32/partition_table/partition-table.bin /tmp/new-partition.csv
diff -u /tmp/current-partition.csv /tmp/new-partition.csv
```

Proceed only after confirming matching layout and compatible bootloader/security settings, with an application partition large enough for the image. The clean build used the SDK's default table: NVS at 0x9000 (24 KB), PHY init at 0xf000 (4 KB), factory app at 0x10000 (1 MB). The legacy repository-level partitions.csv is NOT the active default for this profile; inspect the generated table rather than assuming.

```sh
idf.py -C firmware -B /tmp/esp-sdr-build/build-esp32 -p "$PORT" app-flash
```

`app-flash` writes the application, not a new bootloader/partition table or device NVS. It can rebuild first; use the final flashed image's metadata and checksum for subsequent measurements. Do not use it to force an incompatible partition layout.

### Fresh board or explicitly approved layout installation

For a verified fresh board, or after separately deciding to replace an incompatible layout and retaining a recovery backup, inspect `/tmp/esp-sdr-build/build-esp32/flash_args` and the exported manifest. Then:

```sh
idf.py -C firmware -B /tmp/esp-sdr-build/build-esp32 -p "$PORT" flash
```

This installs the build's bootloader, partition table and application at their listed offsets. It does not request full-chip erase, but changing a partition table can make existing data inaccessible. Never add `erase-flash` or write an unrelated full-flash/NVS image as a shortcut. Preserve board-specific calibration and credentials. Confirm VERSION, raw-capture CRC and finite-run behavior before relying on the board.

## Packaging verification

The source-only public tree was clean-built on 2026-11-11 with the pinned SDK and compiler, using fresh build/export directories outside the repository. The selected host suite passed 6 tests and 5 subtests. No serial port was opened and no device was flashed during public packaging. A new build's metadata/layout must still be verified; this is not a claim that every board or future toolchain is validated.

## Small host regression suite

```sh
python3 -m venv /tmp/esp-sdr-test-env
/tmp/esp-sdr-test-env/bin/pip install pytest
/tmp/esp-sdr-test-env/bin/python -m pytest -q firmware/tests
```

A host C compiler with UndefinedBehaviorSanitizer is needed for C arithmetic/guard checks. CI runs this suite on every push and separately compiles the release firmware and the historical retention experiment against its immutable base. The nRF52840 application is also compile-checked. These tests do not open serial ports or flash hardware. They are a small release subset, not a substitute for receiver ownership, CRC and soak checks on an actual device.

## Runtime and safety

Original-ESP32 startup now fails before radio initialization on **any** NVS-init
error, including full/incompatible storage. It prints a preservation/recovery
message and idles without starting the radio or rebooting. It never erases NVS as an automatic repair. Do not bypass the
failure with an erase: retain a private backup and review the matching firmware
and a specific migration/recovery procedure first. This error path is checked
with host fault injection, not by corrupting device calibration on hardware.

Optimized finite pipeline selection is explicit: `PIPEKERNEL 3`, `ACQOPT 3`, `CLEAROPT 1`, `PIPECOPY 1`, with readback and END-policy verification. Defaults remain 0 for compatibility. Fused copy activates only at 16,380 samples; smaller lengths use the separate path. Full guard coverage, calibration/restoration, finite-command limits and fixed every 32-capture yielding remain. Do not disable those safeguards to chase a throughput number. Nominal RF duration is sample_count/sample_rate, not CPU completion latency; overlapping timing fields cannot simply be added.

Keep a verified compatible recovery firmware and follow the exported offset/partition metadata when manually flashing. Never perform full-chip erasure or overwrite device calibration/NVS as part of ordinary application updates. This package contains no recovery/device backup. Only claim performance from the exact binary and settings actually measured.

## Licenses

Firmware derivative: GPL-3.0-or-later. ESP-DSP and the retained ESP-IDF-derived compatibility files: Apache-2.0. See `firmware/SOURCE_PROVENANCE.md` and component license files. The external SDK includes separately licensed binary libraries; review vendor terms before redistributing compiled firmware.

## Current adaptive source versus historical measurements

The current `firmware/FIRMWARE_VARIANT` is `esp32-dual-sparse-iq-experimental-v7`.
The build example labels the artifact with the source commit; `VERSION?` separately
embeds this variant. Neither is a performance claim for this source.
The [adaptive evaluation](evidence/adaptive-evaluation/evaluation-report.md) separately
tested the unchanged released-v3 image and an instrumented, tie-fixed candidate.
Only the latter received the 30-minute soak. The historical adaptive-v8 source includes that tie
fix, with `DETPIPE_HEALTH` OFF by default; a newly built default-off binary still
needs its own release-image validation. Historical retention CI builds its pinned
base with the archived patch. Read [adaptive detector](adaptive-detector.md) and
[optional telemetry](pipeline-health-telemetry.md) before evaluating a new image.
No recovery image or installed radio firmware is replaced by a compile-only build.
