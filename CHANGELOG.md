# Changelog

## Unreleased

- Add task-first RF Studio with Listen, Test a signal and Compare receivers;
  paste validated settings JSON or copy a self-contained LLM prompt.
- Add memory-only, until-stopped receive sessions and explicit Combined,
  Individual and Both spectrum views. Combining is noncoherent linear power,
  not synchronized I/Q or a coverage claim.
- Add experimental CRC-framed DSTREAM telemetry and DSTREAMIQ sparse full-I/Q
  delivery, with bounded buffers, cooperative stop and independent device use.
- Add RF-clock-anchored dual-receiver campaigns, full-burst opportunity and
  completion-inclusive timing analyses, known-packet diversity checks, and
  sanitized reproducible evidence. No result establishes 100% packet capture.
- Keep sparse recording filesystem writes off the acquisition thread and verify
  echoed frequency/policy and snapshot metadata before accepting a stream.

- Identify the source as `esp32-pipeline-adaptive-q16-v8`. `BGPOLICY` now accepts
  only the exact text `BGPOLICY 1` or `BGPOLICY 2`. On the v7 board `BGPOLICY1`,
  `BGPOLICY 4294967297` and `BGPOLICY -4294967295` were all accepted as rule 1.
- Record the v7 same-image rule comparison in the detector guide. The model
  prediction of a legacy advantage was not borne out on the board.

- Identify the source as `esp32-pipeline-adaptive-q16-v7`. Add the sticky `BGPOLICY`
  selector so the historical optimized-v2 background rule (1) and the Q16 rule (2,
  default) can be compared on one installed image; host C tests check rule 1 against
  the archived v2 source. Clients set and read back the rule and verify the summary.
- Idle with a repeated `ERR nvs_init` notice when NVS initialization fails. V5/v6
  aborted, which reboots in a loop under the release panic configuration.
- Add `esp32-sdr record --background-policy` and `background_policy=` on the
  DET1 and pipeline clients. V7 is compiled and host-tested only, not board-tested.

- Identify final safety fixes as `esp32-pipeline-adaptive-q16-v6`; preserve the
  earlier v4 and intermediate v5 build identities and historical measurements.
- Reject embedded NUL at the serial line boundary and require final passed raw-control
  reports before analyzing current raw captures.
- Preserve NVS on initialization failure and reject malformed SPEC arguments.
- Freeze validated UF2 bytes, keep recovery files private outside installed packages,
  and distinguish version/health observations from exact image verification.
- Publish recordings without overwriting existing files and retain SPC1 gain.
- Add manifest-first v2 RF analysis, explicit current metadata adapters and rejection
  of unsupported custom payloads; keep historical analysis sources unchanged.
- Include public source resources in sdists and explain checkout-only firmware builds.

- Identify corrected source as `esp32-pipeline-adaptive-q16-v4`, distinct from
  both historically tested v3 binaries. Preserve their evidence unchanged.
- Add read-only stored-PHY SHA-256 observations at campaign stage/run boundaries,
  explicit legacy unsupported/error records and private-output guidance.
- Prepare a local measured-v2 source tag with checked archive correspondence and
  original unknown-Git-revision/rebuild caveats. No public release is created.
- Document three-crop containment/copy-cost limitations; keep single retention
  the default and avoid further optimization without a packet-linked redesign.


- Publish the adaptive evaluation with 925 pipeline runs, 1,818 recorded CRC-valid
  files, separate release/candidate identities and the calibration-change caveat.
- Fix top-three tie eviction to preserve earlier generations; check all 4,096
  six-capture score streams and integrated packed retrieval.
- Add default-off pipeline heap/stack telemetry and tested board/matched/raw-control
  harnesses. Only the separate instrumented, tie-fixed image received the 30-minute
  soak; no retained-packet advantage over v2 was established.
- Publish privacy-reviewed summary evidence and an offline accounting checker.

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

The later evaluation is linked above. This source publication creates no release tag, published binary release or newly installed firmware; candidate-soak results do not validate a newly built default-off release image.

## 0.1.0 (source baseline)

Initial native viewer, optimized ESP32 source, nRF52840 tools and scrubbed evidence.
This historical version was not tagged; see Git history for exact source provenance.
