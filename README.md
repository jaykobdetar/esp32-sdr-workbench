# ESP32 SDR Research Workbench

**A native RF viewer and optimized, burst-aware energy detector for the original ESP32.**

Explore the ESP32 receiver's raw I/Q, inspect spectra and recorded events, and compare honest acquisition duty with end-to-end host coverage. This project builds on [ESPARGOS/esp-sdr](https://github.com/ESPARGOS/esp-sdr), adding a Python/Qt workbench and an experimental guarded acquisition/processing pipeline.

> **Not continuous SDR.** Reception has gaps. Detections are unclassified candidate-positive captures, not decoded packets. Power is relative dBFS, not calibrated dBm.

![Native viewer operating with the optimized firmware on a real ESP32](docs/viewer-hardware.png)

*Genuine hardware session, not simulated data: original ESP32 over CP2102 UART, 2440 MHz, 16 MS/s, optimized pipeline. The plotted trace is the strongest retained I/Q capture, not a continuous live stream. The screenshot was captured during the final hardware validation; its status line is an intermediate run, not the final benchmark aggregate. It was grabbed by the GUI hardware smoke harness, which constructs the window directly and so shows the desktop's light theme and the pre-indicator event table; the documented launcher applies a dark palette and now adds an ADC-endpoint column.*

## What you get

- **Native desktop viewer:** spectrum, capture-index waterfall, frequency survey, heuristic occupancy, event inspection and SigMF replay.
- **Three acquisition modes:** raw snapshots, experimental DET1 and the optimized finite pipeline.
- **Event recording:** structured JSON summaries for every detector run, including no-event runs and the requested gain mode, gain index and bandwidth; CRC-checked SigMF I/Q for the strongest qualifying capture per run.
- **Saturation indicator:** every displayed or recorded capture reports the share of samples sitting on an ADC endpoint code, and 1% or more is flagged as likely clipping.
- **Truthful duty indicators:** local nominal RF, analyzed and post-warmup decision exposure, plus separate host-session values including transfer and recording gaps.
- **Complete firmware source:** guarded memory ownership, exact integer energy processing, overlapping acquisition/processing, fused full-size validation/copy and faster exact CAP20 packing.
- **No automatic flashing:** the viewer does not replace firmware or change operating-system security settings.

## Measured result

On **one ESP32-D0WD-V3 rev. 3.1 with 4 MB flash**, at 2440 MHz, nominal 16 MS/s, 16,380 samples, manual gain index 40, bandwidth setting 12 MHz and a 4× adaptive power threshold:

| Final-image condition | Nominal local RF duty |
| :--- | ---: |
| Legacy DET1 control, no retention | 29.759–29.773% |
| Optimized pipeline, no retention | **62.925–62.958%** |
| Legacy DET1 control, retention enabled | 29.754–29.773% |
| Optimized pipeline, retention enabled | **62.708–62.834%** |

An earlier separately archived DET1 v2 build measured about **32.1%**, so the optimized result is approximately **1.96× the historical nominal listening time**. The same-image control above is reported separately; compiler layout and firmware composition affect timing.

A 24 × 5-second retained-event soak processed **73,745 captures**, with stable heap, no reported errors and valid retained/post-run raw CRC checks in every run. Host-run RF duty was **57.687–57.871%**, including command and retained-I/Q transfer time but excluding the separate raw health checks between runs. Shorter GUI runs have more overhead: five 1-second runs ended around **62.42% local RF duty versus 42.93% host-session RF duty** under the GUI's hardware-gain defaults. The 62.42% is the last run's local value; 42.93% is cumulative session duty.

See [validation and limitations](docs/validation.md) for test coverage, negative results and what these numbers do **not** establish. The [published evidence](docs/evidence/README.md) includes all 12 A/B summaries, 24 soak runs with heap replies, five GUI summaries, historical baseline trials, build identity and microbenchmarks. Recalculate the headline numbers offline with `python3 scripts/verify_evidence.py`.

## Quick start: viewer

Python **3.10+** and a desktop environment are required. Linux was tested; other platforms are not hardware-validated by this project.

```bash
git clone https://github.com/jaykobdetar/esp32-sdr-workbench.git
cd esp32-sdr-workbench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
./scripts/launch.sh
```

The installed command `esp32-sdr` also launches the viewer. Dependencies are NumPy, pyserial, PySide6 and pyqtgraph. On Python 3.10 and 3.11 the install deliberately selects PySide6 older than 6.12: PySide6 6.12.0 aborts the viewer within seconds on those interpreters, and is only safe on Python 3.12 or newer. `requirements-lock.txt` records the tested host versions; use it when recreating that environment, subject to wheel availability for your Python/platform.

1. Connect a compatible original ESP32 with this project's firmware. Close other serial monitors/viewers first.
2. Select its port, for example `/dev/ttyUSB0`. The tested physical UART runs at **1,000,000 baud**.
3. Start with **2440 MHz**, **16 MS/s**, **16,380 samples** and **Experimental optimized pipeline**. Use a 1-second run for responsive updates; longer finite runs amortize serial transfer overhead.
4. Enable **Record events / detector runs**, then **Start**. Use **Stop** before opening another serial application.
5. Inspect a saved event or replay its SigMF recording. Recordings are local and ignored by Git.

The optimized mode verifies firmware capabilities and exact option readback; it does not silently substitute a different kernel. It selects kernel 3, acquisition option 3, clear option 1 and fused-copy option 1. Raw snapshots and legacy DET1 remain available. The clearly labeled simulated mode is for UI exploration, not performance measurement.

