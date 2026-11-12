# RF Studio: a simpler way to use the radios

Launch the redesigned interface:

```sh
~/esp32-rf-studio/scripts/launch-studio.sh
```

The earlier RF Bench in `~/esp32-sdr-console` is unchanged. This is a new interface, not a firmware update. No firmware is flashed by the launcher or by a session.

## First session

1. Plug in the receivers. **Rescan USB** finds them without sending commands. Receiver numbers follow USB discovery; the USB location shown on each card distinguishes bridges with identical serial labels. A detected USB bridge is not yet a firmware health check.
2. Leave **Listen** selected. Both receivers are selected by default. The transmitter is not opened in this mode.
3. Choose a shared frequency and session length (or **Until I stop** for receive-only use), then **Start listening**. The app connects and verifies the receiver capabilities, opens **Watch live**, and stops at the selected deadline or when you press Stop.
4. Use **Inspect latest capture** for I/Q, power and FFT detail. **Recordings** contains past sessions; double-click a saved capture to inspect it.

Use **Explore with simulated data** to learn the layout without opening any serial ports. Simulated sessions are labeled throughout. It forces raw simulation for that session without changing the saved receiver-mode selection. Synthetic plots are not hardware results.

## Three tasks

- **Listen:** receive only, with one or more radios. It does not query or control an independently running transmitter.
- **Test a signal:** select the transmitter explicitly. Its packets use the same frequency as the receivers and start only after receivers return data. Default: 2 Mbps, 16-byte known packets, every 2 ms, −20 dBm. **Customize test packets** exposes rate, length and interval. Transmitter tasks remain finite (maximum 60 seconds); until-stopped mode is receive-only. A finite session stops the transmitter, verifies STOP, and restores its original packet configuration.
- **Compare receivers:** show two or more receivers side by side, without transmitting. To compare them under a known source, use **Test a signal** with both receivers selected.

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
- Session needs attention: read the plain-language result and optional diagnostic log. The session folder retains failure details. Do not assume transmission stopped when STOP is unconfirmed.

## Validation of this redesign

The new UI was exercised with two physical ESP32 receivers and one nRF52840 transmitter, with no firmware changes:

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
