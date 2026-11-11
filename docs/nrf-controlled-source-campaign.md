# Controlled nRF52840 source campaign

`scripts/nrf_rf_campaign.py` controls the separately installed Makerdiary transmitter through `nrf52840-transmitter/host/rf_tx.py`. It never flashes either board. Close the GUI and other serial clients first. Use only the identified receiver and authorized transmitter, within applicable local radio limits.

## Minimal experiment

First set `RF_TX_SERIAL` to your own transmitter's exact USB serial as described in the [transmitter guide](../nrf52840-transmitter/README.md). The host validates serial plus USB VID/PID even when a port is supplied. Use verified persistent serial device paths, not these placeholders:

```sh
.venv/bin/python scripts/nrf_rf_campaign.py \
  --rx-port /dev/serial/by-id/RECEIVER \
  --rx-artifact /path/to/your/verified/receiver.bin \
  --tx-port /dev/serial/by-id/TRANSMITTER \
  --output-directory records/nrf-2440-first \
  --frequency-mhz 2440 --rx-frequencies 2440 \
  --mode-mbps 2 --power-dbm -20 --length 64 --interval-us 2000 \
  --pairs 8 --milliseconds 2000 --raw-pairs 2 \
  --geometry 'Record actual separation, orientation, antenna and ambient conditions'
```

The default eight pairs produce 32 detector observations: eight ON/OFF pairs for each of same-image DET1 and optimized pipeline. ON/OFF initial order and receiver order are counterbalanced; block order is reproducibly shuffled with `--seed`. The raw stage adds four separate direct captures per receiver frequency. Each observation has its own finite TX train and explicit STOP. Repeatable OFF means only this transmitter is off, not an RF-silent room.

For an offset control, add a clearly out-of-band receiver tuning such as `--rx-frequencies 2440 2470`. This runs the complete plan at each frequency in the supplied order. Repeat with reversed frequency order to separate frequency effects from time drift. Offset-control contrast is useful evidence, not calibrated filter/alias rejection or proof of transmitter identity. Do not change physical placement between matched phases. Keep settings and random seed in the saved report. Repeat `--mode-mbps 1` in a new output directory for Nordic 1 Mbps. There is no automatic power sweep.

Receiver controls include `--gain`, `--bandwidth-mhz`, `--samples`, `--rate-hz`, and `--ratio-milli`. Defaults match the previous optimized benchmark: manual gain 40, bandwidth 12 MHz, 16,380 samples at nominal 16 MS/s, ratio 4000. Full-size optimized fused copying is active only at 16,380 samples. Duration is bounded to 1–5,000 ms. TX packet ceiling defaults to 20,000 (`--tx-count`) and safety duration defaults to 10 seconds, and must exceed run duration plus settling and a 3-second command/transfer margin. The transmitter accepts `payload_len` through the host API (CLI `--length`) and a positive packet ceiling; whichever count/time bound comes first stops it. Optional `--jitter-us` is recorded. The source must still report running after retrieval; expiration invalidates the observation rather than silently labeling it ON.

## Results and failure behavior

Each newly created output directory contains:

- `results.json`: complete settings/plan, device identity, local receiver binary hash, transmitter status and counters before/after each observation, receiver summaries, cleanup and campaign timing.
- `runs.csv`: flat per-observation index and derived candidate/CRC/power metrics.
- `NNNN-run.json`: each completed observation, including no-event results.
- `NNNN-*.sigmf-meta` and `.sigmf-data`: direct raw controls or strongest retained candidate, when present, with source metadata.

Existing output directories are refused. Aggregate results are checkpointed and atomically replaced after observations; failed/incomplete observations remain marked in aggregate JSON. STOP is attempted even after configuration, receiver, or file failures; final STATUS must confirm stopped. Cleanup failure marks the entire report failed. Loss of the host or serial link can prevent software cleanup, so the independent finite transmitter timeout is also required. No success claim should be based on a failed report.

`retained_crc_valid` on a raw row means the direct raw capture passed transport CRC; on detector rows it means a strongest retained candidate exists and passed transport CRC. False on a no-event row does not mean CRC corruption. Corruption raises an error.

## Interpretation

Candidate-positive captures are windows, not decoded packets. A run retains at most one strongest candidate. UART IQ CRC32 says nothing about Nordic over-air CRC. Transmitter completed counters measure local RADIO END events and bracket host requests, not synchronized receiver exposure; they include acquisition commands and retained transfer time. Do not divide detections by completed packets and call it recall.

