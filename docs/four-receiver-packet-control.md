# Finite four-receiver packet-recovery control

`python -m nrf_campaigns.four_receiver_packets` uses two to four independently
verified receiver ports. It never flashes firmware. A base project installation
provides its transmitter host dependency.

```sh
python -m nrf_campaigns.four_receiver_packets \
  --port /dev/serial/by-path/VERIFIED_A \
  --port /dev/serial/by-path/VERIFIED_B \
  --port /dev/serial/by-path/VERIFIED_C \
  --port /dev/serial/by-path/VERIFIED_D \
  --tx-serial VERIFIED_TRANSMITTER_SERIAL \
  --output ./private-four-packet-control
```

This validates and prints the plan without opening ports. Add `--run` only after
checking device identities, backups, and the local RF setup. Defaults are eight
full raw snapshots per receiver with the source OFF, then eight snapshots per
receiver during an eight-second finite source run. Receiver capture and UART
transfer are sequential on each board; boards run concurrently. The transmitter
uses 2440 MHz, 2 Mbit/s, -20 dBm, 16-byte known payloads, 1000 us nominal interval,
113 us seeded jitter, and no hopping. The firmware's finite timer and count limit
bound RF independently of host execution. The host always attempts STOP and
restores the original source configuration. Receivers are released/closed; their
volatile frequency/gain settings are not restored.

Full I/Q and device details are private output, not publication material. Raw
transport CRC must pass before decoding. The decoder requires known payload,
address, and over-air CRC checks. OFF matches invalidate source attribution.
Unique packet sequences are deduplicated across receivers and snapshots.

The denominator is **all completed transmissions during the whole finite ON
run**, not just packets predicted to fit acquisition windows. Firmware 0.2.2 is
explicitly required because its sequence is the zero-based attempted-transmission
index. The analyzer refuses errors, saturation, a still-running source, apparent
resets, inconsistent counters, sequences outside the completed range, and any
attempted/completed mismatch. Thus it does not silently guess which in-flight
attempt completed. CPU decoding happens only after the source stops.

The resulting percentage measures this sparse raw-snapshot campaign, including
its transfer gaps. It is not continuous reception, nominal aperture union,
instantaneous RF-window recall, phase-coherent combining, or evidence of real
Quest-controller compatibility. A low recovery fraction is expected when raw
UART transfer dominates. Hardware results must be reported separately from
successful offline tests.

### START timing accounting

The 0.2.2 `START` handler resets attempted/completed/scheduled/missed counters
and calls `status()` synchronously before the main loop returns to `radio_task()`.
However, a running `status()` computes `now_us() - start_us`; its `elapsed_us`
need not be zero. The analyzer requires zero integer transmission counters and
`running=true`, but allows a nonnegative integer START elapsed time strictly
before the final recorded first completion. It additionally requires first
completion <= last completion <= final elapsed time. This uses observed event
ordering, not a guessed 1000 us response ceiling: the initial scheduler deadline
is `start_us`, not `start_us + interval_us`.

### Controlled source power

`--power-dbm` accepts -20 (default), -16, -12, -8, -4, or 0. All other source
parameters remain fixed. Each new campaign records its exact `expected_config`;
both START and final status must match it. Offline `summarize(...,
expected_config=report['expected_config'])` reproduces the selected-power check.
Older default-power results remain supported by omitting that argument.

A same-setup 0 dBm run can serve as a known-signal positive control after a weak
-20 dBm run. These are distinct power conditions, not evidence that software
improved sensitivity or packet recovery. Keep their completed-transmission
counts and per-receiver outcomes separate. Do not silently select only the
better result or claim a controlled sensitivity measurement from nominal source
power alone.

### Optional host staggering

`--stagger-ms 100` delays receiver k by k*100 ms before each concurrent capture
round, in both OFF and ON conditions. Allowed values are integer 0..250; default
0 preserves simultaneous command submission. Four receivers therefore receive
planned host delays of 0, 100, 200, and 300 ms. These are host sleeps, **not RF
synchronization** or calibrated acquisition offsets. Thread scheduling, serial
traffic, and firmware latency still vary. The report records the plan, worker
and capture-call times, and each planned delay.

The plan rejects combinations whose last capture cannot even start inside the
requested source duration under a lower-bound calculation. Every earlier full
round must transfer 40,950 raw bytes per receiver at 1 Mbaud/8N1 (409.5 ms), plus
the largest host delay. Thus the last-start lower bound is
`captures * max_delay_ms + (captures - 1) * 409.5`. Framing and processing overhead
are deliberately excluded: passing this check is **not** a runtime guarantee.
For example 32 rounds, four receivers, and 250 ms staggering cannot fit a 30 s
source run. The limit assumes the CLI's fixed default 1 Mbaud receiver transport.

