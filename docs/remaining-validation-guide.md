# Remaining SDR validation: practical bench guide

This is a plan, **not a record of completed tests and not an instruction to flash
or transmit immediately**. Reading, publishing or building this guide does not
install firmware or authorize a new hardware session. Arrange an attended test
window, confirm the exact devices and RF conditions, and approve any deliberate
firmware installation before starting.

## What is actually left

The original 19-item list is not simply “16 done, three untouched”:

- Item **17 already has a pilot**: 24 matched one-second AGC/manual ON/OFF runs on
  unchanged `esp32-pipeline-optimized-v2`, at −20 dBm. Four blocks were variable;
  AGC-minus-manual exact sign-flip p was 0.25 for both manual settings. This does
  not establish packet-detection superiority. [Pilot and evidence](matched-gain-comparison.md).
- Item **18 is not done**: physical geometry was unmeasured. Distance/power claims
  require measured placement, controls and repetitions.
- Item **19 is done as UI documentation**: an actual launcher screenshot shows the
  ADC-endpoint column in explicitly synthetic mode, not new RF performance.
- Items **13–16 have new source and host/compile checks**, but the new
  `esp32-pipeline-adaptive-q16-v3` image has not been flashed or board-soak tested.
  Three-crop retention remains opt-in.
- CI configuration, packaging and release notes exist. A public tag/release is a
  separate decision; successful publication or CI does not validate RF behavior.

The three bench workstreams below are: **A. validate the new firmware safely;
B. strengthen matched gain and retained-packet evidence; C. measure distance and
power effects**. An operational CI/release checklist follows separately.

## Common preparation

### Equipment and records

Required for the initial work:

- The verified original ESP32 receiver with compatible flash/partition layout and
  CP2102 UART, plus its known-working recovery application and private backup.
- The identified Makerdiary nRF52840 MDK USB Dongle running known RF-test firmware,
  reliable USB cables/power, and a host with exclusive access to both serial ports.
- A tape/ruler or laser measure; nonconductive marked mounts; a way to record
  antenna reference points, orientation, height and obstructions. Photograph the
  setup for private records, avoiding people, addresses and unrelated information.
- Enough disk space for raw IQ and summaries. Each full 16,380-sample cf32 capture
  is 131,040 data bytes before metadata; three 5,120-sample crops total 122,880
  data bytes per retained run. Allow extra space for logs, backups and raw controls.
- A lawful controlled RF location. A suitable shielded enclosure or verified
  conducted setup is preferable where practical. Do not connect RF ports directly
  without checking available ports, impedance, attenuation and input limits.

Useful for stronger claims: a calibrated source/attenuator and power meter for
sensitivity, an RF-quiet or properly terminated input for a noise-floor control,
and independent packet/timing instrumentation for recall. A second receiver is
needed for genuinely simultaneous two-receiver work. None of these capabilities
is established by the current single-receiver bench.

### Human actions versus automation

The operator must identify boards/ports, inspect recovery and security state,
choose lawful RF limits, measure/reposition antennas, keep people/objects clear,
and decide when installation or rollback is appropriate. Software can build,
hash, validate readbacks, run finite acquisition, stop the source, record data and
compute statistics. It cannot infer real separation from a photo, prove an
uncalibrated receiver's sensitivity, or replace physical safety checks.

Close the SDR viewer through its normal application controls before serial work.
Do not close unrelated applications, force-close desktop windows, run multiple
serial owners, change device permissions or use root as a shortcut.

Use persistent device paths and your own private transmitter identity. These are
placeholders, not runnable defaults:

```sh
export RX_PORT=/dev/serial/by-id/YOUR_VERIFIED_RECEIVER
export TX_PORT=/dev/serial/by-id/YOUR_VERIFIED_TRANSMITTER
export RF_TX_SERIAL=YOUR_16_UPPERCASE_HEX_TRANSMITTER_SERIAL
export PRIVATE_RUN_ROOT="$HOME/private-sdr-validation"
mkdir -p "$PRIVATE_RUN_ROOT"
```

