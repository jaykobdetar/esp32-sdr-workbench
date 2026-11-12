# Matched v2/adaptive gain trials (private outputs)

The runner never flashes. The operator must separately verify the backup, recovery path, installed artifact and USB devices before running. A local artifact SHA-256 plus VERSION/revision is not proof of installed flash contents. Keep every output directory private and distinct.

From the repository root, activate/install this checkout with `python -m pip install -e ".[dev]"`. Run the explicit checkout script so an installed `nrf_campaigns` module cannot silently select a different checkout:

```sh
PYTHONPATH=. .venv/bin/python scripts/nrf_gain_compare.py \
  --rx-port RX_DEVICE --rx-serial EXACT_RX_USB_SERIAL \
  --tx-port TX_DEVICE --tx-serial EXACT_TX_USB_SERIAL \
  --rx-artifact EXACT_LOCAL_APP_BIN --output-directory NEW_PRIVATE_RUN_DIR \
  --expected-variant esp32-pipeline-adaptive-q16-v7 \
  --expected-revision EXACT_VERSION_REVISION --candidate-count 1 \
  --pairs 4 --manual-gains 40 60 --seed 52840 --power-dbm -20 --milliseconds 1000
```

For the manually installed baseline, use `--expected-variant esp32-pipeline-optimized-v2 --candidate-count 1`, its exact local artifact, and a new directory. For a matched single-retention comparison, run the selected adaptive image with `--candidate-count 1` using otherwise identical conditions. Three-crop v3 versus one-crop v2 changes retention as well as background policy, so cannot isolate the cause of any difference. Revision checking is optional but recommended; mismatches fail before any source START. Defaults remain optimized-v2 and one crop, and three crops require explicit adaptive-v3/v4 selection.

The finite source has both 5000-packet and 6000-ms ceilings on every ON run. Completion-counter deltas must be positive for ON and zero for OFF; these host-command brackets are not exact RF acquisition windows. The source is STOPped and checked before/after runs and finally. A terminal STOP or receiver cleanup failure marks the report failed. A failed receiver transport prevents claiming clear/restoration was verified.

Each run records before/after gain and selectors, initial/cleared/retained heap, actual source counters and every saved crop's metadata and transport CRC. No retained event is represented by count zero, an empty crops list and null CRC, not an imaginary successful capture. Heap equality detects residual allocation/fragmentation after clear, not transient allocation peaks. Gain/selectors are restored and read back; frequency/rate/bandwidth remain at trial settings. An existing pending PIPEKEEP selection is refused without consuming or clearing it.

Candidate windows are not packets; this is not packet recall, calibrated sensitivity or decoder validation. Hardware AGC changes the meaning of detector energy, the bench geometry is unmeasured unless separately documented, and temporal blocks at one placement do not establish general RF performance. Output directories are never overwritten.

V4 requires [stored-calibration boundary observations](calibration-fingerprints.md). Historical v2/v3 remain supported but explicitly lack this telemetry. Three crops remain an opt-in experiment, not the recommended default.
