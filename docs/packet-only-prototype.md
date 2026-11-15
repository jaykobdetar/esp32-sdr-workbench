# Single-board packet-only prototype verifier

This is an opt-in host verifier for the separately reviewed
`esp32-packet-only-bounded-v1finish` firmware candidate, **not a firmware installer**.
It is restricted to the controlled unwhitened Nordic 2 Mbit/s, 16-byte `RFTX`
payload and address `efcdab89c3`. It is not a Quest/general protocol decoder.
The candidate serializes acquisition, fixed known-source decoding and metadata
readout. It sends no I/Q, has no output queue, and does not continuously capture.

## First controls

Identify one board, its independently verified recovery/rollback, and its exact
candidate image before using this tool. Keep other boards out of this first test.
The command is dry-run unless `--run` is present:

```sh
python -m nrf_campaigns.packet_only_campaign \
  --port VERIFIED_RECEIVER_PATH --tx-serial VERIFIED_SOURCE_SERIAL \
  --output NEW_PRIVATE_DIRECTORY --count 32 --off-only
```

Add `--run` for an authorized source-OFF smoke. The source is verified stopped;
no START is issued. The receiver captures and decodes 32 requested slots, with
explicit skip accounting. Any accepted OFF packet fails attribution.

After a clean OFF control and independent review, omit `--off-only` to collect
OFF then ON. Defaults request 128 slots, 10,000 us spacing, an output cap of 16
records/window and a finite 3 s, 0 dBm known-source run. Source duration must
include at least 1 s of planned startup/readout slack and is limited to 16 s.
The source also has a 20,000-attempt hard count bound. These are finite commands,
not an unattended continuous mode. The host records source command/acknowledgement
and collector times; it labels collection extending beyond the nominal source
duration bounds. Planned slack is not a hardware timing guarantee.

## Strict contract and retained failures

Every line is retained and flushed to `off.wire.txt` or `on.wire.txt` before
parsing. PONLY v1 uses monotonically contiguous wire sequence numbers, a CRC32
of the exact ASCII prefix/body, and a bounded BEGIN / WINDOW / PACKET / END
structure. The parser validates exact field names/order, request echoes, CPU
frequency/core, slot monotonicity and scheduled times, per-window packet counts,
terminal accounting, cumulative/max decode work and measured nominal inter-window
gaps. END must explicitly succeed. Missing END, malformed/truncated transport,
CRC failure, sequence loss, decoder/capture/send fault, cancellation and any
output-cap drops reject the entire recall result. Cap zero remains a diagnostic
option, not a way to hide lost output. All-zero-cap or all-skipped runs cannot
establish a positive packet-recovery result.

The host independently reconstructs the deterministic 16-byte payload from the
reported sequence and recomputes the air CRC over the fixed address, length and
payload. Firmware supplies the verified address/observed CRC and payload; this
host cross-check is **not independent RF demodulation** because no I/Q is sent.
A bounded fixed known-source decoder may miss packets outside its hypotheses.

Successful END counters must account for every requested slot: completed plus
skipped, with no faults or cancelled slots. Skipped slots remain explicit losses
of acquisition opportunity. Busy and incomplete decoder candidates are recorded,
but they cannot be translated into numbers of unique RF packets missed. There
is no queue; output cap loss and metadata-send failure are distinct counters.
Gap sums use nominal sample duration between observed triggers and exclude
session edges. They are not continuous-coverage or packet-recall denominators.

On a read/validation failure the host preserves the original report/transcript,
requests cooperative STOP, poisons the receiver framing and closes rather than
resynchronizing failed bytes into an accepted run. The firmware's own bounded
command remains the independent fallback. Source STOP and configuration
restoration are attempted even on failure; a cleanup failure forces failed
status. Calibration is checked before/after each accepted condition and session.
An unavailable post-failure fingerprint is not silently reported unchanged.

## Denominator and interpretation

The source must be healthy firmware 0.2.2. START must prove reset transmission
counters; its live elapsed time may be nonzero but must precede final completion
times. The final state must be stopped, attempted must equal completed, and
scheduled must equal attempted plus missed slots. An early source stop, reset,
accounting mismatch, out-of-range packet sequence or accepted OFF packet fails
the result. Packet sequences are deduplicated within this one source run only.
The denominator includes **all** completed source transmissions, including
startup/slack and periods without receiver acquisition.

The prior best raw-IQ8 control's 161/31,865 ratio is a separate multi-board,
16-second-source/10-second-budget experiment. It is not an equal-condition
baseline for these initial single-board, short packet-only controls. First prove
protocol, cleanup, false-match controls and finite repeatability; only then design
matched-duration comparisons.

The earlier decoder timing of 6.244 ms per 1.02375 ms sample window is about
6.1 times slower than real time; two CRC passes measured 8.236 ms, about 8.0 times.
Removing the 334 ms raw-IQ UART transfer does not remove this compute bottleneck.
Ten-millisecond slots cap nominal aperture time at roughly 10.24% per receiver
before skipped slots and other losses. No continuous capture claim follows.

Provenance: receipts hash the host parser/campaign source. VERSION identifies the
expected variant, not the flashed app hash: the integrator must retain its
independent app-image verification. Only core 1 / 240 MHz is qualified here.
Source evidence is aggregate START/final completed counters, not an event-level
source trace. The retained synthetic wire fixture is produced by the actual C
emitter using fake hardware and synthetic decoder results; it is not RF evidence.

The qualified finish revision paces INFO and END delivery. Firmware session_us
is sampled before END output, not at host receipt. Successful ON controls require
complete END receipt before the conservative source deadline measured from the
host START send boundary. A 3 s plan is not a guarantee: the terminal pacing
upper bound alone is 4.5 s, and late completion rejects the result.
