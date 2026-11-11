# nRF52840 RF test transmitter, protocol 1

Experimental bare-metal application for designated Makerdiary nRF52840 MDK USB Dongle. See the repository validation summary for historical hardware results. Validate USB recovery before RF use on any new build. Use only where permitted, preferably a shielded/conducted bench; supported frequency is a hardware range, not a legal authorization.

## Build and memory safety

Follow the dependency setup in `../README.md`, then run `make VERSION=0.2.2` with GNU Arm Embedded tools on PATH. Uses Nordic startup/SystemInit and TinyUSB checked out under `../vendor/uf2-bootloader/lib`. No SoftDevice calls or initialization. Freestanding `minilib.c` avoids ARM/Thumb incompatibilities in devkitARM's newlib. Upstream headers emit two unused-parameter warnings.

FLASH origin is **0x23000**, with a link-time end limit **0x40000**. Images contain only application flash. RAM begins at 0x20000000; 8KiB stack is reserved. No NVMC/flash programming code, SoftDevice, MBR, bootloader, bootloader settings or UICR is included. `CONFIG_NFCT_PINS_AS_GPIOS` and `CONFIG_GPIO_AS_PINRESET` must never be defined. Preprocessing the pinned Nordic SystemInit confirms the gated UICR-writing branches are absent. It retains normal volatile peripheral errata workarounds and reads FICR calibration.

Firmware outputs ELF/HEX/BIN; BIN must be placed at exactly 0x23000. The restricted host/flash_uf2.py updater handles deployment. Retained marker `UF2_ENTRY_0x57_v1` denotes the implemented recovery contract, not independent proof of correct code.

## USB and recovery

USB CDC VID/PID 2886:f010, serial uppercase DEVICEID[1] then DEVICEID[0] matching Makerdiary. Open CDC with DTR asserted. Baud rate is ignored. Send ASCII commands terminated by LF; CR is ignored. Maximum line is 255 bytes. Responses are one-line JSON. Send one command and read its complete response before the next; flooding commands can exceed the finite 2048-byte output FIFO.

`HELLO` / `STATUS` returns app `rf-test-tx`, version, protocol 1, updater true, healthy boolean, configuration, counters and microsecond timing.

`BOOTLOADER` disables RADIO, queues `{ "ok": true, "bootloader": true }`, continues USB servicing for 300ms, writes GPREGRET=0x57 then NVIC_SystemReset. Factory Makerdiary source src/main.c declares DFU_MAGIC_UF2_RESET 0x57 and tests/clears it on boot. The installed bootloader is not claimed byte-identical to the published release; see `../docs/recovery-and-update.md`. The same GPREGRET remains set during normal app execution, so unexpected resets also request recovery. Five-second hardware watchdog is fed only from main loop, with WDT/HardFault reset handlers. Watchdog/USB enumeration behavior still requires hardware validation. No persistent configuration is changed.

Boot is RF-off. USB unmount, suspend, DTR loss and VBUS loss stop transmission. Firmware deliberately does not auto-start after reconnect/reset.

## Original protocol (read 0.2.0 revisions below for current limits/timing)

- `STOP`: immediately requests RADIO disable and returns status. Does not erase counters.
- `CONFIG frequency_mhz=2402 mode_mbps=1 power_dbm=-20 payload_len=32 interval_us=10000 jitter_us=0`
- `START count=100 duration_ms=1000`
- `START count=0 duration_ms=10000`: timed run, also capped at 20000 attempts.

CONFIG is atomic, supports any subset, rejects duplicate/unknown keys and changes while running. `length` aliases `payload_len`, but status reports `payload_len`. Frequency 2402..2480 MHz, modes 1/2 Mbps, power -40/-20/-16/-12/-8/-4/0 dBm, payload 8..252. Default -20dBm. Interval 1000..1000000us and at least `(payload_len+10)*8/mode_mbps+300`; jitter 0..interval/2. Jitter is uniform integer ±jitter from deterministic xorshift32, not cryptographic. There is no hopping/burst mode in this initial build.

START requires both count and duration. Count 0..20000, duration 1..60000ms; stops on first bound. A polled, nonblocking state machine prevents overlap, services USB and checks deadlines. Deadline expiration can abort an in-flight packet; only observed hardware EVENTS_END increments `completed`. Radio inactivity timeout after a launched TX is 10ms; timeout increments errors and stops. `healthy` means zero observed radio timeout errors in this run, not independent RF verification.

`scheduled` counts due transmissions accepted by the scheduler; `attempted` counts TASKS_TXEN writes. Initial implementation increments these together; neither is an ideal-slot counter or receiver metric. `completed` counts hardware END events, including one pending when STOP is processed. No ACK reception or remote reception is claimed. `elapsed_us` is local TIMER2 elapsed run time, `last_end_us` last observed completion relative to run start. Timer 1MHz, 32-bit wrapping. No synchronized host/radio clock is assumed. Next due time is based on actual launch, avoiding catch-up bursts but allowing accumulated scheduling drift. Scheduler jitter is software-timed, not precision PPI timing.

