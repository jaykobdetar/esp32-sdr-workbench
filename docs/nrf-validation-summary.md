# Controlled RF transmitter and ESP32 validation

**Publication scope:** This report describes the completed local experiment. Paths under `records/`, firmware artifact directories and recovery directories below are archival provenance labels, not public download links. The [public evidence](evidence/nrf-validation/README.md) contains scrubbed numeric exports and known test-packet bytes; raw I/Q, flash backups and binaries are withheld. This publication did not repeat hardware measurements or change the devices. Historical test counts below are not the current public-checkout test count.

Date: 11 November 2026
Source: local research archive; public export described in [evidence](evidence/nrf-validation/README.md).

## Result

The Makerdiary dongle now runs a USB-controlled RF test transmitter with a verified, hands-free application-update path. The ESP32 captured and decoded real known Nordic 2 Mbps packets, including their address, sequence number, complete payload and over-air CRC.

The optimized receiver increases observation time and source-dependent candidate detections. It does **not** reliably retain the useful packet from a long detector run: selecting only the strongest event often saves unrelated interference or a packet cut by a capture boundary. A tested alternative retention policy did not demonstrate a statistically convincing improvement, so the original optimized receiver was restored.

## Verified deliverables

- Transmitter firmware **0.2.2**, source, guarded UF2 image, binaries and build instructions.
- Independent Python USB controller and application-only update script.
- Reproducible controlled ON/OFF, offset-frequency, parameter-screen and actual-image ABAB experiments.
- **550 controlled raw I/Q files**, with successful UART transport CRC checks. **25 files** contain at least one complete known packet with verified address, payload and RF CRC. These totals are artifact counts, not a packet-recall estimate.
- Machine-readable run results, source counters, timing, settings, per-file checksums, analysis JSON and diagnostic figures.
- An isolated retention-policy experiment, kept as an unadopted research artifact.
- A finite multi-receiver coordinator with independent settings, host offsets and combined reports. Fake multi-device tests passed; the one attached receiver also passed a real coordinator health check.

## Automatic updating and recovery

The device was already in UF2 mode when work began. Its reported board is `nRF52840-MDK-USB-DONGLE`, bootloader 0.7.1; read-only silicon identification reports nRF52840 variant AAD0, 256 KiB RAM and 1024 KiB flash.

The installed factory image includes S132 5.1.0 below **0x23000**. Custom applications therefore start at **0x23000**, not the generic no-SoftDevice example address 0x1000. The updater rejects images outside 0x23000–0x3ffff, bootloader-family images, malformed blocks, wrong board/serial, invalid vectors and missing update capability.

`BOOTLOADER` stops the radio, acknowledges the command, writes **GPREGRET = 0x57**, then resets. That mechanism was checked against Makerdiary source and its published 0.7.1 release binary, then verified on this dongle. Multiple complete application-to-UF2-to-new-application cycles succeeded without a button press. Every update records a backup and checks the new version, updater support, health and stopped state.

All images used by the experiment were application-only. Public distribution contains source, not device images. No bootloader replacement, chip erase, direct UICR write or direct bootloader-configuration write was performed. Read-only hashes before and after the final update matched for MBR, SoftDevice, bootloader code, configuration, documented UICR words and the observed settings page. These are post-install preservation checks, not a pre-install whole-chip backup. The factory UF2 implementation may maintain its own application bookkeeping; the updater does not promise that every settings byte is immutable across arbitrary updates.

The original `CURRENT.UF2`, identification files and extracted factory application are archived. `CURRENT.UF2` does not include the inaccessible bootloader/MBR/UICR regions. The published bootloader code is not an exact CRC match to the installed code, although version/model, configuration, MBR and software entry are verified. No exact factory-binary identity is claimed.

Manual fallback: unplug the dongle, hold its button while plugging it back in, then release it. Confirm the green LED and **UF2BOOT** volume. Use the guarded updater with `--initial` and a known-good custom application. See `nrf52840-transmitter/docs/recovery-and-update.md` for factory-application recovery and limitations.

## Transmitter capabilities and timing

Commands support configuration, start, stop, status, health, read-only device diagnostics and bootloader entry. The exposed conservative operating range is 2402–2480 MHz, Nordic 1/2 Mbps, −40 to 0 dBm, 8–252 payload bytes, finite counts/durations, seeded interval jitter, repeating payload patterns, hopping lists and packet bursts.

Packets carry `RFTX`, a sequence number and known payload bytes. Completed counters use RADIO END events. The final version fixes a race between STOP and a completing packet. Four bounded 40-packet mode/pattern/hop/burst checks and 20 cancellation checks passed on hardware; the transmitter is stopped now.

Scheduling is software-polled. The logs expose missed slots and actual launch lateness rather than claiming hardware-precise timing. USB control can add sub-millisecond or approximately millisecond outliers. No missed-slot increases occurred inside the 17-setting screen's recorded brackets, but that does not eliminate timing jitter. Completion latency is an observed END-event latency, not calibrated over-air duration.

## Main measurements

All following figures apply to the recorded USB placement, not a calibrated laboratory path. The useful fixed-gain setting was gain index 60; gain 80 showed clipping. RF gain indices are not calibrated gain in dB.

### Direct source attribution

At 2440 MHz, 0 dBm configured TX power, 2 Mbps and 64-byte payloads, all four raw ON buffers in the controlled gain-60 campaign decoded completely, compared with zero of four OFF buffers. The 2470 MHz offset controls had no exact known-header matches. Mean raw ON power exceeded OFF by 22.56 dB in that small controlled set.