Use paired ON-minus-OFF changes in candidate-window rates, post-warmup fraction, retained-IQ yield, RMS/clipping and spectrum as controlled-source evidence. Avoid treating correlated capture windows as independent trials. Payload/sequence demodulation and RF CRC validation are separate offline steps; see [validated results](nrf-validation-summary.md). Persistent ambient interference can dominate either state.

Firmware trains its background on the first 16 captures of every run, including ON runs, and adapts per capture afterward. High-duty sources can train themselves into the background. This experiment measures the actual existing detector, not a separately noise-trained detector. Faster cadence also changes wall-time adaptation.

Local nominal RF/analyzed/decision duty stays in the receiver summary. Host receiver timing includes command and IQ retrieval overhead. Full campaign timing additionally includes source setup, settling, raw controls and saving. `detector_rf_percent_of_complete_campaign` deliberately includes those costs in its denominator and only successful detector exposure in its numerator; it is not comparable to local duty or pure detector-only host duty.

## Offline verification

```sh
.venv/bin/python -m pytest -q tests/test_nrf_rf_campaign.py
```

These tests use fake radios and transmitters; they never open serial hardware. Hardware validation is a separate explicitly authorized step.

## Historical-image versus current-image comparison

`scripts/nrf_receiver_compare.py` runs exactly one receiver algorithm on the already installed image. It never flashes. Separately verified application-only flashing and ABAB image order must be managed outside the script.

```sh
.venv/bin/python scripts/nrf_receiver_compare.py \
  --receiver-mode historical --label historical-A1 \
  --rx-port VERIFIED_RX --tx-port VERIFIED_TX \
  --rx-artifact /path/to/your/verified/receiver.bin \
  --output-directory records/nrf-historical-A1 \
  --pairs 8 --gain 60 --power-dbm 0 --length 64 \
  --interval-us 1000 --jitter-us 150
```

Repeat after the independently verified image changes with `--receiver-mode optimized --label optimized-B1`, then historical-A2 and optimized-B2, always using distinct directories. Keep geometry and settings fixed. By default this script uses gain60, TX0 dBm, interval1000 µs, jitter150 µs, payload64, 2 Mbps, eight paired ON/OFF trials (16 observations), no direct raw stage. `--raw-pairs` can enable that additional stage. Other campaign parameters remain available.

Historical mode invokes only DET1 and its normal retrieval; it does not send DETPIPECLEAR, ACQOPT, CLEAROPT, PIPEKERNEL or PIPECOPY. Optimized mode uses the exact optimized selectors. Actual VERSION is always logged; `--expected-variant TEXT` optionally enforces a VERSION substring, since the archived historical image may not expose a named variant. The local artifact hash identifies the intended corresponding file, not a flash readback or proof of the running image. Preserve separate flashing/hash-verification records.

CSV and JSON rows normalize nominal sample exposure, local RF duty, and receiver host RF/decision duty using total samples, configured sample rate and their respective measured durations. Raw receiver summary fields are also preserved unchanged. Receiver host elapsed time includes selector/clear commands and retained transfer but excludes source snapshots, source settling and file saving. Complete campaign duty remains separately named and includes all those costs. Labels and exact settings are saved in aggregate JSON and retained metadata.

## Public checkout versus historical collection

The public runners require `--rx-artifact /path/to/your/verified/receiver.bin`; there is no private-machine default binary path. This records a local binary hash, not flash readback. Tests use explicitly synthetic temporary binaries. Parameter screening additionally requires a new `--output-directory`, explicit ports, and `--geometry`; the screen runs the 17 documented configurations, including configured TX power up to 0 dBm. Direct raw sweeps also require explicit receiver/transmitter ports. All source settings remain subject to local RF regulations.

Historical application-flashing shell wrappers, recovery paths and binary images are not included. Historical versus optimized image changes and optional retention-patch installation must be deliberate independent steps with your own recovery backup. `scripts/compare_nrf_abab.py`, `summarize_nrf_screen.py`, `summarize_nrf_retention.py` and `evaluate_nrf_retention.py` operate on privately held original-layout records; they do not regenerate those raw records from the public exports. Use `scripts/verify_nrf_evidence.py` for the public-data verification path. Source hashes and portability changes are recorded in [rf-source-provenance.json](rf-source-provenance.json).
