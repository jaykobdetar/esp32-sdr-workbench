# Original-ESP32 release protocol

This documents the published `firmware/` original-ESP32 command path, not every historical upstream backend. Source authority: `firmware/main/common/burst_commands.h`, `burst_capture.h`, `burst_serial.c`, and `firmware/main/targets/esp32/receiver.c`. Unsupported lab commands are described separately in [diagnostic provenance](diagnostic-provenance.md).

The common wire framing is shared with historical optimized-v2. The current
`adaptive-q16-v3` source changes the background policy and adds metadata/crop
commands; those changes are [described below](#unflashed-adaptive-q16-v3-extension)
and have not been validated on a board.

## Transport and discovery

Commands are newline-terminated ASCII over UART, 8N1, no flow control. Query `TRANSPORT?` for the actual baud; do not assume a generic upstream baud matches this build. Drain boot text and synchronize with `SYNC <decimal nonce>` (reply `SYNC <nonce>`). Read the entire response, including any binary payload, before the next command. Errors start with `ERR`. Finite runs can emit several lines: the protocol is not universally one reply per command.

- `INFO` → `ESP32SDR 6 burst 16380`.
- `CAPS` → space-separated capability flags; query rather than infer from version alone.
- `VERSION?` → `VERSION {json}` with the actual firmware build identity.
- `TRANSPORT?` → `TRANSPORT UART <baud>` on this release's UART path.
- `RANGE?` → advertised minimum/maximum frequency and step in MHz.
- `LIMITS?` → JSON gain-index range, bandwidth range, sample rates and component bit depths.
- `FREQ <MHz>` → `OK` for accepted tuning. Acceptance does not establish PLL lock or calibrated RF sensitivity.
- `GAIN HARDWARE`, `GAIN MANUAL <index>` → `OK`. Indices are not dB.
- `GAIN?` → `GAIN <HARDWARE|MANUAL> <index> 0 <max-index> <forced>`: the index is `-1` under hardware AGC, and `<forced>` is the live force bit read back from the gain register. The matched-gain evidence archives these mode readbacks. They do not report the gain hardware AGC chose during every capture; current-source raw start/end register snapshots are separate telemetry.
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

### Historical optimized-v2 decision rule (policy 1)

The measured historical image applies this rule to each capture, in signed
10-bit ADC units. **Current adaptive-q16-v3 uses policy 2 below**, not this
positive-latching integer rule:

1. Split the capture into complete 64-sample blocks and compute each block's variance (mean-removed I and Q power). The capture's `mean` is the average block variance and its `peak` is the largest.
2. For the first 16 captures of a run, only accumulate: `background` is the running average of `mean`.
3. Afterwards a capture is candidate-positive when `peak * 1000 > background * ratio-milli`. Its score is `peak * 1000 / background`; the capture with the highest score in the run is the one retained.
4. Only captures that are **not** positive update the background, as `(63 * background + mean + 32) / 64`. A sustained rise in level is therefore never absorbed within a run.

`background` is an integer with a floor of 1, so at low signal levels the threshold moves in coarse steps.

### END summary fields

`DETPIPE1 END` carries one JSON object. The common numeric fields listed here
are non-negative integers; current-source candidate descriptors are a list.

| Field | Meaning |
|---|---|
| `version`, `kernel` | Summary revision (1) and the energy kernel that ran (0 or 3). |
| `status`, `errors` | 0 = clean; 1 = an acquisition failed; 2 = packing or internal accounting failed. `errors` is 1 whenever `status` is non-zero. |
| `captures`, `processed_captures` | Successful acquisitions and captures that reached the decision rule; they must match. |
| `warmup_captures` | Captures used only to seed the background, at most 16. |
| `detections` | Candidate-positive captures, not unique transmissions. |
| `background_adc2`, `best_ratio_milli` | Final background and highest score, as defined above. |
| `wall_elapsed_us` | Run wall time, the denominator of local duty. |
| `completion_observed_us` | Sum of trigger-to-done polling times. |
| `acquire_call_us_includes_overlap` | Time inside the acquire call, which includes the overlapped energy work. |
| `energy_compute_us`, `copy_us`, `decision_us`, `retention_copy_us` | Stage totals. They overlap the acquire time and must not be added to it. |
| `total_samples`, `analyzed_samples` | `captures * samples`, and the part in complete 64-sample blocks. |
| `retained_samples` | Size of the retained capture, or 0. |
| `frequency_mhz`, `sample_rate_hz` | Echo of the tuned frequency and nominal rate. |
| `acquisition_option`, `clear_option`, `copy_option`, `fused_active`, `pack_failed` | Selector readback and whether the fused path actually ran. |

`DET1 END` has the same shape without the kernel, copy and overlap fields; it reports `trigger_to_done_us`, `acquire_call_us` and `processing_us` instead. Historical summaries carry no gain or saturation information: the viewer adds requested gain settings and retained ADC-endpoint counts. Current-source gain/trigger fields are described below.

`DETGET` / `DETPIPEGET` retrieve retained CAP20 with the same DATA framing; missing retention is an error. `DETPIPECLEAR` releases retained pipeline data. `DETPIPEMEM?` reports allocation headroom. `DETPIPEALLOCTEST` is a bounded allocation diagnostic, not RF capture.

Pipeline selectors:

- `PIPEKERNEL <0|3>` and `PIPEKERNEL?`: reply `PIPEKERNEL <value>`.
- `PIPECOPY <0|1>` and `PIPECOPY?`: reply `PIPECOPY <value>`; fused copy is active only at the full 16380-sample length.
- `ACQOPT <0..3>` and `CLEAROPT <0|1>`: setters reply `OK`; queries reply `<name> <value>`.

Read back selectors. Acquisition timing includes overlapped prior-buffer work, so adding it to energy time double-counts work. Energy analyzes complete 64-sample blocks only (16320 of 16380 samples); guard/tail memory validation still covers the complete requested region and aperture. Histogram lab telemetry is not part of this release's detector stream. Some END JSON lines have ASCII whitespace padding for the documented UART framing workaround; parse JSON rather than require one fixed byte count.

## Unflashed adaptive-q16-v3 extension

Current source adds `background_policy: 2` and `background_q16` to DET1/DETPIPE1
END summaries while preserving their version-1 framing. Policy 2 keeps 16 warmup
captures, then compares peak energy with the previous Q16 background and adapts
on every capture: weight 1/256 for positives and 1/64 for negatives, with a
1/65536 ADC² floor. Integer energy processing itself is unchanged. This is a new detector
policy, not the measured optimized-v2 binary. Raw gain-register start/end
snapshots and device-monotonic trigger metadata are additive. See
[adaptive detector semantics and limits](adaptive-detector.md).

`PIPEKEEP 3` selects one-shot three-crop retention for the next valid DETPIPE1;
`PIPEKEEP 1` cancels it and `PIPEKEEP?` reads pending selection. Default remains
single full capture. END includes `retention_capacity` and `retained_candidates`
(slot, samples, offset_samples, generation, trigger_device_us, score_milli,
capture_us). `DETPIPEGET` returns strongest and `DETPIPEGET <slot>` retrieves an
occupied slot, using normal CAP20/CRC framing. Crops are bounded to 5120 samples;
320 µs at 16 MS/s but too short for the known 292 µs frame at 40/80 MS/s.
Firmware has not been flashed or board-soak validated; no new RF results claimed.
