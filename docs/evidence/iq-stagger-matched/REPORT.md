# Matched IQ precision and host-stagger controls

Eight completed, counterbalanced physical runs used **16 s source duration,
10 s host acquisition budget, 0 dBm, 16,380 complex samples at 16 MS/s, and a
32-round cap** throughout. The comparison varied only IQ10/IQ8 and 100/5 ms
host staggering. The order was 10/100, 10/5, 8/5, 8/100, then the reverse.
Each condition therefore has two runs; this is a small controlled diagnostic,
not statistical superiority or a calibrated sensitivity/coverage claim.

This report was produced from completed JSON only. The projection rechecks
cached accepted-packet accounting, per-condition counts, calibration, source
STOP and configuration restoration. It does not reload I/Q or decode RF.
[Numeric evidence and input hashes](summary.json) contain no device identifiers,
private paths, calibration fingerprints or RF samples. The reusable projector
is `scripts/project_packet_controls.py`.

## Matched results

Counts and source denominators below are sums across the two runs per condition.
Unique packets are deduplicated within each run, then summed: sequence counters
reset between runs. Capture time is the median of the two ON-run medians.

| IQ bits/component | Stagger step | ON / OFF snapshots | Median capture call | Unique / completed source transmissions | Descriptive recovery |
|---|---:|---:|---:|---:|---:|
| 10 | 100 ms | 112 / 112 | 416.976 ms | 82 / 31,866 | 0.25733% |
| 10 | 5 ms | 184 / 184 | 416.881 ms | 124 / 31,874 | 0.38903% |
| 8 | 100 ms | 126 / 128 | 334.363 ms | 88 / 31,860 | 0.27621% |
| 8 | 5 ms | 220 / 224 | 334.403 ms | 161 / 31,865 | 0.50526% |

All eight runs passed. No condition reached its round cap. Every OFF control had
zero accepted packets; duplicate accepted observations were zero in every run,
including 5 ms staggering. No capture call started or ended beyond the latest
host source-duration deadline. Calibration fingerprints were unchanged, source
STOP was confirmed, and source configuration was restored in every run.

The shorter stagger retained 64.3% more ON snapshots with IQ10 (184 versus 112)
and 74.6% more with IQ8 (220 versus 126) over the same acquisition budgets.
At 5 ms, IQ8 retained 19.6% more ON snapshots than IQ10 (220 versus 184). These
are directly observed retained-snapshot differences, not a theoretical RF duty
factor. Median capture service time was essentially unchanged by stagger within
each format, while IQ8 service time was about 19.8% shorter than IQ10.

The unique packet totals also increased in these controls, but two runs per
condition do not establish a general packet-recovery advantage or optimum
stagger. Zero observed duplicates does not prove the RF apertures never overlap.
Host sleeps are not synchronized RF timing. The percentages retain every
completed transmission during the entire 16 s source run, including time outside
the 10 s acquisition budget; they are not capture-window recall.

## Per-run accounting

Receiver lists use stable anonymous order A, B, C, D.

| Run | IQ / stagger | ON snapshots A–D | OFF snapshots A–D | Unique packets / completed | Per-receiver unique packets A–D |
|---|---|---|---|---|---|
| 1 | 10 / 100 ms | 14,14,14,14 | 14,14,14,14 | 43 / 15,935 | 12,11,8,12 |
| 2 | 10 / 5 ms | 23,23,23,23 | 23,23,23,23 | 63 / 15,942 | 15,17,14,17 |
| 3 | 8 / 5 ms | 27,27,27,27 | 28,28,28,28 | 79 / 15,935 | 17,23,16,23 |
| 4 | 8 / 100 ms | 16,16,16,15 | 16,16,16,16 | 44 / 15,934 | 10,13,8,13 |
| 5 | 8 / 100 ms | 16,16,16,15 | 16,16,16,16 | 44 / 15,926 | 10,13,8,13 |
| 6 | 8 / 5 ms | 28,28,28,28 | 28,28,28,28 | 82 / 15,930 | 18,24,16,24 |
| 7 | 10 / 5 ms | 23,23,23,23 | 23,23,23,23 | 61 / 15,932 | 19,18,9,15 |
| 8 | 10 / 100 ms | 14,14,14,14 | 14,14,14,14 | 39 / 15,931 | 11,13,6,9 |

Runs 4 and 5 each skipped one ON call for receiver D after its host budget
expired; successful siblings were retained. All other skipped-call counts were
zero. Differing ON/OFF totals remain explicit rather than silently balanced.

## Separate experiments stay separate

The earlier [14 s acquisition / 16 s source format controls](../iq-format-initial/summary.json)
use a different exposure fraction and must not be pooled into these percentages.
The [failed 12 s source control](../iq-format-initial/failed-12s-control.md) remains
failed and excluded: its attempted/completed mismatch was not waived. This new
16 s preset passed all eight checks, but the duration does not guarantee that
future runs cannot encounter a stop-boundary mismatch.

Projection groups distinguish precision, stagger, source power, source duration,
acquisition budget and both condition round caps. Changing these creates a
separate group, not an invisible mixture. The default capture format remains
IQ10; these results do not silently promote an experimental setting.
