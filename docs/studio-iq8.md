# RF Studio raw I/Q precision

The **Advanced → Raw I/Q format** selector offers IQ10 (10 bits per component,
unchanged default) and IQ8 (8 bits per component). IQ8 uses the existing CAP16
firmware command. It discards the lowest two bits of each signed ADC component:
20% fewer payload bytes than CAP20, at a precision cost. It is not lossless and
is not a packet-recovery or continuous-coverage guarantee. Snapshot sample count
and nominal sample rate are unchanged.

The selector is available only for raw mode. Selecting DET1, DETPIPE1 or
DSTREAMIQ resets it to IQ10 and disables it. Returning to raw leaves IQ10 selected
until you explicitly choose IQ8 again. Starting, stopping and restarting a raw
session preserves your selected format. Each receiver's session settings and
saved capture retain the actual component precision.

Portable settings exports include `bits_per_component` (8 or 10). Legacy
schema-1 documents that omit it still import as IQ10. Imports requesting IQ8
with a detector or DSTREAMIQ mode are rejected without applying partial settings
or starting hardware. Format settings never select a transmitter or flash a
receiver.

Two- and four-receiver simulation respect the selected format. Synthetic samples
are quantized to a signed IQ10 grid first; IQ8 then uses the same upper-eight-bit
truncation as CAP16, with complex64 values matching the host representation.
Simulation stays explicitly synthetic: its CRC flag is not hardware transport
evidence, and its cadence is not a USB throughput benchmark.
