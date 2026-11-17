# Acquisition-free serial integrity control

`python -m nrf_campaigns.serial_integrity_control` repeatedly requests the receiver's
static `CAPS` response, without configuring RF or requesting captures. It is a
control for transport/parser integrity, not an RF benchmark, continuous-coverage
measurement, packet-recovery result, or proof that a cable or board is defective.

The command is a dry run by default. Identify each receiver by verified USB
location and chip identity before selecting its port; these bridges can share
USB serial labels. Close other software using the ports.

```sh
python -m nrf_campaigns.serial_integrity_control \
  --port /dev/serial/by-path/VERIFIED_RECEIVER_C \
  --port /dev/serial/by-path/VERIFIED_CONTROL_A \
  --tx-serial VERIFIED_TRANSMITTER_SERIAL \
  --output ./private-serial-control \
  --seconds 60 --target-bytes-per-second 25600
```

Add `--run` to operate the devices. One to four distinct ports are tested
sequentially. Each trial is bounded to 1–120 seconds plus bounded setup and
failure diagnosis. The response-byte-rate target is 1–50000 bytes/s (default
25600); **actual validated bytes divided by actual elapsed time** is reported.
Request/reply pacing may not attain the target. A target numerically equal to
DSTREAM's output rate does not reproduce its packetization, CPU load, RF SRAM
ownership, or UART scheduling. UART remains at the existing 1 Mbaud setting.
The transmitter must acknowledge STOP and report stopped before testing; STOP
and status are attempted again in final cleanup. No transmission is requested.

## Validation and failure handling

The exact learned `CAPS` reply is crosschecked against connected capabilities.
Every subsequent reply must match byte for byte, including line ending. No
repair, discarded bad frame, relaxed CRC, or successful resynchronization can
turn a failed trial into a passing one. A failed outcome produces a nonzero
command exit status.

On failure the same receiver serial descriptor stays open. Up to 4096 failed
reply bytes and a short bounded tail are retained privately. A fresh protocol
object then attempts nonce synchronization **on that same descriptor**, followed
by `CLOCK?` and `CALHASH?`. DTR/RTS are not changed and the port is not reopened
between failure and diagnosis. Device clock regression or a large disagreement
with host elapsed time flags a possible reset/clock discontinuity; consistency
does not prove that a reset was impossible. The descriptor closes only after
this diagnosis completes. Initial opening of a serial connection can itself
change board state, so this control cannot establish calibration invariance
across independent sessions.

Output is private: it includes port identities, firmware/version information,
calibration fingerprints and raw bytes. Do not publish the directory unchanged.
A saved diagnostic explains a rejection; it is not accepted RF evidence.

## Next-day isolation

Run the same bounded control on the suspect receiver and a known comparison
receiver, preserving both failed and successful attempts. After closing every
serial session, swap **one physical factor at a time**, such as cable or host
USB port, with the owner present. Re-identify the devices after each swap and
repeat unchanged settings. Compare failures per elapsed time and delivered byte
count, not just whether one short run passed. Do not silently retest until a
failure disappears or attribute it to hardware without the comparison.

A similar failure without acquisition narrows the investigation beyond the RF
capture loop, but shared UART firmware, bridge, host driver, electrical path and
host reader remain possible causes. A passing control does not clear those
components under all acquisition workloads.