## On-air packet

Nordic proprietary GFSK, not BLE or IEEE 802.15.4. Standard 8-bit preamble, 5-byte address (BASE0=0x89abcdef, PREFIX0=0xc3, BALEN=4), 8-bit length field, payload, 2-byte CRC. PCNF1 endian and whitening bits are zero (little-endian bit ordering, whitening disabled). CRC polynomial 0x11021, init 0xffff, address included (CRCCNF=2). 1Mbps/2Mbps Nordic MODE values selected.

RAM byte 0 is payload length. Payload bytes 0..3 ASCII `RFTX`; 4..7 little-endian uint32 sequence starting at zero each START; payload byte i>=8 equals `(i + sequence) & 0xff`. Payload array is static, word-aligned, and unchanged while RADIO is active.

## Staged hardware validation

1. Validate binary addresses and recovery marker, flash only via preserved UF2 bootloader.
2. Confirm CDC serial, HELLO healthy/idle and version, then BOOTLOADER. No START yet.
3. Flash other version and repeat recovery before enabling finite low-power RF tests.
4. Confirm completed counter and STOP/timeout/disconnect behavior, separately measure actual RF signal using receiver instrumentation. USB command success alone does not establish RF correctness.

## CDC correction (0.1.2 / 0.1.3)

Do not deploy 0.1.0/0.1.1: first hardware test established enumeration and software recovery, but found missing/truncated responses. Root cause was legacy TinyUSB's single-packet flush without automatic completion draining. Main loop now repeatedly flushes; command parsing applies response-capacity backpressure. `cdc_device_patched.c` is a local copy of the upstream licensed driver with DTR checked before FIFO removal and each transfer limited to 63 bytes so every transfer is a short USB packet (avoids missing ZLP latency). Vendor source remains untouched. The 0.1.2/0.1.3 pair is for revalidation and alternating-version update checks. No RF validation is implied by these source fixes.

## Phase 2 additions (0.2.0)

Preserves software bootloader recovery and CDC fix. Adds the following CONFIG keys:

- `payload_hex=deadbeef`: 1..244 bytes of hexadecimal (even number of digits), repeated across payload bytes 8..length-1. Pattern length must not exceed length-8. `payload_hex=off` restores deterministic `(index+sequence)&255` tail. `RFTX` and sequence remain mandatory and unchanged. STATUS echoes lowercase payload_hex and payload_pattern_len.
- `hop_list=2402,2440,2480`: up to 16 frequencies, each 2402..2480 MHz; `hop_list=off` disables hopping. `hop_every=1..20000` is number of **scheduled slots** at each list frequency. Missed slots still advance the hop position. STATUS reports base frequency_mhz, currently selected active_frequency_mhz, list and dwell. Frequency changes only while RADIO is Disabled before TXEN.
- `burst_count=0..20000`: zero disables bursts. Otherwise insert `burst_gap_us=0..1000000` extra microseconds after each group of this many **scheduled slots**. The extra gap is in addition to normal jittered interval. Missed slots count toward burst grouping.
- `seed=1..2000000000`: deterministic xorshift32 seed, reset at each START. One PRNG draw per scheduled slot including missed ones, even with zero jitter. Identical settings produce the same ideal schedule.

Example: `CONFIG length=32 interval_us=5000 jitter_us=500 seed=42 payload_hex=deadbeef hop_list=2402,2440,2480 hop_every=10 burst_count=5 burst_gap_us=20000`

### Revised timing semantics

The due schedule now advances from the previous ideal due time, rather than actual launch. One due slot is processed per main-loop iteration. If RADIO is not available or the following slot is already due, the slot is marked missed. Stale slots are skipped rather than transmitting catch-up bursts. A launch can still be delayed within its slot; software polling is not hardware-precise. The scheduler stops when duration or actual attempt cap is reached; it does not account slots beyond that stop or retrospectively enumerate an unprocessed backlog after the deadline.

- scheduled: number of processed due slots.
- attempted: actual TASKS_TXEN writes.
- missed_slots: processed due slots not launched. During/after ordinary operation, scheduled = attempted + missed_slots.
- late_slots: launches whose timestamp is later than the ideal due time, including even one microsecond.
- launch_lateness_min_us / max_us / total_us: actual TIMER2 timestamp immediately before TASKS_TXEN minus ideal due time. Small register-write/instruction delay follows the timestamp. This is not the first over-air bit timestamp.
- completion_latency_min_us / max_us / total_us: END-event **polling observation time** minus TXEN timestamp, not a hardware-captured airtime measurement.
- first_end_us / last_end_us: completion observation timestamps relative to START.
- timing_saturated: a sum overflowed uint32 and was clamped to 4294967295. Means exact totals are unavailable; minima/maxima remain valid.

