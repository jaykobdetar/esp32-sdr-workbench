# Two ESP32 receivers: measured coverage, 12 November 2026

## Result

Both receivers are operational. RF-anchored timing and deliberate phase/yield
scheduling substantially improve combined coverage. **Continuous 100% coverage
was not achieved.** More than 100% summed receiver-time is not more than 100%
unique coverage.

| Measured condition | Combined nominal RF-window union |
|---|---:|
| Independent/free-running, three 1-second trials | 83.25–88.50% |
| Best tuned paired acquisition, six 5-second trials | 99.927–99.995%, mean 99.971% |
| Staggered readout, predefined 30-second window | 96.246% |
| Independent repeat through the packaged command, 30-second window | 96.260% |

The tuned five-second trials summed to approximately **109.2% receiver-time**.
They still contained gaps, with the largest per trial between 64.8 and 226.3 µs.
The six trials together had about 8.64 ms of uncovered nominal RF time over 30
seconds of requested acquisition. This is not a single uninterrupted 30-second
recording: transfers and clock-anchor checks occurred between these trials.

The staggered trials **include readout and restart gaps**. Their largest gaps
were 1.783 ms and 0.962 ms respectively. Each board requested 30 seconds of
acquisition; these requests took about 31.3 seconds to complete with overhead.
Full first-trigger-to-last-sample episode coverage was 96.146% and 96.152%.
The headline 30-second window was fixed from the shared start grid, not chosen
after inspecting the best portion of the recording.

Detector decisions are a separate measure. Excluding each finite run's first
16 warmup captures and its unprocessed 60-sample block tail, combined nominal
decision-window coverage was 99.321–99.395% in the tuned five-second trials and
95.627% / 95.641% in the two 30-second staggered observations. Detection,
retention, decoded-packet recall and calibrated sensitivity were not established
by any of these percentages.

## How the timing was measured

USB request/reply brackets were roughly sub-millisecond to millisecond scale,
which is insufficient to certify the small gaps. Instead, the two receivers
captured identical known nRF52840 packets. Each accepted anchor required the
same sequence within a transmitter start session, full expected payload,
expected address and valid over-air CRC on both receivers. UART CRC separately
validated data transport.

An affine fit maps one device's trigger timestamps to the other's timeline.
Relative drift was about **23.4 ppm**. The tuned campaign used 10 common-packet
anchors over 58.26 seconds; maximum fit residual was 0.735 µs and maximum
alternating held-out-anchor residual was 1.050 µs. The two staggered trials had
maximum fit residuals of 3.007 and 2.590 µs, with held-out maxima of 2.486 and
2.154 µs. These are empirical consistency checks, not certified timing bounds.
The final analyzer uses this affine fit; progress prints use a simpler offset
approximation and are not the final results.

Every successful pipeline capture supplied a CRC-checked trigger timestamp.
The union counts overlap once and includes actual late triggers and skipped
schedule slots. Aperture length is still **nominal N/fs**, not an externally
calibrated RF-arrival interval. Constant trigger/sample delays, sample-rate
calibration, analog group delay, rare unobserved events and long-term clock
stability remain limitations.

## Conditions and implementation

- Two original ESP32-D0WD-V3 revision 3.1 devices, each with 4 MB flash.
- Experimental image based on main commit `2c06109` (v8).
- Exact application SHA-256:
  `6de4ca33808539a31fc8af75b84bffa2a9604634977e5adb94ddce2a8d7dd523`.
- Variant `esp32-dual-timing-experimental-v1`; not an upstream release.
- 2440 MHz, nominal 16 MS/s, 16,380 samples, 12 MHz filter setting,
  manual gain 60, legacy background policy, optimized energy/copy selectors.
- Tuned interval 1,875 µs. Initial relative phase centered predicted drift over
  each five-second run; mandatory every-32-capture yields were phase selected,
  **not removed or shortened**. Aperture ownership and memory guards remain.
- Headline trials have retention disabled. A separate one-second retained-I/Q
  trial reached only about 92.05% nominal union. Do not apply no-retention timing
  results to full I/Q recording or assume all sampled data reaches the host.
- RF anchors: known 16-byte, 2 Mbps source packets, 2440 MHz, configured 0 dBm,
  1,000 µs interval and 113 µs jitter. This is not calibrated received power.
  The source was stopped during pipeline timing.

The packaged staggered repeat completed 15,999 and 16,000 successful captures
across six and seven chunks respectively. No reported acquisition/packing
error or trace CRC failure occurred in the completed timing trials. Cleared
heap readings were stable within the principal campaigns; this is bounded
functional validation, not a lifetime soak or a proof against all faults.

## Preservation and final state

Each board's full 4 MB flash was privately backed up and its read digest checked
before writing. Faster backup transfer failed without saving a backup; the
reliable 115200-baud retry succeeded. The original board received only an
application update in its existing factory slot.

The second board contained factory ESP-AT firmware with a different OTA/NVS
layout. Its verified active OTA0 application was replaced without changing
partition definitions. Its older partition table lacked a checksum required
by the newer SDK; startup correctly idled before NVS initialization. Adding
only the missing MD5 record resolved that incompatibility. All other bytes in
the first 1 MB, including bootloader, partition definitions and NVS, were
verified unchanged before boot. No full-chip erase or copying of calibration
between boards occurred.

SDK-managed calibration refreshes remain possible. Stored calibration
fingerprints were stable within the measured campaigns; original backups are
retained, and calibration was not manually rolled back. This is not a claim of
byte-for-byte NVS preservation across every firmware startup.

Both boards were left on the tested experimental application, buffers cleared,
hardware AGC selected and ready for receive operations. Final checks passed six
raw I/Q transport CRCs and two finite pipelines. The nRF source was restored to
its prior settings and verified healthy and stopped. No desktop windows were
opened/closed, and nothing was pushed or published.

## Reproduction and remaining work

Use [the experimental command guide](dual-receiver-timing.md). The portable
RF-clock/staggered command was itself run on both boards, not merely dry-run.
Host suite: **621 tests plus 5 subtests passed**. Clean experimental firmware
build, UBSan diagnostic/parser tests, Ruff and whitespace checks passed.

The next engineering limit is **readout/restart dead time**, followed by residual
scheduler jitter. Shortening or overlapping trace transfer and maintaining a
continuous acquisition schedule would be needed before seeking a genuine
continuous-coverage claim. A shared clock/trigger could improve determinism but
would not by itself eliminate data-transfer pauses. No 100% packet-recall,
continuous-I/Q or calibrated sensitivity claim is warranted.
