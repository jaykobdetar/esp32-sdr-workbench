# RF Bench: a shared transmitter / receiver console

Start the native application with `./scripts/launch-lab.sh`, or run
`esp32-sdr lab` in an installed environment. It reuses the workbench receiver
and nRF transmitter libraries; it does not flash either device.

## First session

1. Close other programs using the radio serial ports. Refresh USB devices.
2. Select the receivers. Transmitters are **unchecked by default**. Device
   tooltips expose the USB-location path; use that to distinguish receivers
   whose USB serial labels are identical. Moving a cable changes its location.
3. Choose each receiver's frequency in the device table. Acquisition mode,
   sample rate, gain, bandwidth and detector settings apply to all selected
   receivers. Start with manual gain for comparable detector energies.
4. To generate known packets, explicitly select the nRF transmitter and set
   its frequency, modulation, power, packet size and interval. Initial defaults
   use 2440 MHz, 2 Mbps, −20 dBm and a 2 ms interval. The same transmitter
   settings apply to every selected transmitter. Multiple sources may interfere.
5. Choose a finite session length (at most 60 seconds) and output directory,
   then click **Start selected devices**. Receivers must capture successfully
   before transmitters start. A packet cap of zero means the finite time limit,
   not unlimited transmission.
6. **STOP ALL** ends the session early. Closing the window normally also waits
   for orderly cleanup. The final transmitter display distinguishes confirmed
   STOP from uncertain STOP. Never force-close the desktop window.

A session takes control of selected devices. If a selected transmitter is
already active it is stopped rather than silently reconfigured. After a normal
session, transmitter configuration is restored but transmission is not restarted.
A USB failure may prevent STOP confirmation; the firmware's finite duration
remains a second limit. Investigate any uncertain STOP message before reuse.

## What is displayed and saved

The shared plot overlays the latest spectrum from each receiver. Per-receiver
rows show completed runs, capture count, retained captures, nominal sampled
seconds divided by host elapsed session time, and ADC endpoint percentage.
Endpoint counts flag possible clipping, not calibrated RF power. **Inspect latest
I/Q** opens the existing waveform/spectrum inspector. **Open recordings** opens
the session directory.

Each session has an atomically written `session.json`, separate receiver folders
with normal workbench summaries and recordings, transmitter counters, and cleanup
results. These are local research records: they can contain USB paths, identifiers
and raw environmental RF. Do not publish them without reviewing and sanitizing.

**Demo · no hardware** runs two clearly labeled synthetic receivers with no
transmitter access. Use it to learn the controls; demo results are not measurements.

## Limits

This is shared host control of independent acquisition workers, not phase-locked
acquisition. Starting workers together does not synchronize their RF windows.
Per-receiver duty percentages must not be added to infer combined coverage or
packet recall. The previous experimental staggered dual-receiver timing scripts
remain separate; their measured coverage does not apply to this console.

The interface supports multiple transmitter rows, but only one physical nRF
transmitter was available for testing. Multi-transmitter lifecycle behavior is
covered by host regression tests, not a multi-transmitter RF experiment. No
firmware-update UI or automatic flashing is included.

## Validation

On November 12, 2026, the interface was exercised with both connected ESP32s
and the nRF source at −20 dBm. A three-second run completed 1,500 transmitter
radio completions with zero reported TX errors; both receivers recorded data.
A normal window-close test also checked early cleanup. This validates integration,
not detector sensitivity, packet recall or synchronized coverage.