Do not publish USB identities, full flash/NVS, private absolute paths or raw RF
without a separate review. Keep exact device identity privately even when public
reports use generic receiver/source labels.

### Freeze the experiment before collecting data

Record Git commit and clean/dirty state, host package/dependency versions, SDK and
compiler versions, application binary SHA-256, partition/configuration files,
actual `VERSION?`, and source firmware identity. A local application hash alone
is not proof of installed flash identity. Preserve the installation and readback
verification separately. Rebuilding may change timestamps and layout; every
rebuild is a new binary even if its friendly variant name is unchanged.

Write down the primary question and endpoint before looking at results. Record
run duration, sample rate/count, gain mode/index, bandwidth, threshold, retention
count, frequency, payload, PHY rate, packet interval/jitter, source power and all
finite safety ceilings. Change one factor at a time during diagnosis. Never
combine data from different images, gains, geometry or RF powers as if they were
one repeated condition.

## A. Validate adaptive firmware on the board

### A1. Recovery and installation gate

Follow [firmware build and flashing](firmware-build.md), including detected flash
capacity, private full-flash backup/hash, security-state review, existing/new
partition comparison and application-size check. Stop for secure boot, flash
encryption, an unknown layout or a missing compatible recovery application.
Do not assume the illustrative 4 MB backup size or 0x10000 application offset is
correct for another board. A backup file is not a demonstrated recovery procedure.

Build a clean, identified source revision with the exact pinned SDK. The following
only compiles; it does not flash. Use a fresh output directory:

```sh
# First activate the pinned SDK using firmware-build.md.
REV=$(git rev-parse HEAD)
python firmware/tools/build_firmware.py \
  --profile esp32 --version "$REV" --jobs 4 \
  --build-root "$PRIVATE_RUN_ROOT/build-$REV" \
  --output "$PRIVATE_RUN_ROOT/artifacts-$REV"
```

Confirm embedded variant `esp32-pipeline-adaptive-q16-v3`, actual revision and
hash. Only after the installation gate is satisfied and installation is approved,
use the build guide's **application-only** route on a compatible existing layout.
Do not run generic full-chip erase, replace the bootloader/partition table to make
an incompatible image fit, or overwrite NVS/calibration. `app-flash` can rebuild;
record the actual final flashed binary, not just an earlier export.

Retain the known-good optimized-v2 application and its compatible layout records
outside the public repository. If rollback is needed, stop RF, close both serial
owners normally, and deliberately restore that verified application using its
matching layout procedure. Never substitute another board's full-flash dump.

### A2. Short passive acceptance checks

Keep the source stopped. In one exclusive receiver session, log `INFO`, `CAPS`,
`VERSION?`, `TRANSPORT?`, `LIMITS?`, `GAIN?` and selector readbacks. Require the
expected image, UART 1,000,000 baud and `PIPEKEEP` capability before testing crops.
Then collect a few direct raw captures and finite detector runs. For example,
after successful installation and source-stop verification:

```sh
esp32-sdr record --port "$RX_PORT" --mode raw --gain 40 --bits 10 \
  --frequency-mhz 2440 --rate-hz 16000000 --bandwidth-mhz 12 \
  --samples 16380 --runs 5 --output "$PRIVATE_RUN_ROOT/passive-raw-01"

esp32-sdr record --port "$RX_PORT" --mode DETPIPE1 --gain 40 \
  --frequency-mhz 2440 --rate-hz 16000000 --bandwidth-mhz 12 \
  --samples 16380 --run-ms 1000 --runs 5 \
  --output "$PRIVATE_RUN_ROOT/passive-single-01"

esp32-sdr record --port "$RX_PORT" --mode DETPIPE1 --gain 40 \
  --frequency-mhz 2440 --rate-hz 16000000 --bandwidth-mhz 12 \
  --samples 16380 --run-ms 1000 --runs 5 --candidate-count 3 \
  --output "$PRIVATE_RUN_ROOT/passive-three-01"
```

