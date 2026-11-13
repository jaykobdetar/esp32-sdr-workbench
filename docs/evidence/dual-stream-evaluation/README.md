# Dual-receiver streaming evaluation

This evidence accompanies the experimental persistent detector stream and sparse
I/Q transfer work. **It does not demonstrate continuous RF capture, 100% packet
recall, coherent I/Q combining, or Quest-controller protocol compatibility.**

The measurements below are intermediate candidates, not interchangeable results
for the current source tree. Each data set has its own measured application hash,
build-source commit and firmware variant in [summary.json](summary.json).

## Read the three time measurements separately

1. **Requested-window nominal union:** union of each recorded trigger timestamp
   plus `16380 / 16 MHz`, over the requested receiver-A observation interval.
   Shared, known, CRC-valid RF packets align the independent clocks. This is a
   timing model, not a calibration of the usable ADC aperture.
2. **Completion-inclusive nominal union:** the same model, but the denominator
   extends to the later receiver terminal timestamp and therefore includes final
   snapshot/telemetry drain. It still excludes external RF-anchor calibration,
   host pre-arm time, terminal-frame transmission and trailing ASCII output.
   It is **not** a complete host-session metric.
3. **Full-burst opportunity:** packet-start times for which an entire hypothetical
   50/100/250/500 µs burst could fit in *one* nominal capture. Overlapping partial
   captures are not stitched together. The denominator is the requested interval
   shortened by the burst duration. This does not imply that those captures were
   retained, that a packet was present, or that it could be decoded.

Adding receiver duties is not a union measurement. Likewise, a nominal timeline
union near 100% can still have substantially fewer opportunities for a complete
packet to fit inside one receiver's buffer.

## Intermediate candidate comparisons

Ranges below are across the listed runs, rounded from the reproducible evidence.
The source is stopped during no-retention timing runs. Sparse campaigns include
alternating transmitter ON/OFF runs and retain full buffers independently of the
energy-positive detector flag.

| Data set / measured candidate | Runs | Requested-window union | Completion-inclusive union | Largest requested-window gap | 100 µs full-burst opportunity |
|---|---:|---:|---:|---:|---:|
| `campaign-r7`, stream v7, 1.875 ms period, no raw retention | 3 × 30 s | 99.960–99.969% | 99.953–99.961% | 724–851 µs | 98.418–98.432% |
| `campaign-r7-1800`, same binary, 1.800 ms period | 3 × 60 s | 99.565–99.630% | 99.561–99.627% | 776–837 µs | 99.341–99.433% |
| `sparse1-onoff`, sparse v1, one IQ frame pumped per cycle | 4 × 30 s | 99.752–99.760% | 97.064–97.072% | 851–1,006 µs | 98.114–98.195% |
| `sparse2-guard-timing`, sparse v2 adaptive guard, no raw retention | 2 × 60 s | 99.680–99.688% | 99.677–99.685% | 715–742 µs | 98.068–98.079% |
| `sparse3-onoff`, sparse v3, fuller UART budget plus adaptive guard | 2 × 30 s | 98.833–98.854% | 96.849–96.869% | 851–884 µs | 95.523–97.104% |

The shorter period improved the modeled 100 µs full-burst opportunity but worsened
timeline union in these trials. The adaptive maximum-delay guard caused frequent
forced tick waits and was rejected as the preferred scheduler. The v3 transfer
change eliminated busy-snapshot skips in its two trials, but its combination with
that guard and more frequent packing worsened timing. **None of these tradeoffs
is evidence of a universally better receiver.** Later scheduler candidates must
be evaluated separately rather than assigned these numbers.

Early streaming candidates also experienced incomplete final ASCII summaries
after valid binary telemetry. Those trials were failures, not coverage evidence.
Paced summary output and immediate-command handoff changes were screened before
these accepted campaigns. The exact USB/serial truncation mechanism was not
established; the workaround is empirical.

The old finite-run result around 96.25% had different timing boundaries and
readout/restart behavior. Do not directly compare it with a requested-window
99.75% figure or describe that as an equal-duration end-to-end improvement.