ON capture rows label whether their host call started or ended after the latest
host-duration deadline. That deadline is bracketed by host times immediately
before START and after its acknowledgement, plus the requested duration. It is
not a measured RF timestamp. The source count limit or an error can stop RF
earlier; a pre-deadline capture call does not prove RF overlap. Late observations
remain visible rather than silently discarded, and the denominator remains all
completed transmissions in the finite source run.

Compare a staggered trial with an equal-power, equal-duration, equal-snapshot-count
unstaggered trial. A single pair is a diagnostic comparison, not a statistical
advantage, sensitivity gain, or continuous-coverage claim.

### Explicit IQ8 transport trial (default remains IQ10)

`--capture-bits 8` requests the existing firmware's CAP16 format: 8 bits per I
and Q component, obtained by discarding the low two bits of each signed 10-bit
ADC component. `--capture-bits 10` remains the default CAP20 path. Both retain
16,380 complex samples at 16 MS/s, approximately 1023.75 us of nominal aperture.
The IQ8 payload is 32,760 bytes versus IQ10's 40,950 bytes. At 1 Mbaud/8N1 the
payload-only wire floors are 327.6 ms and 409.5 ms. The plan's budget calculation
now uses the selected format rather than a fixed IQ10 cost.

Each row records actual component precision, complex sample count, sample rate,
packed payload length, firmware capture duration, and measured host capture-call
time; metadata also retains measured payload-transfer and header-latency times.
Analysis rejects mixed ON/OFF formats or a format different from the requested
one. The source waveform and completed-transmission denominator are unchanged.
Old fixed-IQ10 reports are still checked through their saved capture settings.
IQ8 is an explicit trial option, not a promoted default or a lossless claim.

`python -m nrf_campaigns.iq8_replay PRIVATE_CAMPAIGN_DIRECTORY` independently reruns
the baseline decoder and exact firmware-equivalent IQ8 quantization on retained
IQ10 data without opening hardware or modifying the evidence. It verifies the
input IQ10 grid and compares full payload/address/CRC-accepted observations.
A replay of 576 retained captures (288 ON and 288 OFF) from four 0 dBm trials
and one -20 dBm trial preserved all 187 strong-source accepted observations with
no gained observations or OFF detections. In the weak-source trial, accepted
observations fell from eight to seven; its seven-packet receiver union survived
because another receiver retained the lost observation's packet. This is
quantization replay, not fresh CAP16 hardware validation or universal equivalence.

A bounded physical ABBA IQ10/IQ8 comparison should keep source power, duration,
nominal aperture, snapshot count, and staggering equal. Compare wire/host timing,
transport integrity, and packet outcomes. A fixed-count trial can demonstrate
faster completion but not increased capture throughput. A separate equal-duration
acquisition-budget trial is needed to test whether saved service time yields more
retained unique packets. A single pair is not statistical proof of superiority.

### Equal host acquisition-budget mode

After fixed-count format controls pass, compare IQ10 and IQ8 with, for example,
`--captures 32 --duration-ms 16000 --acquisition-budget-ms 14000 --stagger-ms 100`.
In this optional mode `--captures` is a maximum number of rounds, not a promised
snapshot count. Each OFF and ON condition gets the same finite host call-start
budget. ON's budget starts immediately before sending START (not after its USB
acknowledgement); OFF's starts immediately before its first round. The source
still runs to its independent finite count/duration bound, so the denominator
remains every completed transmission during that entire source run.

The host stops launching new rounds when the budget expires, and each receiver
rechecks after its stagger sleep before calling capture. A last partial round may
therefore contain snapshots from only some receivers. Skipped calls are recorded
separately and are not counted as captures or decoded as empty IQ. An in-flight
capture/readout finishes normally and can extend past the budget. All workers
still join before source/receiver cleanup. Every receiver must retain nonempty
ON and OFF controls for valid analysis.

Each condition records its requested budget, host start/deadline/end times,
rounds started, actual per-receiver snapshot counts, and whether the round cap
was reached. A reached cap can prevent this experiment from measuring the full
available throughput: do not call that run an uncapped time-budget result.
Budget validity is checked separately from the fixed-count lower bound because
unused capped rounds need not fit. No timing label represents a calibrated RF
aperture. Compare actual retained counts, service-time measurements, unique
packets and completed denominators across balanced repeated trials, not just the
best percentage. The IQ10 default and fixed-count behavior remain unchanged.