Counters reset per START; STOP now preserves elapsed time when already stopped. Command maximum is 1023 bytes, responses bounded by 1900 bytes, RX response backpressure updated accordingly. Host must read a complete line per command. Long status formatting/USB work may increase missed or late slots; the telemetry explicitly exposes that limitation.

### Offline tests

`cc -std=c11 -Wall -Wextra -Werror schedule.c test_schedule.c -o build/test_schedule && build/test_schedule` covers due/missed/late accounting, 32-bit clock rollover, burst gaps, seeded 20,000-slot jitter and sum saturation. `python3 test_offline.py` extracts the actual firmware parser/status functions and tests atomic rejection, aliases, payload patterns, hop list limits, seed ranges and duplicate keys using host sanitizers (leak checking disabled because this runner uses ptrace). Actual minilib output was separately compared with libc using a maximal 244-byte payload and 16-hop status. These are source-level tests, not hardware RF validation.

## Read-only DEVICE diagnostics (0.2.1)

`DEVICE` rejects while running, busy, or RADIO STATE is not Disabled. It performs bounded synchronous flash reads only while idle. USB interrupts remain enabled; CRC calculation can briefly delay other command processing. No flash/peripheral writes occur in the diagnostic code.

Returns raw unsigned FICR INFO values as part, variant, package, ram_kib, flash_kib; uppercase DEVICEID[1]:DEVICEID[0] serial without a separator; actual raw RADIO MODE, FREQUENCY and TXPOWER as radio_mode_reg, radio_frequency_reg, radio_txpower_reg. Raw frequency is offset from 2400MHz; raw TXPOWER should be interpreted per Nordic register encoding, not as an unsigned dBm value.

All checksums are CRC-32/ISO-HDLC (reflected polynomial EDB88320, initial/final XOR FFFFFFFF), returned as eight uppercase hexadecimal characters. Runtime `crc32_selftest` and the offline test both yield CBF43926 for ASCII `123456789`. Empty input yields 00000000. Regions are exact half-open byte ranges, including erased padding:

- mbr_crc32: [0x00000000, 0x00001000)
- softdevice_crc32: [0x00001000, 0x00023000)
- bootloader_code_crc32: [0x000F4000, 0x000FD800)
- configuration_crc32: [0x000FD800, 0x000FE000)
- settings_crc32: [0x000FF000, 0x00100000)

Full uicr_crc32 is null because the requested [0x10001000,0x10001400) range includes reserved addresses that are not read. `uicr_named_crc32` is instead computed on 38 named words, each serialized as four little-endian bytes in this exact order: CUSTOMER[0..31] (0x10001080..0x100010FC), PSELRESET[0..1] (0x10001200/204), APPROTECT (208), NFCPINS (20C), DEBUGCTRL (210), REGOUT0 (0x10001304). This subset is explicitly not a checksum of a contiguous UICR page and must only be compared with the identical subset. Nordic nrfx's nrf52840.h documents these named readable words. No reserved NRFFW/NRFHW or holes are read.

Region checksums identify byte-level differences but are not cryptographic authentication and do not alone establish that an image matches a trusted release. Host comparisons must use identical address windows/padding and independently trusted release evidence. Firmware and CRC functions use `-fno-delete-null-pointer-checks` so the deliberate read of embedded flash address zero is retained.

## STOP completion race fix (0.2.2)

Earlier versions sampled END before requesting disable and could miss an END arriving in between. `stop_control.c` now clears shortcuts and requests DISABLE, observes STATE=Disabled, then samples END and accounts it exactly once only if the transfer was still tracked busy. Once Disabled is observed, that TX cannot newly complete. Already-counted ENDs do not increment again. The main-loop completion path is unchanged.

The disable wait is bounded by 1000 microseconds or 4096 polls, whichever arrives first; the poll bound also covers a stalled TIMER2. This is a short synchronous safety operation, not an unbounded USB-blocking wait. On timeout the RADIO peripheral is powered off immediately, errors increments, and the app resets into the preserved bootloader without a success acknowledgement. Because reset loses RAM telemetry, a timeout is primarily observed as recovery enumeration, not a persisted errors count. No transmission is claimed complete if Disabled was not established.

`test_stop_control.c` exercises END before stop, END arriving during disable, canceled-without-END, already-accounted transfer, disable timeout, stalled timer and clock wrap using the actual shared control function. An additional historical generated host harness (not included in this public source tree) exercised the extracted actual application stop function: idle STOP before START retains elapsed_us=0, completed increments once, and repeated STOP preserves counters/elapsed. No hardware was used for these tests. Previous versioned firmware binaries remain unchanged.
