# Where to make a change

The installed host tools, hardware-specific source, and preserved measurements
have different lifetimes. Start in the smallest layer that owns the behavior.
The public entrypoints below do not need to change when internals move.

| If you are changing… | Start here | Check it without hardware |
| --- | --- | --- |
| What happens when someone invokes `esp32-sdr` | [CLI routing and headless recorder](../sdr_research/cli.py). Studio, Bench, and the original viewer have separate windows; the recorder must not need Qt. Checkout launchers share [interpreter selection](../scripts/launcher-common.sh). | `tests/test_cli_studio.py`, `tests/test_launchers.py` |
| A setting, default or validation rule | [Lab config](../sdr_research/lab_config.py) owns per-device defaults and constraints. [Studio settings](../sdr_research/studio_settings.py) owns the portable document, including restrictions that only apply to Studio. [Lab session](../sdr_research/lab_session.py) owns the lifecycle and the checks involving multiple devices. | `tests/test_studio_settings.py`, `tests/test_lab_session.py` |
| Visual presentation | [Studio](../sdr_research/studio_gui.py), [Bench](../sdr_research/lab_gui.py), or [original viewer](../sdr_research/gui.py). All three use the same [capture inspection dialog](../sdr_research/capture_inspection.py); spectrum calculations live in [analysis](../sdr_research/analysis.py), not in the dialog. | `tests/test_studio_gui.py`, `tests/test_lab_gui.py`, `tests/test_gui.py` with offscreen Qt |
| A capture or summary crossing the serial boundary | Follow [protocol](../sdr_research/protocol.py) → the mode-specific detector, pipeline or stream parser → [acquisition worker](../sdr_research/acquisition.py). The [wire protocol](protocol.md) is a contract with firmware; a change to the GUI is not a reason to change it. | `tests/test_protocol.py`, the matching parser tests, `tests/test_acquisition.py` |
| What lands on disk | [Recording](../sdr_research/recording.py) constructs SigMF metadata, stages both files, then publishes data before metadata. Metadata is the commit marker. Session summaries instead replace one complete JSON document. | `tests/test_recording.py` covers concurrent writers, failed staging and rollback; `tests/test_studio_history.py` covers history. |
| ESP32 build inputs or exported artifacts | [Catalog](../firmware/firmware-targets.json) → [build driver](../firmware/tools/build_firmware.py) → [exporter](../firmware/tools/export_web_firmware.py). Release commands and export guards share one list of diagnostic probes. The compiled receiver is under [firmware/main](../firmware/main); [source provenance](../firmware/SOURCE_PROVENANCE.md) identifies vendored and historical code. | `firmware/tests/`; `python firmware/tools/build_firmware.py --matrix` just prints the catalog. Actual cross-compilation uses the pinned SDK in [firmware CI](../.github/workflows/firmware.yml). |
| nRF52840 packaging | [Transmitter build driver](../nrf52840-transmitter/host/build_firmware.py) archives inputs and records checksums; [UF2 conversion](../nrf52840-transmitter/host/make_uf2.py) encodes those bytes. The [updater](../nrf52840-transmitter/host/flash_uf2.py) validates the image; building it is **not** permission to install it. | `nrf52840-transmitter/tests/`; `python -m nrf_tx.build_firmware --version 0.2.2 --dry-run` prints a plan only. |
| Recalculating published results | Start with the [script index](../scripts/README.md) and [evidence index](evidence/README.md). Verifiers consume sanitized artifacts. Campaign runners can drive devices: do not substitute a live run for an offline check. | `tests/test_source_provenance.py` and the corresponding evidence tests under `tests/` |

## What to leave alone

- [RF source provenance](rf-source-provenance.json) pins specific scripts, tests
  and a host module by content, not just by filename. Formatting changes can
  invalidate a result. Add a new implementation for new analyses instead of
  rewriting the code that produced a published measurement.
- [November 14 overlays and images](../experiments/nov14-research/README.md)
  reconstruct earlier source at specific commits. [Combined-bank](../experiments/combined-core-banks/README.md)
  and [retention](../experiments/retention/README.md) experiments are opt-in,
  not copies to keep in sync with the default firmware.
- Keep package names and entrypoints in [pyproject.toml](../pyproject.toml) in
  mind: `scripts/` installs as `nrf_campaigns` and transmitter `host/` installs
  as `nrf_tx`. Add new public non-package resources to [the explicit sdist
  allowlist](../MANIFEST.in); do not broaden it to include local recordings,
  device dumps or downloaded SDKs.

## Before opening a PR

From a clean checkout with a supported Python, install `python -m pip install -e '.[dev]'`.
Run `ruff check .`, `ruff format --check .`, and
`QT_QPA_PLATFORM=offscreen python -m pytest -q`. Pytest collects all three
test directories; host C tests need a compiler. For changes near frozen
research, also follow the [separate research-preservation checks](../.github/workflows/research-preservation.yml)
in a full clone. For packaging changes, [build and inspect both distributions](source-distribution.md).
A green host suite or successful cross-compile is not a board measurement.
