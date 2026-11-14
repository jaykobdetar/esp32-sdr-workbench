# Experimental sparse full I/Q during persistent telemetry

**Experimental and build-specific.** This mode does not provide a continuous waveform, coherent receiver combining, calibrated RF apertures, or a packet-recall measurement. Intermediate candidates have separate hardware evidence in the [streaming evaluation index](evidence/dual-stream-evaluation/README.md); those results must not be assigned automatically to the current source. Check `firmware/FIRMWARE_VARIANT` and the device's `VERSION?` reply against the measured build identity. The existing no-retention `DSTREAM` command remains available; sparse-capable firmware additionally advertises `DSTREAMIQ`.

RF Studio exposes this mode explicitly under Advanced. See the [UI guide](rf-studio.md#experimental-persistent-telemetry--sparse-iq) for bounded sessions, no-save operation and independent receiver timing, and the [combined-receiver guide](continuous-dual-receivers.md) for the separate RF-aligned campaign.

## Command and host API

`DSTREAMIQ deadline_us duration_ms period_ns yield_phase ratio_milli snapshot_every snapshot_phase`

The first five arguments have the existing DSTREAM limits. `snapshot_every` is
1024–1000000 captures; `snapshot_phase` is 0 through every-1. A snapshot is selected
when generation modulo every equals phase, independently of detector positives.
For about five seconds at a 1.875 ms nominal cycle, start with every=2667.
The BEGIN line is the ordinary DSTREAM BEGIN line plus every and phase, echoed
for host verification. Use different phases for two receivers if desired; this
is not clock synchronization.

`run_stream(..., snapshot_every=2667, snapshot_phase=0, on_snapshot=callback)`
returns normal timing results and `snapshots_received`. Each callback receives
metadata plus immutable `payload` (40950 packed bytes, 16380 complex samples,
10 bits per component, 16 MS/s). `decode_iq(payload, 16380, 10)` converts it.
No raw data is written to disk or retained in the returned result. A caller must
explicitly save callback data if wanted. Callbacks must be fast and never touch
the radio; slow consumers can invalidate transport. With no callback, complete
snapshots are checked and discarded.

## Wire format

All frames are 48 bytes, little-endian; the final uint32 is CRC32 over the first
44 bytes, using the same CRC convention as DSV1. Timing DSV1 frames are unchanged.

* `DSI1`: magic, generation u32, trigger u64, sample count u32, packed length u32,
  packed CRC32 u32, completion gain-register u32, completion duration u32,
  frequency MHz u32, reserved-zero u32, frame CRC32 u32.
* `DSQ1`: magic, generation u32, byte offset u32, payload length u32,
  28-byte payload (zero-padded last chunk), frame CRC32 u32.

Metadata precedes sequential chunks. The host checks metadata against an original
CRC-checked timing record, requires exact offsets/generation/length, and verifies
the complete packed CRC. A maximum of 4096 recent timing records and one 40950-byte
packed accumulator are held internally. Missing metadata/chunks, corruption,
reordering, incomplete final snapshots or final-count disagreement fail the run.
Transport CRC says nothing about over-air packet validity.

## Scheduling and safety

Only immutable previous CPU-owned `p.copy` is packed, after acquisition restores
RF memory ownership and before that copy is overwritten. No second 65 KB raw
buffer is allocated. Ten internal DMA-capable pages total 40950 bytes, checked
against the RF aperture and other allocations. Allocation failure rejects the
command before acquisition. Existing recovery/protected flash regions are not
changed by this feature.

One writer multiplexes frames. An already-started frame is finished before
switching; otherwise timing records have priority. The nonblocking UART pump has
a 128-byte maximum per acquisition cycle. One snapshot is outstanding at a time;
selection while busy increments `iq_busy_skips` and never overwrites its data.
A packing failure produces status 4 and invalidates the run. Timing queue overflow
continues to fail closed. Watchdog yields remain unchanged.

After acquisition stops, pending frames drain with a two-second deadline and
watchdog yields; timeout leaves framing incomplete, so the host must stop and
mark the connection failed, not issue more ordinary commands. A successful END
reports `iq_produced`, `iq_sent`, and `iq_busy_skips`. STOP is cooperative; bounded
final readout can delay completion. The terminal timestamp includes this drain.

Full packing and CRC add periodic CPU cost and can create missed deadlines; they
are reflected in timestamp gaps; v6 reports their CPU time separately and overlaps
part of that work with acquisition. Each full snapshot
requires 1464 frames including metadata (70272 wire bytes), not merely 40950 UART
bytes. Timing traffic and USB stalls may extend delivery. Heap headroom, timing regressions, STOP latency, transmitter payload recovery and multi-minute stability must be assessed for each measured binary on **both board layouts**. Passing one candidate’s tests does not validate a later candidate. Do not substitute its numbers for the earlier no-retention runs.

## v6 prototype: overlap packing and bounded CRC work

The v6 experiment keeps the same packer and wire format, but packs a selected
**previous, fully validated CPU-owned copy** in the acquisition-wait callback,
after its energy calculation. It never reads the current RF-owned sample aperture.
Packed pages are checked to lie outside that aperture during allocation and remain
immutable while CRC calculation and delivery are pending. No second raw buffer is
allocated. Default no-snapshot mode remains unchanged.

CRC processing is limited to 2048 packed bytes per later wait callback. The new
snapshot is not CRC-scanned in the callback that packs it. Metadata is gated on
both complete CRC calculation and commitment of its matching timing record; UART
transmission remains outside the wait callback. Busy selections are counted once
per capture generation. The final capture, including STOP or acquisition failure,
is packed after RF ownership is restored if no wait callback processed it; final
CRC work then completes in bounded chunks inside the existing two-second drain.

`iq_pack_us` and `iq_crc_us` separately report cumulative CPU time. Some packing
may exceed the RF waiting window; overlap does not make that CPU cost disappear.
This is a scheduling experiment, not an assurance that snapshot-induced gaps or
missed slots vanish. Bit-exact packing, incremental CRC, metadata readiness,
partial writes, STOP draining and failure handling have software tests; board
performance and long-duration stability require fresh validation of this variant.

## v7 review follow-up: acquisition ownership and complete capabilities

The v7 source keeps v6's wire format and snapshot pipeline. A common pre-acquisition
wait now performs the cooperative part of every scheduled delay before ADC/filter
changes or capture-SRAM handoff. The final trigger wait never calls `vTaskDelay`.
This applies to `TIMEDCAP`, trace acquisition, `DSTREAM`, and `DSTREAMIQ`, including
the first deadline and every long-period capture. Setup telemetry excludes that
coarse wait. Host C tests execute the actual acquisition function with ownership-
checking register stubs; those tests are not a hardware timing guarantee.

`CAPS` is sent directly from its compiler-sized constant rather than the 256-byte
`reply()` buffer. Tests compile and run all CP2102/health capability combinations,
including the previously truncated combination.

The host can verify `expected_background_policy` against BEGIN; application and
campaign callers pass their verified/selected rule. It also reads an optional
post-summary `ERR` for a failing acquisition, bounded to one second. Missing error
text does not make a failed run valid. The installed Studio launcher is now
`esp32-sdr studio`.

Larger snapshot chunks remain a separate protocol/performance experiment: changing
48-byte framing here would break compatibility and invalidate existing transport
and measured-binary evidence. The current 70,272-byte snapshot wire cost is explicit
above. No v6 coverage or throughput figure is claimed for this new v7 binary.