Use new directories for every block. Do not interpret a run with no retained IQ
as a failed CRC or assume passive ambient activity will populate all three slots.
Controlled ON runs are needed later to exercise retention reliably. Record all
summaries, including no-event runs and failed runs, rather than selecting only
attractive captures.

Require valid transport CRC for every downloaded buffer; consistent capture,
processed, warmup and sample counters; zero error/packing status; valid crop bounds
and distinct retained generations; and no resets, watchdogs, serial framing errors
or hangs. Verify `background_policy=2`, Q16 consistency, gain snapshot fields and
monotonic trigger order. Device uptime is not UTC or calibrated RF arrival.
Check that the one-shot three-crop selection resets and a subsequent ordinary
single-candidate run returns the normal full-size behavior.

### A3. Memory, stack and soak gate

`DETPIPEMEM?` currently returns free DMA-capable internal heap and largest free
block. Sample it at comparable boundaries: after `DETPIPECLEAR`, after retained
allocation/run, and after clearing again. Compare like-for-like states; retained
pages intentionally consume memory until cleared. Stable total free bytes alone
does not rule out fragmentation or transient peaks.

`DETPIPEALLOCTEST <samples> <retain>` is a finite allocation diagnostic, but it
checks the legacy allocation pattern, not a complete three-crop soak. Do not
present it as proof that all twelve new crop pages work on the board.

**Instrumentation still needed:** no existing command reports task-stack high-
water mark or the true minimum heap during a run. Add and host-test bounded
telemetry for these before claiming measured stack margin/transient heap safety.
Document the pinned SDK's stack-unit convention. Record the instrumentation's
source/binary identity; instrumentation can affect timing. Define a conservative
required margin before the test instead of declaring any nonzero margin a pass.

Stage the run length, inspecting logs between stages: 5×1-second single/crop runs,
then 20 alternating 5-second runs per retention mode, then an attended 30-minute
soak with finite individual commands. These are suggested engineering gates,
not a statistical proof of long-term reliability. Begin passively; introduce the
controlled finite source only after short checks pass. Alternate modes and repeat
from a fresh boot to expose fragmentation and order effects. Use a dedicated
single-owner harness for pre/post-run heap logging; the recorder CLI alone does
not sample heap or stack between runs.

At full capture length, three crops pack into 38,400 bytes versus the old 40,950,
but use twelve page allocations instead of ten, larger summaries, and extra crop
scanning/copy work. At shorter capture sizes three crops can use more memory than
the corresponding old single capture. Exercise 256, 2,048, 8,192 and 16,380 samples,
then bounded rate/control combinations. Do not disable guards, yields or deadlines
to improve throughput. Deliberate host fault tests belong in mocks; do not corrupt
on-device memory merely to simulate failure.

**Stop and investigate:** any CRC/guard/accounting error, reset/watchdog, leaked
post-clear heap, shrinking largest block, inadequate stack margin, stale timing,
failed cleanup or unexpected policy readback. Preserve failed evidence, stop the
source, and reconnect only after resolving uncertain framing. Roll back before
normal use if the new image cannot pass. Passing permits the next experiment;
it does not prove higher packet yield.

## B. Stronger matched gain and retained-packet validation

### B1. Respect the completed pilot and current runner limits

The pilot measured candidate windows/local-second OFF→ON of approximately
178.7→393.6 for AGC, 81.6→100.8 for manual40 and 175.4→164.9 for manual60 at
−20 dBm. AGC had ADC endpoints in 7/8 selected buffers; neither manual setting
had endpoints in its selected buffers. Selection bias, drift and four blocks
prevent a general ranking. Zero endpoints does not establish analog linearity.

The existing `nrf_gain_compare` runner deliberately accepts **optimized-v2 only**.
For an explicitly authorized repetition on that unchanged image:

