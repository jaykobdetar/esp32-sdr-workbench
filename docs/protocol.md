# Original-ESP32 release protocol

This documents the published `firmware/` original-ESP32 command path, not every historical upstream backend. Source authority: `firmware/main/common/burst_commands.h`, `burst_capture.h`, `burst_serial.c`, and `firmware/main/targets/esp32/receiver.c`. Unsupported lab commands are described separately in [diagnostic provenance](diagnostic-provenance.md).

## Transport and discovery

Commands are newline-terminated ASCII over UART, 8N1, no flow control. Query `TRANSPORT?` for the actual baud; do not assume a generic upstream baud matches this build. Drain boot text and synchronize with `SYNC <decimal nonce>` (reply `SYNC <nonce>`). Read the entire response, including any binary payload, before the next command. Errors start with `ERR`. Finite runs can emit several lines: the protocol is not universally one reply per command.

- `INFO` → `ESP32SDR 6 burst 16380`.
- `CAPS` → space-separated capability flags; query rather than infer from version alone.
- `VERSION?` → `VERSION {json}` with the actual firmware build identity.
- `TRANSPORT?` → `TRANSPORT UART <baud>` on this release's UART path.
- `RANGE?` → advertised minimum/maximum frequency and step in MHz.
- `LIMITS?` → JSON gain-index range, bandwidth range, sample rates and component bit depths.
- `FREQ <MHz>` → `OK` for accepted tuning. Acceptance does not establish PLL lock or calibrated RF sensitivity.
- `GAIN HARDWARE`, `GAIN MANUAL <index>` → `OK`; `GAIN?` reports mode/index and limits. Indices are not dB.
- `BANDWIDTH <MHz>` → `OK`; zero selects the widest setting. `LPF AUTO`, `LPF <0..127>` and `LPF?` expose experimental filter controls.
- `RELEASE` → `OK`, releasing the transport lease. `ERR busy` can indicate another active transport owner.

Discover spectrum support with `SPECINFO?` (see `firmware/main/common/spectrum.c` and the Python protocol adapter for their exact layouts). Do not treat spectra as calibrated power.

## Capture framing and encoding

`CAP <samples> <rate-code>` returns raw 32-bit words. `CAP20` returns packed signed 10-bit components; `CAP16` returns their upper signed eight bits. Sample count is 256–16380. Original ESP32 accepts rate codes 0 = 80 MS/s, 1 = 40 MS/s, 6 = 16 MS/s. Rates are nominal configured rates, not a measured timing calibration.

The header is `DATA <samples> <crc32-hex> <capture-us>\n`, followed immediately by exactly:

- CAP/raw: `4 * samples` bytes.
- CAP20: `(20 * samples + 7) // 8` bytes.
- CAP16: `2 * samples` bytes.

CRC32 is over the transmitted bytes, compatible with zlib CRC32. CAP20 concatenates 20-bit samples least-significant-bit first, without intersample padding: signed I is bits 0–9 and signed transmitted −Q is bits 10–19. Negate the second component to recover conventional Q. Raw words retain the upper metadata bits. CAP16 sends signed I followed by signed −Q. The capture time is firmware-observed elapsed time, not RF arrival time or uninterrupted RF aperture.

`RXRUN <samples> <rate-code> <repeats> <16|20>` returns repeated DATA/payload pairs followed by `END`; repeats are bounded at 1000. These are separate captures with gaps, not continuous streaming.

## Finite detector and pipeline

`DETINFO?` and `DETPIPEINFO?` return respectively `DETINFO 1 5000 16 64` and `DETPIPEINFO 1 5000 16 64`: protocol revision, maximum run milliseconds, warmup captures, energy block length.

`DET1 <ms> <samples> <rate-code> <ratio-milli> <retain>` and `DETPIPE1` with the same arguments accept 1–5000 ms, 256–16380 samples, supported rates, ratio 1000–1000000 and retention 0/1. They emit `<command> BEGIN` with the request fields plus frequency MHz, then `<command> END {json}` after finite acquisition. Errors may occur between BEGIN and END. Verify summary types, status, counts and requested settings, not just presence of END. `sdr_research/detector.py` and `sdr_research/pipeline.py` implement the host checks.

`DETGET` / `DETPIPEGET` retrieve retained CAP20 with the same DATA framing; missing retention is an error. `DETPIPECLEAR` releases retained pipeline data. `DETPIPEMEM?` reports allocation headroom. `DETPIPEALLOCTEST` is a bounded allocation diagnostic, not RF capture.

Pipeline selectors:

- `PIPEKERNEL <0|3>` and `PIPEKERNEL?`: reply `PIPEKERNEL <value>`.
- `PIPECOPY <0|1>` and `PIPECOPY?`: reply `PIPECOPY <value>`; fused copy is active only at the full 16380-sample length.
- `ACQOPT <0..3>` and `CLEAROPT <0|1>`: setters reply `OK`; queries reply `<name> <value>`.

Read back selectors. Acquisition timing includes overlapped prior-buffer work, so adding it to energy time double-counts work. Energy analyzes complete 64-sample blocks only (16320 of 16380 samples); guard/tail memory validation still covers the complete requested region and aperture. Histogram lab telemetry is not part of this release's detector stream. Some END JSON lines have ASCII whitespace padding for the documented UART framing workaround; parse JSON rather than require one fixed byte count.