## Actual known-packet evidence

[packet-proof.json](packet-proof.json) contains only complete, known generated
payloads with address and over-air CRC verification. Partial decoder candidates,
incidental RF samples, raw recordings and device identifiers are excluded.

| Candidate / source state | Sparse recordings A + B | Distinct packets A | Distinct packets B | Combined distinct packets |
|---|---:|---:|---:|---:|
| Sparse v1, ON run 0 | 8 + 8 | 4 | 4 | 8 |
| Sparse v1, OFF run 1 | 8 + 8 | 0 | 0 | 0 |
| Sparse v1, OFF run 2 | 8 + 8 | 0 | 0 | 0 |
| Sparse v1, ON run 3 | 8 + 8 | 3 | 5 | 8 |
| Sparse v3, ON run 0 | 15 + 16 | 8 | 10 | 18 |
| Sparse v3, OFF run 1 | 15 + 16 | 0 | 0 | 0 |

Deduplication is **within one transmitter START only**. Sequence numbers can be
reused in another run and must not be merged across runs. In these ON runs the
receivers contributed different packets; combined counts therefore exceeded
those of either receiver. This is useful temporal diversity in sparse recordings,
not a packet-recall percentage, a matched sensitivity comparison, or coherent
combining. Zero matches in these OFF controls is a finite observation, not proof
of a zero false-positive rate. ON/OFF order was alternated, not randomized.

The source used known 16-byte payloads, 2 Mbps GFSK at 2440 MHz, nominal 0 dBm,
1 ms packet interval with 113 µs configured jitter. Receivers used manual gain 60,
16 MS/s, 16,380 samples, 10-bit components and legacy background policy. Antenna
geometry and absolute received power were not measured, so these are not
sensitivity or distance specifications.

## Reproduce the published checks

From an installed checkout with transmitter extras:

```sh
python -m nrf_campaigns.verify_stream_evidence docs/evidence/dual-stream-evaluation
python -m nrf_campaigns.verify_sparse_packet_evidence docs/evidence/dual-stream-evaluation/packet-proof.json
```

From the source checkout, `python -m scripts.…` is also supported. These commands
are offline and do not connect to radios or transmit.

The timing verifier checks archive SHA-256 values, original per-frame wire CRCs,
sequence/counter/terminal consistency, independent bracketing RF-anchor groups,
clock-fit and held-out screens, then recomputes interval unions and sensitivities.
The packet verifier recomputes the known payload and Nordic over-air CRC from the
published decoded bytes, then recomputes per-run unions. **It cannot repeat raw
I/Q demodulation because raw RF is intentionally private.** Transport CRC and
radio CRC are different checks.

The archive manifest hashes and wire CRCs detect corruption; they are not
cryptographic attestation of the measurement hardware or clock model.

## Timing uncertainty and remaining limits

- Each accepted fit requires at least three independent capture-pair groups on
  each side of the requested interval. Whole groups are held out for validation.
- Affine clock-fit residuals and held-out errors are empirical diagnostics, not
  certified bounds on clock behavior inside the run. Nonlinear drift between
  anchors can remain undetected.
- ±1/5/20 µs clock-shift scenarios and eroded-aperture scenarios are published as
  **assumption-based sensitivity analyses**, not confidence intervals.
- Packet opportunity uses nominal sample rates and trigger timestamps. ADC
  settling, capture-boundary validity, RF calibration changes and finite decoder
  performance still matter.
- Full-rate raw I/Q is approximately 40 MB/s at these settings, far above the
  roughly 100 kB/s wire capacity of a 1 Mbaud 8N1 link. Sparse snapshots are not a
  continuous waveform, regardless of the acquisition-window union.
- RF Studio's combined spectrum is an asynchronous, noncoherent power display.
  Its independently started streams are not automatically aligned by this RF
  calibration campaign and must not inherit the campaign's coverage figures.

Firmware images and flash backups are not part of this evidence. Preserve each
board's recovery image and verify its partition layout before flashing; identical
USB serial labels do not imply identical application offsets.