```sh
python -m nrf_campaigns.nrf_gain_compare \
  --rx-port "$RX_PORT" --tx-port "$TX_PORT" --tx-serial "$RF_TX_SERIAL" \
  --rx-artifact /PRIVATE/PATH/TO/VERIFIED_INSTALLED_APPLICATION.bin \
  --output-directory "$PRIVATE_RUN_ROOT/gain-pilot-repeat-01" \
  --pairs 8 --manual-gains 40 60 --milliseconds 1000 --power-dbm -20 \
  --seed 52840 --geometry 'REPLACE WITH MEASURED FIXED PLACEMENT'
```

Eight pairs here are an engineering extension, not a justified confirmatory
sample size. The runner supports even block counts 2–16 and currently labels
geometry unmeasured; retain a separate measured setup record rather than changing
that flag after the fact without provenance.

**New-firmware comparison requires additional runner work.** Do not disable its
variant guard to get it running. Add an explicit expected-image selection, AGC/
manual settings, retention-count handling, pre/post gain/heap telemetry, and
per-crop saved references. Preserve finite TX count/time ceilings, exact USB
identity, STOP/final-state checks, failed-run reporting and cleanup tests. The
existing receiver-compare runner supports explicit new variant matching for
manual-gain single-retention tests, but is not already a matched AGC/three-crop
experiment. Validate the extended plan with fake devices before hardware.

### B2. Design and collect

1. Use the same measured geometry and fixed source frequency/power/format within
   a block. Match detector duration, sample rate/count, threshold, bandwidth and
   retention budget. Repeat single versus three-crop conditions separately so
   gain and retention effects are not silently combined.
2. Counterbalance ON/OFF and gain/retention order within blocks; randomize block
   order with a recorded seed. Repeat across separate sessions/days or placements
   if the conclusion is meant to generalize. For old/new firmware, separately
   approved application changes and AB/BA session order are needed; no runner
   should silently flash between observations.
3. Start with a small diagnostic pilot. Choose a meaningful effect and primary
   endpoint, estimate variability, then plan a new held-out sample size before
   confirmatory collection. More repeated windows inside one run are not more
   independent experimental units. Predefine handling of failed/expired runs and
   report exclusions and replacements; do not retry selectively until p is small.
4. Retain counts/exposure from every run, source configuration and before/after
   status/counters, gain readbacks/snapshots, crop metadata, raw controls, hashes,
   endpoint counts and all errors. Confirm the source is actually running for
   valid ON observations and stopped for OFF. OFF means this source is off, not
   an RF-silent room. Stop while repositioning or changing conditions.
5. For every ON observation enforce both finite packet count and independent
   duration limits, with enough margin for settling, acquisition and retrieval.
   Expiration invalidates ON exposure; do not silently relabel it. STOP in cleanup
   and verify stopped even on receiver/file errors. Host failure still needs the
   independent firmware timeout. Restore recorded source and receiver settings.

### B3. Analysis and acceptance

