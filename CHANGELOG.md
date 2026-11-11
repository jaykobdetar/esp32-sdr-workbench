# Changelog

## Unreleased

- Build ESP32 release and historical retention firmware, and nRF52840 firmware in CI.
- Collect transmitter parser, schedule, stop-control and CRC host checks with pytest.
- Add weekly latest-dependency compatibility checks, including unpinned Qt smoke tests.
- Package transmitter tools as `nrf_tx` and campaign helpers as `nrf_campaigns`.
- Use one host version source, `sdr_research/_version.py`.
- Add a Qt-free recorder engine and bounded headless recording CLI; publish run
  summaries atomically after retained captures are saved.
- Add an editable serial-port picker and AGC/detector warning.
- Recompute evidence intervals and exact small-sample permutation tests.
- Add a C-checked detector reference model and explicitly versioned Q16 background
  adaptation; existing measured evidence still describes its original firmware.

- Add opt-in three-crop retention, gain-register snapshots and device trigger timestamps.
- Run 24 matched AGC/manual ON/OFF trials on unchanged installed firmware; publish scrubbed counts and explicit small-sample limits.
- Replace the README image with a genuine launcher screenshot, clearly labelled synthetic.

No on-board validation of the new adaptive firmware, release tag or published release is implied by this entry.

## 0.1.0 (source baseline)

Initial native viewer, optimized ESP32 source, nRF52840 tools and scrubbed evidence.
This historical version was not tagged; see Git history for exact source provenance.
