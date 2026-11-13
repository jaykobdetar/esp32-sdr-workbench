# RF Studio: a simpler way to use the radios

From the installed repository checkout, launch the interface:

```sh
./scripts/launch-studio.sh
```

The earlier RF Bench remains available through `./scripts/launch-lab.sh`; the original viewer uses `./scripts/launch.sh`. This is a new interface, not a firmware update. No firmware is flashed by the launcher or by a session.

## First session

1. Plug in the receivers. **Rescan USB** finds them without sending commands. Receiver numbers follow USB discovery; the USB location shown on each card distinguishes bridges with identical serial labels. A detected USB bridge is not yet a firmware health check.
2. Leave **Listen** selected. Detected receivers are selected by default. The transmitter is not opened in this mode.
3. Choose a shared frequency and session length (or **Until I stop** for receive-only use), then **Start listening**. The app connects and verifies the receiver capabilities, opens **Watch live**, and stops at the selected deadline or when you press Stop.
4. Use **Inspect latest capture** for I/Q, power and FFT detail. **Recordings** contains past sessions; double-click a saved capture to inspect it.

Use **Explore with simulated data** to learn the layout without opening any serial ports. Simulated sessions are labeled throughout. It forces raw simulation for that session without changing the saved receiver-mode selection. Synthetic plots are not hardware results.

## Three tasks

- **Listen:** receive only, with one or more radios. It does not query or control an independently running transmitter.
- **Test a signal:** select the transmitter explicitly. Its packets use the same frequency as the receivers and start only after receivers return data. Default: 2 Mbps, 16-byte known packets, every 2 ms, −20 dBm. **Customize test packets** exposes rate, length and interval. Transmitter tasks remain finite (maximum 60 seconds); until-stopped mode is receive-only. A finite session stops the transmitter, verifies STOP, and restores its original packet configuration.
- **Compare receivers:** select two or more receivers without transmitting, then choose Combined, Individual or Both views. To compare them under a known source, use **Test a signal** with both receivers selected.

**Stop all devices** stops this session's selected devices. Closing the window normally also waits for cleanup. Do not force-kill the app during transmission. A failed STOP is shown as **Session needs attention**, never as success. If communication is lost, the transmitter's finite-duration run still has a configured endpoint, but an unconfirmed stop must not be treated as verified.

## What the display means

- The spectrum is the latest retained capture, not a continuously sampled RF stream. Its age is displayed.
- The waterfall advances once per retained capture. Its vertical axis is **capture index**, not elapsed time.
- Raw I/Q mode favors frequent inspectable waveforms over listening duty; serial readout creates substantial gaps. Event detector modes reduce readout frequency but may retain stronger unrelated activity instead of the desired packet.
- Estimated receiver duty is shown separately for each board. The UI does **not** synchronize their windows or calculate union coverage. Adding the percentages is not a coverage measurement.
- A candidate is not a decoded packet. The viewer does not automatically establish payload identity or packet recall.
- ADC endpoint percentage flags possible clipping. Consider reducing manual gain; endpoint samples alone do not prove a damaged receiver.

## Advanced controls

The default screen deliberately hides low-level tuning. **Show advanced radio settings** exposes raw/DETPIPE1/DET1 modes, sample rate, manual or automatic gain, bandwidth, sample count, detector window, background ratio and optional firmware policy. The hardware capability checks reject unsupported settings instead of guessing. AGC plus detector mode displays a warning because energy values are not comparable across gain changes.

The default recording destination is `~/rf-studio-recordings`. Each session gets its own timestamped folder with an atomic `session.json` and per-receiver files. These contain local device information and raw RF: keep them private unless reviewed and sanitized. Turning off **Save session and captures** uses memory only: no session directory, summary or raw files are written. The displayed result disappears when the app closes. History can open older RF Bench session folders too.

Custom payloads, hopping experiments, statistically controlled ON/OFF campaigns and the experimental dual-timing protocol remain CLI tools. This interface prioritizes straightforward live use; it does not replace calibrated experiments.

## If something fails

- No radios: reconnect, rescan, or explore simulation.
- Could not connect: close other radio applications, check USB connections, and retry. No automatic flashing is attempted.
- No retained data: wait for the detector window, inspect the advanced settings, or choose raw I/Q mode. The last plot's age helps distinguish an old capture from fresh data.
- Session needs attention: read the plain-language result and optional diagnostic log. When saving is enabled, the session folder retains failure details; memory-only sessions keep them only in the live result and diagnostic log. Do not assume transmission stopped when STOP is unconfirmed.

## Validation of this redesign

The initial UI/control checks below used two physical ESP32 receivers and one nRF52840 transmitter without flashing during those checks. They are historical checks of the ordinary modes, not validation of every later experimental stream binary:

- Five-second raw-I/Q test: both receivers delivered 14 captures; the transmitter completed 2,500 packets, reported zero radio errors, and confirmed stopped.
- Five-second detector-mode comparison: both receivers delivered retained captures and ended without acquisition errors.
- Normal window-close during a subsequent transmitter session: cleanup completed and STOP was confirmed. The transmitter was left stopped and its prior packet configuration restored.
- Software coverage includes simulation, explicit transmitter selection, readiness failures, repeated sessions, capture inspection/history, invalid output destinations, normal close, stale-data labeling, malformed saved summaries, and unconfirmed STOP handling.

