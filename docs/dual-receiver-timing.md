# Experimental dual-receiver timing

This branch adds **diagnostic, bounded dual-board operation**, not continuous SDR.
Both boards must have the separately built `esp32-dual-timing-experimental-v1`
application. The existing viewer is unchanged. Nothing in the host tool flashes
boards, starts a transmitter, or edits OS permissions.

## Identity and preservation

Some CP2102 bridges all advertise serial number `0001`. With two attached,
`/dev/serial/by-id` can silently point to only one of them. Use verified distinct
USB-location paths or genuinely unique serial identifiers, and recheck chip
identity before flashing. Keep each board's own private full-flash backup.
Do not copy NVS or calibration between boards. Install only an application when
the existing bootloader/partition layout is compatible. No full-chip erase is
part of this experiment.

## Run a bounded timing experiment

```sh
python scripts/dual_receiver_timing.py \
  --port /dev/serial/by-path/VERIFIED_RX_A \
  --port /dev/serial/by-path/VERIFIED_RX_B \
  --output records/dual-first \
  --period-us 1800 --phase-us 900 --duration-ms 1000
```

The output directory must be new. `--period-us 0` leaves each board free-running
after its scheduled initial start. `--retain` saves each receiver's strongest
candidate, adding copy/transfer overhead. All operations are finite (100–5000 ms
per pipeline); trace and I/Q transfers occur after acquisition stops. Between-run
USB transfers and reconnect/configuration time are real reception gaps.

`CLOCK?` returns a device monotonic microsecond timestamp. The host records the
request/response bracket and uses its midpoint only as an **estimate**, not a
hardware clock synchronization guarantee. `TRACEARM <device_deadline_us>
<period_us> <yield_phase>` arms one full-length 16 MS/s pipeline, up to five
seconds ahead. Period is zero or 1600–10000 us, and yield phase is 0–31. The
existing every-32-capture scheduler yield is preserved, optionally phase shifted.
All RF ownership, complete-aperture guard validation, immutable-copy, timeout,
retention and finite-duration checks remain enabled.

`TRACEGET` sends a CRC-checked list of every successful capture trigger. The
4096-entry buffer fails explicitly on overflow and must agree with successful
capture accounting. `TRACECLEAR` cancels a pending arm and frees the trace.
`TIMEDCAP <device_deadline_us>` is a separately scheduled full-length raw capture
with trigger metadata, for a controlled common-RF-clock calibration experiment.
Neither command asserts an RF-arrival timestamp.

## What the numbers mean

* Each interval is a recorded dump-trigger timestamp plus **nominal** 16380/16e6
  seconds. ADC/sample-clock frequency, trigger-to-sample latency and RF group
  delay have not been externally calibrated merely by this instrumentation.
* The combined metric is the **union of intervals**, with overlap counted once.
  It cannot exceed 100%. Summed receiver duties may exceed 100%, but this is
  redundant receiver-time, not more than complete coverage.
* Host-clock midpoint union is reported as `mapped_nominal_union`. Inspect the
  clock brackets. If their uncertainty can move an interval across a blind gap,
  the midpoint estimate is not a verified gap-free reception claim.
* Independent oscillators drift, and firmware/OS scheduling can introduce late
  or skipped slots. The trace reports actual trigger times and scheduling
  lateness, not just intended deadlines.
* Known, address-and-CRC-verified packets observed by **both** receivers can
  anchor their relative RF timelines. Packet matches must use the same sequence
  within a verified transmitter session; fit and validate drift across the run.
  Packet-containing files and energy detections are not packet recall.
* A pair of 63% receivers can have anything from substantial coincident gaps to
  near-complementary windows. Adding 63 + 63 does not establish 100% coverage.

Hardware findings and local evidence belong in a separate dated campaign report.
This protocol description alone does not claim that the two-board experiment
passed or that the target was achieved.

## RF-clock calibration and staggered readout campaign

The portable campaign is dry-run by default. It uses the existing verified
nRF52840 source, so identify that device explicitly as well as both receivers.
It changes the source to known 16-byte, 2 Mbps packets at 2440 MHz, 0 dBm,
1000 us interval with 113 us jitter, always with a bounded transmit duration.
The source is stopped on normal completion and exception cleanup. It leaves
that test configuration selected; restore your own saved source settings when
finished. This is a local bench tool, not automatic publication or flashing.

```sh
python scripts/dual_receiver_rf_campaign.py \
  --port /dev/serial/by-path/VERIFIED_RX_A \
  --port /dev/serial/by-path/VERIFIED_RX_B \
  --tx-serial VERIFIED_NRF_SERIAL \
  --output records/dual-rf-clock --staggered
```

After inspecting the dry-run, append `--run` to open the hardware. Both receivers
use manual gain 60, 16 MS/s, 12 MHz bandwidth, full 16,380-sample captures and the
legacy background rule on this instrumented image. The source is off during
pipeline timing. Known packets must pass address, complete known-payload and
RF-CRC checks on both boards before they become clock anchors. Insufficient
anchors stop the campaign rather than silently substituting USB clock timing.

Eight one-second probes choose yield phases while preserving every mandatory
32-capture yield. Without `--staggered`, six five-second paired trials follow.
With `--staggered`, separate receiver workers instead perform six and seven
chunks (30 seconds of requested acquisition on each), with readouts offset from
each other. A predefined 30-second observation window includes actual readout
and restart gaps. No clock-anchor capture interrupts that observation window.

After the final bracketing RF anchors:

```sh
python scripts/analyze_dual_receiver_timing.py records/dual-rf-clock
```

The analyzer checks that every anchor matches its saved packet metadata, fits
relative clock offset and drift, checks alternating held-out anchors, and
recomputes interval unions. It does **not** independently re-demodulate raw I/Q;
the packet decoder outputs and original local arrays remain available for that.
Fit residuals are empirical consistency checks, not certified uncertainty bounds.
The provisional numbers printed during acquisition use a simpler offset estimate;
use the final affine-clock analysis, not those progress numbers, for results.

Post-warmup detector-window coverage is also reported separately: the first
16 captures in every finite pipeline do not contribute to decisions, and the
60-sample incomplete block tail is not analyzed. RF aperture coverage does not
mean that every packet was detected, retained, transferred or decoded.