Report paired ON-minus-OFF candidate-window rates and post-warmup fractions,
local versus host duty, crop transfer costs, retained-buffer yield, signed ADC
endpoints and complete known-address/payload/**RF CRC** recovery. Use whole
blocks/pairs as resampling units. Give per-block data, effect sizes and intervals;
exact permutation p-values require exchangeability and do not remove temporal
confounding. Control multiplicity or label secondary comparisons exploratory.

Transport CRC verifies bytes over UART; RF CRC verifies a decoded test frame.
Deduplicate packet sequence numbers across crops when reporting unique recovered
frames, keeping file-level yield separate. A detector-selected buffer is not a
random RF sample. The replay model's selected-file override does not reconstruct
missing online captures or establish recall.

For 64-byte 2 Mbps test frames the known full duration is about 292 µs. A
5,120-sample crop spans 320 µs at 16 MS/s, but only 128/64 µs at 40/80 MS/s.
Even at 16 MS/s a peak-centered crop can truncate a frame. Retention improvements
must be demonstrated on held-out captures with a declared byte budget, not
inferred from three saved files versus one.

**Do not call detections/transmitter-completed packets “recall.”** Those counters
bracket host commands and transfers, not synchronized RF observation windows.
Recall needs an independently known packet schedule, calibrated alignment to
receiver exposure, correct treatment of gaps, eligible packet denominators and
validated decoding. Start with retained-frame yield and source-associated
candidate excess; state that packet recall remains unavailable.

## C. Measured distance and transmit-power trials

### C1. Measure first

Define antenna reference points on both devices and record their separation in
metres, measurement uncertainty, orientation/polarization, height above the
surface, board/mount positions, cable routing, line of sight, nearby reflective
objects and activity. Keep a diagram and private setup photographs. A measured
case-to-case distance is not automatically antenna-to-antenna distance; state
which was measured. Mark positions so a second session can reproduce them.

Choose a fixed, safe geometry before power changes. Prefer starting at −40 dBm
and increasing only as necessary within lawful limits and hardware constraints.
The source supports −40, −20, −16, −12, −8, −4 and 0 dBm; these are nominal
register settings, not calibrated antenna EIRP. Do not assume free-space path
loss indoors or infer receiver sensitivity in dBm from distance alone.

### C2. Staged matrix, not one giant unattended sweep

First establish one nonsaturating reference placement/power, with OFF controls.
Then vary power at that placement while holding gain/manual settings fixed.
After this passes, choose a small set of measured distances and repeat a subset
of useful powers. Use randomized/counterbalanced condition order where physical
movement permits; log order and time regardless. Return to a reference condition
between distance blocks to detect drift. Include OFF observations at every
placement and fresh setup records whenever anything moves.

Predeclare the distance/power grid, repetitions and endpoint from a pilot. Repeat
complete distance blocks rather than treating nearby correlated windows as
independent trials. Keep AGC/manual comparison a separate factor or a planned
factorial design, not an uncontrolled adjustment when a condition looks poor.

After A passes, the existing manual-gain, single-retention receiver-compare runner
can collect one condition with explicit new-image identity:

```sh
python -m nrf_campaigns.nrf_receiver_compare \
  --receiver-mode optimized --label geometry01-power-minus40 \
  --expected-variant esp32-pipeline-adaptive-q16-v3 \
  --rx-port "$RX_PORT" --tx-port "$TX_PORT" \
  --rx-artifact /PRIVATE/PATH/TO/VERIFIED_INSTALLED_APPLICATION.bin \
  --output-directory "$PRIVATE_RUN_ROOT/geometry01-power-minus40" \
  --frequency-mhz 2440 --rx-frequencies 2440 --mode-mbps 2 \
  --power-dbm -40 --length 64 --interval-us 2000 --jitter-us 150 \
  --gain 40 --bandwidth-mhz 12 --rate-hz 16000000 --samples 16380 \
  --ratio-milli 4000 --milliseconds 1000 --pairs 8 --raw-pairs 2 \
  --tx-count 5000 --tx-duration-ms 6000 --seed 52840 \
  --geometry 'REPLACE: measured antenna separation, uncertainty, orientation, height, surroundings'
```

The word `optimized` selects the pipeline API, not a claim that v3 is faster.
Use `--expected-variant esp32-pipeline-optimized-v2` and its own verified artifact
only when intentionally testing that old image. This example is one condition,
not an automatic distance sweep, and eight pairs is not a power calculation.
The broad parameter-screen script changes many factors and is not a substitute
for this matched distance/power design. Never move the setup while TX is active.

The current receiver-compare runner verifies final source STOP, but does **not**
automatically restore all earlier transmitter and receiver settings. Record those
settings before starting and restore them deliberately through the single owning
controller after the run, with readbacks; a tested cleanup extension is needed
before describing this as fully unattended restoration. Record any intentional
final-state change instead of claiming the original state was restored.

**Reject or stop:** unknown/moved geometry, missing OFF controls, transmitter
expiry/state mismatch, gain/readback drift, unexpected saturation, dropped or
corrupt transfers, failed cleanup, or unrecorded settings. Preserve results
rather than relabeling bad conditions. Stop increasing power when clipping or
front-end nonlinearity is suspected; zero ADC endpoints alone is not clearance
to increase further.

Report measured response surfaces and uncertainty for this setup. Claim calibrated
sensitivity only after independent conducted power calibration and a defensible
packet-level denominator. Do not extrapolate one indoor distance to a product's
range, continuous coverage or Quest protocol compatibility.

## Stop and final-state verification

Use the owning runner's explicit STOP/final-status and cleanup log. If it fails,
stop the experiment; do not start another controller while an owner is active.
Once the owning process is closed, this **nontransmitting** check explicitly stops
the identified source and verifies its state:

```sh
python - <<'PY'
import os
from nrf_tx.rf_tx import Transmitter
with Transmitter(os.environ['TX_PORT'], serial_number=os.environ['RF_TX_SERIAL']) as tx:
    tx.stop()
    status = tx.status()
    if status.get('running') is not False:
        raise RuntimeError('Source STOP is not confirmed; stop the experiment')
    print('Source stopped')
PY
```

If software cannot establish STOP, use the pre-agreed physical power-disconnect
plan and inspect the cause before reconnecting. Finite bounds remain necessary;
do not rely on a finalizer alone. Record which receiver image/settings remain
installed and which source settings were restored. No run is successful when
cleanup outcome is uncertain.

## Reproducibility deliverable

Use a private session directory such as:

```text
session-id/
  plan.json                 # hypotheses, factors, randomization, exclusions, endpoints
  setup/geometry.json       # actual measurements, uncertainty, mounts and conditions
  setup/diagram-and-photos/ # private physical records
  identity/                 # source revision, host environment, binary/config hashes
  installation/             # separately approved install/readback/rollback record
  runs/                     # every run, including failures and no-event summaries
  iq/                       # original SigMF metadata and raw data, retained crops
  analysis/                 # frozen script revision, outputs and per-block results
  cleanup.json              # verified source STOP and restored receiver/source settings
  SHA256SUMS
```

Keep full flash/NVS recovery in a separate protected private backup location, not
inside an uploadable experiment bundle. Before publication, create a scrubbed
copy, review metadata and paths, recompute public checksums, preserve measurement
values and link every conclusion to the exact image/settings/data. Never update
historical hashes merely to conceal changed analysis or silently replace failed
observations. State which operations were never run.

## CI and release readiness, separately from the bench work

1. After pushing, verify the intended remote commit and inspect **that commit's**
   host and firmware Actions jobs. A successful local build is not a remote pass.
   Pinned-SDK current ESP32, immutable-base historical retention and nRF builds
   must be distinguished; none accesses a radio.
2. The latest-dependency workflow deliberately goes beyond the production Qt pin.
   Scheduled workflows generally need to be on the repository's default branch;
   a feature-branch push alone does not establish that weekly monitoring is live.
   Check Actions configuration and the actual scheduled/manual run. A failure on
   newer Qt is useful compatibility evidence, not permission to remove the pin.
3. Before a release, freeze a commit, rerun host/firmware checks, build and inspect
   wheel/source artifacts, install the wheel in a fresh environment and test CLIs
   outside the checkout. Preserve tested dependency versions. State the hardware
   gates still open, especially if distributing experimental firmware.
4. Complete [release notes and version steps](releasing.md), review licenses and
   artifact privacy, and obtain a separate decision before creating a public tag
   or release. Pushing these changes does not itself authorize tagging, releasing,
   merging another person's changes, or flashing either device.

A release can accurately describe an experimental, compile-tested feature without
claiming board validation. A hardware-performance claim must wait for the relevant
bench gates and the actual evidence above.
