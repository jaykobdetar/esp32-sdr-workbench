# Headless recording and acquisition

The GUI and `esp32-sdr record` share `sdr_research/acquisition.py`, a Qt-free serial owner
with bounded display/notice queues. The recorder does not import PySide6 or pyqtgraph and
does not require a display. Use the normal project installation, or invoke
`python -m sdr_research.cli record` from the source tree.

```sh
# Every detector run gets a summary, including no-candidate runs.
esp32-sdr record --port /dev/serial/by-id/YOUR_RECEIVER \
  --output records/unattended --mode DETPIPE1 --gain 40 \
  --run-ms 1000 --runs 100

# Stop starting new runs after an hour; finish the current bounded operation.
esp32-sdr record --port /dev/serial/by-id/YOUR_RECEIVER \
  --output records/one-hour --mode DET1 --gain 40 --duration-s 3600

# Hardware-free CLI check: two synthetic raw bursts, each saved as SigMF.
esp32-sdr record --demo --mode raw --runs 2 --output records/demo
```

Select the mode matching the installed firmware. No command flashes a receiver. Detector
modes require 10-bit captures; the recorder rejects incompatible arguments before opening
a port. A real port must be explicitly supplied. Only one process may own a receiver.
The UART remains at 1,000,000 baud.

Without `--runs` or `--duration-s`, recording continues until SIGINT (Ctrl-C), SIGTERM or an
error. Both signals request a graceful stop: the current finite run, bounded serial timeout,
retained transfer and recording finish before the radio closes. Duration is a limit on
starting another run, not a promise to interrupt a run at an exact instant. Exit status is
nonzero on acquisition or recording errors. Status/record notices and a final totals object
are printed as JSON lines.

Raw CLI mode saves **every** burst, unlike the GUI's optional candidate-only autosave.
Detector mode saves each summary and the available retained IQ. `--candidate-count 3`
opts into up to three shorter crops on compatible DETPIPE1 firmware advertising PIPEKEEP.
It is not enabled by default or in the GUI pending board validation. Each crop is saved
separately; `retained_sigmf_candidates` lists successfully saved files strongest-first, while
`retained_sigmf` preserves the legacy strongest-file reference. A partial save failure stops
recording and preserves the successfully saved filenames in the error summary. Trigger
uptime and crop offsets are kept in capture metadata, not relabelled as exact UTC RF arrival. Allow sufficient disk space;
errors stop acquisition rather than silently dropping recordings. Synthetic recordings are
marked in SigMF metadata. Detector performance is never simulated.

`--background-policy 1|2` selects the detector background rule on firmware that
advertises `BGPOLICY` (v7 and later): 1 is the historical optimized-v2 rule, 2 the
Q16 rule. Without the option the recorder selects the firmware default, 2, and
never inherits an earlier client's choice. Older firmware has one fixed rule and
refuses an explicit request. See [comparing the two rules](adaptive-detector.md#comparing-the-two-rules-on-one-image).

## Atomic run summaries

A `.det1.json` or `.detpipe1.json` file appears only after retained-IQ recording completes or
fails. The final document is written to a temporary file in the same directory, flushed and
renamed atomically. Consumers see a complete document, not an initial no-capture placeholder.
A capture-save failure is represented by `recording_state: error` and `recording_error`, with
`retained_sigmf: null` when no crop was successfully saved; the worker stops and reports the error. If the summary itself cannot
be saved, no successful publication is claimed. An abrupt process/power loss before publication
may leave IQ or a temporary file without a summary. Atomic visibility is not a guarantee of
cross-file transactionality or power-loss durability.

## Viewer controls and screenshot

The editable port picker lists pyserial's discovered devices and provides a Refresh ports
button. Refresh preserves manually entered paths and comma-separated `port@MHz` assignments;
it never opens a port. The viewer and recorder warn when hardware AGC is selected with a
detector: energies and candidate rates across gain steps are not directly comparable.
The warning does not silently change gain.

The README's `viewer-launcher-demo.png` was captured from the actual documented launcher,
not a window-construction smoke harness. It is explicitly a synthetic raw-IQ session and
shows the ADC end % event column. No real hardware-performance claim is made from it.
