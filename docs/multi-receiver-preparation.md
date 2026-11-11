# Independent receiver coordinator

This prepares finite raw-capture experiments for future multiple ESP32 receivers. It does not flash hardware, change the GUI, synchronize clocks, or establish continuous reception. One receiver is supported now.

Create a JSON plan, for example:

```json
[
  {"receiver_id":"rx2440","port":"/dev/serial/by-id/VERIFIED_RX_A","frequency_mhz":2440,"rate_hz":16000000,"bandwidth_mhz":12,"gain":60,"samples":16380,"start_offset_ms":0,"captures":3},
  {"receiver_id":"rx2470","port":"/dev/serial/by-id/VERIFIED_RX_B","frequency_mhz":2470,"rate_hz":16000000,"bandwidth_mhz":12,"gain":60,"samples":16380,"start_offset_ms":25,"captures":3}
]
```

Validate and inspect without opening hardware:

```sh
.venv/bin/python scripts/multi_receiver_capture.py --plan receiver-plan.json --dry-run
```

Dry-run is also the default when neither mode flag is given. It checks plan structure, bounded configuration, duplicate IDs and resolved serial-path aliases. Device-specific gain, bandwidth and rate support is checked by the existing Radio.configure after connection during an actual run; dry-run cannot promise hardware compatibility.

After identifying and authorizing every receiver, close all other serial clients and run explicitly:

```sh
.venv/bin/python scripts/multi_receiver_capture.py --plan receiver-plan.json --run --output-directory records/multi-first
```

The output directory must be new. Each worker creates, configures, captures from and closes its own exclusive Radio. There is no cross-thread serial sharing. A receiver failure does not discard another receiver's successful results. Every owned connection is closed in a finally block, and close failures are reported. The combined `results.json` identifies each receiver, actual identity, settings, host timing bounds, CRC-valid captures, errors and close outcome. SigMF files use unique receiver IDs and capture indexes.

Plans allow 1–16 receivers, 1–100 captures each, and offsets up to 60 seconds. Each serial operation uses the existing bounded Radio deadlines. This is finite scheduling, not a hard real-time global deadline; a large count and serial timeouts can take substantial time. Do not rely on process interruption for an immediately written aggregate report. Capture files already saved remain available, but aggregate JSON is written when the finite coordinator returns.

`start_offset_ms` schedules the **host worker connection/configuration start**, relative to one host monotonic epoch. USB initialization, firmware preparation and OS scheduling add independent delays before capture. Actual worker lateness and each capture call's start/end are recorded. These are host bounds, not RF timestamps. `samples / configured sample_rate` is nominal per-receiver aperture. The coordinator intentionally does not sum duties into aggregate RF coverage: overlapping or differently tuned windows, unsynchronized device clocks and dead time prevent a continuous-reception claim.

Offline tests use injected fake Radio APIs and include independent settings, per-receiver errors, closing after connect/capture failures, offsets, duplicate port aliases, CRC errors and a dry-run CLI with nonexistent hardware paths.
