# Combined receivers: three different meanings

RF Studio now offers **Combined**, **Individual**, and **Both** display choices.
They are intentionally distinct from the experimental sustained-detector work.

## 1. A useful combined spectrum

The combined display averages **linear FFT power**, not complex I/Q and not dB
values. It uses recently delivered, transport-CRC-valid captures at the same
frequency, sample rate, and ADC format. It excludes stale, incompatible, or
possibly clipped observations when a better source is available. If every
source has endpoint samples, it selects the least-clipped source and labels
that fallback. Individual views and capture inspection remain available.

The receivers are **not phase coherent**. Their local oscillators, gains, sample
clocks, antenna responses, and acquisition times are not calibrated to each
other. The combined display is an asynchronous diversity view, not a continuous
waveform, calibrated received-power measurement, or proof of improved decoding.
A freshness label means recent delivery to the host, not simultaneous RF capture.

## 2. Sustained detector telemetry

`DSTREAM` is an experimental, bounded, **no-retention** mode. It keeps acquisition
and background state running while transmitting compact timestamp/energy records.
It avoids restarting the detector and reading out a full raw buffer after every
short run. Existing finite `DETPIPE1` and raw recording modes remain available.

At 1 Mbaud with 8N1, a receiver can transfer roughly 100 kB/s. Full 16 MS/s,
20-bit I/Q requires 40 MB/s. A 16,380-sample buffer takes about 410 ms on that
UART, although it represents only about 1.024 ms of nominal acquisition. Removing
file saving alone does not remove that transport cost.

The experimental stream emits 48-byte CRC-protected records, approximately
26 kB/s at a 1.875 ms trigger period. It uses one existing command task and a
bounded queue. UART pumping happens only after RF memory ownership is restored.
No background task reads RF-owned SRAM. Queue overflow, lost sequences, invalid
CRC, or inconsistent final counters invalidate the measurement. The command has
a ten-minute upper bound and accepts cooperative STOP; watchdog-friendly yields
remain enabled. Longer unattended UI sessions are separate from this bounded
research command and should not be confused with gap-free reception.

Each record includes:

- Capture generation and device trigger timestamp.
- Mean and peak energy, background estimate, candidate flag and cumulative count.
- Warmup/decision validity and observed acquisition completion latency.
- Gain-register snapshot taken at that capture's completion.
- Transport CRC.

A candidate is an energy-positive acquisition window, **not a unique packet**.
This no-retention mode does not deliver raw I/Q or decode packet payloads. The separate [DSTREAMIQ extension](sparse-iq-stream.md) adds sparse full snapshots, not continuous raw samples.

## 3. Measuring combined coverage

The explicit campaign `python -m nrf_campaigns.dual_stream_campaign` uses short,
known nRF transmissions to identify shared packets with full payload, address,
and over-air CRC checks. Those anchors align the independent device clocks.
The receivers then run with staggered trigger schedules and an optional
nanosecond-resolution period accumulator to compensate estimated clock drift.
The actual trigger timestamps retain microsecond resolution.

The analyzer requires both complete streams, bracketing RF anchors, an affine
clock-fit screen and whole-capture-group held-out checks. It computes interval
union over the **requested observation window**, including startup and ending
edges. It reports acquisition-window union and detector-decision union separately.

These remain **estimated nominal windows based on trigger + N/fs**. Fit residuals
and held-out errors are empirical diagnostics, not certified timing bounds. They
are not packet recall, nor proof that the ADC is valid for every instant. A
reported gap-free nominal trial alone would not establish 100% packet capture.

## Running a bounded experiment

Install the project as described in the [main setup instructions](../README.md#quick-start-rf-studio). The base installation includes the transmitter host package; no separate transmitter extra is required. Identify receivers by verified USB location, especially when their
USB serial labels are identical. Firmware installation is a separate reviewed
step: this campaign never flashes devices.

```sh
python -m nrf_campaigns.dual_stream_campaign \
  --port /dev/serial/by-path/VERIFIED_RECEIVER_A \
  --port /dev/serial/by-path/VERIFIED_RECEIVER_B \
  --tx-serial VERIFIED_TRANSMITTER_SERIAL \
  --output ./private-dual-campaign \
  --seconds 30 --trials 3 --period-ns 1875000 --phases 34,34
```

This example selects the experimental idle-wakeup scheduler (`34`) measured in the later candidates. It requires both receivers to advertise `DSTREAMIDLEWAKE`; unsupported selectors are rejected, not silently substituted. Older streaming firmware can explicitly use `--phases 32,32` for tick-aware yielding. Omitting `--phases` selects the original fixed phase `0,0`, not the later measured scheduler.

This prints a dry-run plan. Add `--run` to operate the devices. The source emits
bounded known test packets at 2440 MHz only for RF clock alignment; it is stopped
during the no-retention timing trials and at cleanup. Keep source power and
placement appropriate for your equipment and local operating limits.

The output directory is private and includes raw RF clock-anchor buffers, device
information, calibration fingerprints, decoder evidence, complete telemetry and
run summaries. Do not publish it unchanged. Publish only explicitly reviewed,
sanitized evidence and distinguish unsuccessful trials from accepted measurements.

## Recovery and limits

Never infer an application offset from an identical USB serial label. These tests
used receivers with different partition layouts. Preserve each board's original
flash and current calibration/settings, check the partition table, and write only
the verified application region. No command in RF Studio flashes automatically.

If a stream loses framing, STOP is requested and that connection is marked failed.
Reconnect before another command. A failed run is not filled in by interpolation.
The transmitter and receivers remain independently operable.

## What would improve packet capture next?

Nominal time coverage and whole-packet containment are different goals. A packet
can cross capture boundaries or fall partly in a gap even when the union of
listening windows covers nearly all of the timeline. Windows from independent
receivers cannot simply be joined into one decodable waveform. Retention,
signal quality, matching uncertainty, and successful decoding must also be
measured against known transmitted packets.

Transport bandwidth is a separate limit: the UART cannot export every sample at
the receiver's full sample rate. Sparse snapshots keep the display useful, but
do not remove this limit or turn telemetry into continuous I/Q.

Two future paths are shared hardware timing, to control and measure overlap more
precisely, and better on-device packet-selective retention, to spend scarce
buffer and transport capacity on useful bursts. Both need implementation and
controlled validation. Neither is a guaranteed route to gap-free reception or
complete packet recovery; the remaining limits are engineering and measurement
questions, not a lack of permission to test the existing devices.

## Evidence and source identity

Use the [streaming evaluation index](evidence/dual-stream-evaluation/README.md) for accepted measurements, unsuccessful candidates, binary identities and caveats. The [RF Studio guide](rf-studio.md) explains the interactive controls. Studio streams start independently; they do not perform the RF-clock alignment and staggered scheduling of this explicit campaign. No current installation state or performance result should be inferred from the source branch name.