This attribution is based on recovered known information and RF CRC, not environmental energy alone. UART capture CRC and Nordic packet CRC are recorded separately.

### Historical versus optimized firmware

The actual preserved historical and optimized applications were flashed in ABAB order, with four randomized ON/OFF pairs in each phase and identical source settings.

| Measurement | Historical DET1 v2 | Optimized v2 |
|---|---:|---:|
| Nominal local RF duty | 32.11% | 62.33% |
| Nominal host-run RF duty | 26.50% | 51.09% |
| Source-dependent candidate excess, cycle 1 | 134.60/s | 236.37/s |
| Source-dependent candidate excess, cycle 2 | 131.19/s | 234.08/s |
| Full RF-CRC-valid retained buffers, ON | 1/8 | 0/8 |
| Complete known payloads, ON | 1/8 | 2/8 |

The optimized source-dependent excess was about **102 candidate windows/s higher in both cycles**. Candidate windows are not distinct packets. The two optimized payloads lost a leading address or trailing CRC at the capture boundary; absent bits are not CRC failures. No exact known markers appeared in the 16 OFF buffers.

The host-run denominator includes commands and retained-data transfer. Each campaign JSON also records whole-campaign time including source control, settling, recording and gaps. Neither denominator proves continuous observation. The paired confidence intervals and small-sample/time-order caveats are in `docs/controlled-rf-analysis.md`.

### Parameter screen

Seventeen configurations tested power, 8/32/64/128-byte payloads, packet interval, 1/2 Mbps mode, 16/40/80 MS/s, bandwidth, threshold, buffer size, hopping and bursts. This was one-factor screening with three ON/OFF pairs per detector mode, not an exhaustive factorial or sensitivity certification.

- A complete **8-byte payload packet** passed address and RF CRC checks. Its nominal on-air duration is about 68 µs with this framing and 2 Mbps rate. This is a successful short-packet observation, not a minimum reliable duration.
- At 80 MS/s, 16,380 samples span only **204.75 µs**. A 64-byte payload plus its length byte alone needs **260 µs** at 2 Mbps, so complete recovery cannot fit in that buffer.
- Source-dependent candidate excess was clear at configured −8 and 0 dBm in this placement, but not consistently separated at −20 or −40 dBm. These are transmitter settings, not a measured receiver sensitivity in dBm.
- The 1 Mbps trials recovered correct partial known payloads but no complete frame. This is partial reception evidence, not proof that the radio mode failed.
- Hopping and burst schedules ran with actual END counters and finite safety bounds. No hopping-packet recall or continuous-frequency coverage was established.

### Retention-policy experiment

A separate build added seeded reservoir selection without another IQ buffer. Twelve paired ON/OFF repeats compared it with the strongest-event policy on the same image. Equal fine CFO refinement was applied to all 48 recordings.

- Complete RF-CRC-valid ON buffers: reservoir **3/12**, strongest **2/12**.
- OFF: **0/12** for each policy, with no exact known-header matches.
- Paired difference: +8.33 percentage points; bootstrap 95% interval −16.67 to +33.33 points; exact McNemar p = 1.0.

That is **not demonstrated superiority**. The original optimized image and strongest default were restored. The experimental source and results remain available for reproducibility, not as an adopted improvement.

## What is not established

- Packet recall or precision from candidate-count/transmission-count ratios.
- Calibrated received power, minimum reliable signal strength or distance thresholds.
- Precise radio-time matching from host timestamps.
- Continuous reception from one or multiple ESP32 devices.
- The Quest controller protocol, or reliable interception of its real hopping traffic.
- General superiority of reservoir retention, or exhaustive performance over all settings.

Antenna separation/orientation was not measured, and only one ESP32 was available. Measured-distance trials require physical repositioning. A two-receiver experiment needs a second device plus timing/coverage evidence.

## Recommended next work

1. Preserve several candidate buffers or stream a bounded sample of candidates, so packet recovery is not determined by one peak-ratio winner.
2. Record per-capture hardware timestamps and source launch timestamps, with measured clock uncertainty, before attempting packet-level recall.
3. Evaluate a narrowband GFSK-aware or boundary-aware retention score against held-out controlled recordings, then benchmark its processing cost and RF duty on hardware.
4. Repeat distance/power trials with measured antenna geometry. Use a calibrated RF path before making sensitivity claims.
5. For multiple receivers, add a shared timing reference or calibrated trigger/clock mapping; measure overlap and gaps rather than summing nominal duties.

## Final state and entry points

- Dongle: **RF test transmitter 0.2.2, healthy, stopped**. Conservative next-run configuration: 2440 MHz, 2 Mbps, −20 dBm, 64 bytes, 10 ms interval, no hopping or bursts.
- ESP32: **original esp32-pipeline-optimized-v2 restored**, application SHA256 `8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad`.
- Controller: `nrf52840-transmitter/host/rf_tx.py`.
- Updater: `nrf52840-transmitter/host/flash_uf2.py`.
- Experiments: `scripts/nrf_rf_campaign.py`, `nrf_receiver_compare.py`, `nrf_parameter_screen.py`, `nrf_retention_campaign.py`.
- Offline decoder/figures: `scripts/analyze_nrf_iq.py`.
- Detailed analysis: `docs/controlled-rf-analysis.md`.
- Complete local data: `records/nrf-*`.

The final workbench/controller test pass was 313 tests. Separate build-archive tests passed collision refusal, manifest/checksum validation and a real isolated build. Firmware retention tests passed 70 tests plus 70 subtests. Transmitter source tests cover scheduling, parsing, CRC, diagnostic routing and STOP races. Exact logs, commands, checksums and validation scope accompany the artifacts.