These are UI/control tests, not a sensitivity, packet-recall, or continuous-coverage validation. Only one physical transmitter was available; multiple-transmitter support is inherited from the tested session engine but is not newly hardware-validated here.

## Paste settings or ask an LLM

Open **Paste settings / ask an LLM** on the setup screen.

1. **Copy LLM prompt** copies supported fields, units, bounds, interactions and your current portable settings. Paste it into your preferred LLM and replace the goal placeholder. No LLM service is contacted by RF Studio.
2. Paste its complete JSON response into the text box, without Markdown fences.
3. **Validate & apply** checks the entire document before changing any controls. Unknown/missing/duplicate keys, wrong types, out-of-range values and impossible packet timing are rejected. Errors leave the previous controls unchanged.
4. Review the controls. Device selection, simulation and recording directory remain local. Transmitters are deliberately deselected on import; explicitly select one for a Test task, then press Start separately.

**Use current settings** fills the editor with a valid portable example. The format includes all supported session, receiver and packet controls, but excludes USB identities, device selections, local paths, hopping and arbitrary commands. Pasting or copying never opens hardware. Firmware-specific capability checks still happen at session start. Import is disabled while a session is running.

### Until stopped, without recording

Uncheck **Save session and captures**, then choose **Until I stop · receive only**. Listen and Compare receivers can run without a preset deadline. Press **Stop all devices** or close the window normally to finish. Live frame queues and the diagnostic log are bounded; there are no session artifacts to fill disk. This is indefinite operation, not an unlimited-duration stability guarantee. Transmitter tests still require a finite duration of 60 seconds or less.

The memory-only mode was also verified on both physical receivers: 902 and 901 detector captures, three retained each, manual stop, no errors, and no output directory created.

## Combined and individual displays

The live view starts with **Combined**, a noncoherent diversity spectrum. **Individual** restores the separate receiver views, and **Both** shows them together (scroll if needed). Capture inspection always opens an actual individual receiver buffer, never fabricated combined I/Q.

The combined display averages FFT **linear power**, then converts back to dBFS. Opposite I/Q phases therefore cannot cancel as they would in a naive sample sum. Only transport-CRC-valid, finite samples from the same frequency, sample rate and ADC format are eligible; the newest valid buffer defines the compatibility group. Ordinary-mode inputs older than two seconds by local arrival time are excluded; sparse stream snapshots use the explicitly labeled eight-second limit described below. This freshness test is not a proof of simultaneous RF acquisition. Samples exceeding 1% ADC endpoints are excluded when a cleaner receiver exists; if all are clipped, a clearly labeled least-clipped single-receiver fallback is used. The UI lists contributors and exclusions.

This can provide one easier-to-read power view, but is **not** a phase-coherent receiver, calibrated combined RF amplitude, continuous I/Q waveform, coverage measurement, or proof of improved packet recovery. Independent gain and calibration differences remain. Averaging asynchronous bursts may dilute a transient seen by only one receiver. Preserve individual views for diagnosis. After Stop, the last combined result is explicitly marked as stopped; no new samples are implied.

## Experimental persistent telemetry + sparse I/Q

The Advanced receive-mode selector includes **Experimental persistent telemetry + sparse I/Q** (`DSTREAMIQ`). It requires compatible experimental firmware already installed; selecting it never flashes a board. Older firmware fails the capability check rather than silently falling back.

This mode keeps detector telemetry running while periodically transferring a complete I/Q snapshot, approximately every five seconds. Sample rate is fixed at 16 MS/s, capture size at 16,380 samples and precision at 10 bits. The detector ratio and supported background policy remain adjustable; the ordinary detector-window control is disabled. Acquisition period is 1.875 ms, tick-aware yield phase 32, snapshot interval 2667, snapshot phase 0. Each command is bounded to 600 seconds; until-stopped sessions restart commands and therefore introduce restart gaps. Stop is cooperative and waits for firmware acknowledgement.

**These UI streams start independently. They are not clock-aligned or staggered by the calibrated dual-receiver campaign. Do not assign that campaign's coverage result to this interface.** Continuous telemetry is not continuous stored I/Q, and neither is a packet-recall measurement. The combined spectrum uses only sparse full snapshots, with an explicitly displayed age and an 8-second freshness limit (ordinary modes retain the 2-second limit). Individual I/Q inspection remains available.

No-save mode creates no output path. With recording enabled, a separate bounded queue writes both sparse captures and chunk summaries without filesystem calls on the acquisition thread; a full queue or writer error fails the session instead of silently discarding I/Q. Only per-chunk summaries and sparse snapshots are saved, not every telemetry record. The in-memory rendering queues remain bounded.

Sparse recording shutdown waits at most five seconds for the writer. If a filesystem operation remains blocked, radio cleanup can finish and the session reports incomplete recording; the daemon writer may finish that in-flight operation later, but it will not start further queued writes. No-save does not start this writer.

For the experimental stream design, see [combined-receiver concepts](continuous-dual-receivers.md) and the [sparse-I/Q protocol](sparse-iq-stream.md). [Build-specific evaluation evidence](evidence/dual-stream-evaluation/README.md) distinguishes intermediate candidates and timing models from the current source. Do not transfer a result from one binary to another.
