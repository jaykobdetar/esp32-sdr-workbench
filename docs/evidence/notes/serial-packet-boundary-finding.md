# CP2102 ASCII reply boundary finding

## Observed failure

The fused-copy experiment initially appeared to fail while retaining an event: the host timed out waiting for `DETPIPE1 END`. Further repetition also failed in the **unfused control**, so this was not established as a fused-copy defect.

A timed raw transcript showed a valid 576-byte END line. Its first 512 bytes arrived about 2.006 seconds after a 2-second run began. The remaining 64 bytes did not arrive during the host's 7-second deadline. Sending an ordinary `INFO` query at about 10.035 seconds released those 64 bytes together with the 23-byte INFO response. The END itself reported status 0, matching processed/captured counts and approximately 2.001 seconds of firmware wall time. Host read calls had no long scheduling stalls; the maximum recorded blocking interval was approximately 0.101 seconds.

An earlier post-failure drain also contained 8,884 NUL bytes. That particular observation is preserved but not explained by the later clean timing transcript. It is not evidence of a proved stack overflow or memory corruption.

## Controlled test

A no-RF `FRAMEPROBE` command emitted predictable ASCII JSON lines with exact byte lengths. Two repetitions each tested 63, 64, 65, 511, 512, 513, 575, 576 and 577 bytes, both unmodified and with conditional padding. Each response had 0.4 seconds to arrive before an INFO query was sent as an explicit release control.

Results in both repetitions:

* Unpadded 64-byte line: zero bytes before INFO, complete correct line afterward.
* Unpadded 576-byte line: 512 bytes before INFO, final 64 bytes afterward.
* Adjacent unaligned lengths: complete before INFO.
* A full 512-byte response arrived without the stall.
* Padding an aligned line by one byte made every tested response complete before INFO.

This supports a CP2102/host USB bulk-packet boundary buffering issue on this setup. It does not identify which hardware/driver component is responsible, nor claim that every CP2102 behaves this way.

## Minimal correction

The isolated `v4frame` build adds one JSON whitespace character **before the final newline** of DETPIPE END only when its total length is divisible by 64. JSON meaning is unchanged. It emits neither an extra reply nor an unsolicited blank line. Binary DATA headers, capture payloads, CRC calculation and timeouts are unchanged. No OS, USB driver or security settings were changed.

The same helper drives the controlled probe. Full retained-event A/B and stability testing follows separately; a framing control alone does not validate the whole detector.

## Evidence

* `records/campaign/v4-reproduce-timed.json`
* `records/campaign/v4-reproduce-timed-rx.bin`
* `records/campaign/v4-reproduce-long.json`
* `records/campaign/v4-retention-timeout-serial.bin`
* `records/campaign/frame-probe-v4.json`
* `firmware-pipeline-frame/artifacts-pipeline-v4frame/`

The earlier `serial-alignment-probe.json` attempt using arbitrary SYNC strings was invalid: SYNC only accepts a numeric nonce and returned `ERR command`. Those responses were not used as alignment evidence.
