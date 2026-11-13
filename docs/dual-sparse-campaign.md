# Bounded sparse-I/Q ON/OFF campaign

This is an **experimental measurement tool**, not proof of continuous raw reception.
It requires both receivers to advertise `DSTREAMIQ`. It never flashes firmware.
Run from a checkout whose campaign code includes the independent-anchor screening:
three separate successful capture pairs before and after each timing run, not
three packets from a single pair.

Preview without opening any device:

```sh
python -m nrf_campaigns.dual_sparse_campaign \
  --port /dev/serial/by-path/VERIFIED_RECEIVER_A \
  --port /dev/serial/by-path/VERIFIED_RECEIVER_B \
  --tx-serial VERIFIED_TRANSMITTER_SERIAL \
  --output /path/to/new-private-results \
  --seconds 30 --trials 1 --snapshot-every 1024
```

From the repository root, `python -m scripts.dual_sparse_campaign` is also
supported when dependencies are installed. Add `--run` only after checking device
identities and their firmware. Output must not exist. Device identifiers, raw RF,
and anchor recordings are private; do not add this directory to GitHub.

## Measurement design

* Full 16380-sample snapshots, 16 MS/s, 2440 MHz, fixed manual gain 60 by default.
* Two receivers staggered by half a nominal cycle; default period 1.875 ms,
  tick-aware yielding, RF-anchor clock drift compensation.
* Snapshot every 1024 captures by default; `--snapshot-every 2667` is less intrusive.
  Receiver B uses an offset snapshot phase. This does not make their RF clocks
  synchronous or guarantee equal snapshot counts.
* Each trial includes ON and OFF. Trial order alternates ON/OFF then OFF/ON.
  Each condition is bracketed by independent known-source RF anchor recordings.
* Source uses known 16-byte Nordic 2 Mbps payloads, 1000 us interval plus jitter,
  at -4 dBm initially (`--power-dbm` selects supported values up to 0 dBm).
* Each stream lasts 1–55 seconds. Source ON uses `count=0` with a finite duration
  of stream length plus 2 seconds, never more than 57 seconds. This covers the
  scheduled startup and is stopped explicitly at stream completion. Anchors are
  separate bounded transmitter runs, not part of the snapshot packet union.

Callbacks only write one approximately 40 KB packed snapshot and its metadata;
no payload decoding occurs in the acquisition callback. They retain no raw buffers
in the report. Slow disk or USB can still invalidate transport; any reported
transport failure must not be converted to coverage.

Both receiver workers share a cooperative STOP event. On error, that event is set,
the transmitter is stopped, and both workers are joined before serial ports close.
The transmitter's own finite duration is a secondary limit. Final raw decoding
runs only after the campaign closes the hardware connections.

## Output and interpretation

`results.json` holds per-condition timing results, source counters, calibration
fingerprints, snapshot metadata, and offline decoder results. `.packed` files are
CRC-checked 10-bit-per-component CAP20 data, with matching JSON metadata. A
`.packed` file without complete metadata may remain after an interrupted write;
it is not a validated recording and is not included in decoder inputs.

Within **one source START**, the decoder unions unique sequence+payload keys across
the two receivers only when the known payload, address and over-air CRC all pass.
Repeated decoding hypotheses and repeated recordings of the same packet count
once. The report gives each receiver's unique count, shared count, union, and
receiver-exclusive contributions. It rejects mixing run IDs, because sequence
numbers can restart after START. OFF matches are reported rather than suppressed:
they would require investigating interference, stale data or analysis errors.

These are packet counts in sparse saved recordings, **not packet recall**. Source
completed counters cover a broader interval than snapshot apertures, and no
per-transmission timing match is established. Do not divide union counts by
completed transmissions and call that detection probability. Timing coverage is
separately estimated from nominal apertures and independently bracketed RF clocks;
failed timing screening remains `unverified`, even if some packets decode.

The raw files can be reanalyzed offline through `decode_saved(output, run_row)`.
It rechecks saved CRC and size before decoding, and never accesses a serial port.