If Linux denies access to the port, arrange serial-device permission using your distribution's documented procedure. Do not run the whole GUI as root. Qt may require your distribution's desktop/XCB libraries; headless systems cannot display the interactive GUI without a display server.

## Build and install firmware

See **[firmware build and flashing](docs/firmware-build.md)** for the pinned ESP-IDF revision, configuration, compilation and deliberate flashing steps. Back up your own device before flashing. Do not use another person's full-flash image, and do not publish backups: they can contain stored settings or credentials.

The optimized path is validated on the **original ESP32 only**, not ESP32-S3/C3/C6 or other family members. Inherited upstream ports remain in the source for completeness, not as a claim of equivalent optimization or validation. The GUI checks capabilities rather than assuming every board implements the same commands.

## How the pipeline works

```text
finite RF acquisition → stop and restore ownership → validate/copy
                                                       ↓
next finite acquisition overlaps exact energy processing of the prior private copy
                                                       ↓
run summary + optional strongest capture → CRC-checked serial transfer → viewer
```

Full aperture bounds/sentinels, receiver restoration and immutable-copy ownership remain enforced. The pipeline does not read the aperture while RF owns it. Incomplete 64-sample tails and the first 16 warmup captures do not contribute to decision exposure. Faster cadence changes which RF windows are observed and how the per-capture adaptive background evolves in wall time.

## Scope and limitations

- Duty is `successful samples / configured sample rate / complete run wall time`, a **nominal aperture estimate**, not externally measured RF arrival coverage.
- Only one board was benchmarked. Independent multi-port viewing is not synchronized multi-board coverage.
- No packet decoder, packet recovery rate, calibrated sensitivity, false-positive guarantee or exact RF event timestamps are provided.
- A candidate count can include multiple positive captures of the same transmission. Only the strongest qualifying I/Q capture per detector run is retained.
- The waterfall advances per displayed capture, not uniform RF time. UART transfer adds substantial gaps.
- BLE OFF/ON validation was inconclusive in ambient RF; no ground-truth transmitted packet count/timing was available.
- The detector flags a large and variable share of captures. In the [published runs](docs/evidence/README.md), 5–31% of post-warmup captures were candidate-positive in the manual-gain A/B trials, 6–48% in the soak and 38–47% in the hardware-AGC GUI runs. Nothing here separates real band activity from gain steps or threshold artefacts.
- The adaptive background only updates on captures that are *not* flagged. A sustained rise in level therefore keeps every later capture positive until the finite run ends and the next run re-warms.
- Energy is measured in ADC units. Under hardware AGC the firmware does not report the gain in use, so energies are not comparable across gain steps; under manual gain index 40 the recorded background was only 2–34 ADC² units, where integer rounding of the background is coarse.
- Reported dBFS is relative to one full-scale component, so a complex sample can read up to +3 dBFS. Values near or above 0 dBFS, or a flagged ADC-endpoint share, mean the capture is at the converter's rails.
- The screenshot-session retained captures have Q-component endpoint occupancy of 0.20–12.76%, consistent with a saturation/clipping concern. [Published counts](docs/evidence/gui/clipping-counts.json) do not establish its cause; no controlled manual-gain/AGC or terminated-input comparison was performed.
- Undocumented receiver/debug behavior is experimental. Use only on hardware and signals you are authorized to investigate; respect applicable radio/privacy laws.

## Repository layout

```text
firmware/       Complete optimized firmware source and build configuration
sdr_research/   Native viewer, protocol, processing and recording code
scripts/        Viewer launcher, offline evidence verifier and endpoint counter
tests/          Small selected regression suite (not the entire research archive)
docs/           Build guide, serial protocol, screenshot and validation summary
docs/evidence/  Curated benchmark summaries, build identity and diagnostic sources
.github/        CI: lint, format check and both host test suites
```

Historical lab clients (`profiling.py`, `pipeline_profile.py`, `validate_copy.py`), other-chip backends and vendored ESP-DSP are kept deliberately; see [diagnostic provenance](docs/diagnostic-provenance.md). The serial commands the release firmware answers are described in [the protocol document](docs/protocol.md).

This public release intentionally excludes original device flash/NVS, recovery images, personal machine configuration, raw RF recordings, large uncurated campaign logs and complete superseded experimental firmware trees. A curated sanitized evidence supplement and small, explicitly historical diagnostic source selections are included under `docs/evidence/`. The full private research originals are preserved separately.

## Attribution

Receiver firmware derives from **[ESPARGOS/esp-sdr](https://github.com/ESPARGOS/esp-sdr)** at upstream commit `a8eaac1758d7567be9d6e82698f36f025573cb62`. Its license and notices are retained in `firmware/`. This repository is an independent experimental extension, not an official ESPARGOS release. See the firmware build guide for third-party requirements and provenance.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). Upstream notices are retained. Vendored ESP-DSP remains Apache-2.0 under its own notices. ESP-IDF and its toolchain are external dependencies under their respective licenses. This release contains source, not proprietary vendor radio-library binaries or device flash dumps.

## Run selected tests

```bash
python -m pip install -e ".[dev]"
ruff check . && ruff format --check .
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m pytest -q firmware/tests
```

The viewer and evidence suite has **160 tests**; the firmware host suite has 6 tests plus 5 subtests and needs a host C compiler with UndefinedBehaviorSanitizer. [CI](.github/workflows/ci.yml) runs the lint, the format check and both suites on Python 3.10 and 3.13 for every push and pull request. These software tests require no connected board and are not a replacement for hardware validation: CI does not build the firmware, which needs the pinned ESP-IDF described in the build guide. Qt needs the system EGL/XCB libraries even for offscreen runs (`libegl1` on Debian/Ubuntu).
