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
