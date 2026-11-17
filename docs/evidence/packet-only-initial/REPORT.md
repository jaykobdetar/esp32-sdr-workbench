# Initial single-board packet-only controls

These are finite known-source controls, not continuous reception or Quest
compatibility. The source denominator is aggregate completed transmissions;
there is no event-level source trace. Full wire transcripts were revalidated
against the strict parser before producing the allowlisted numeric summary.

## Candidate preparation and recovery

Only receiver A was changed for these controls. The initial candidate's exact
128-byte capability reply was withheld until a later nonce query released it;
that check was not accepted as normal delivery. The qualified `v1finish`
candidate instead reuses the preserved paced INFO/END send path without changing
CRC-framed wire bytes. The first installation of that fix failed during serial
writing; automatic rollback verified the exact whole pre-write image. One retry
from a fresh verified recovery checkpoint succeeded, with all nonwritten bytes
verified unchanged before application boot. Earlier images, failed checks and
rollback receipts remain private and preserved. This is not proof that the
underlying serial fault is resolved or that runtime calibration survives resets.

## Controlled packet outcomes

| Control | Requested / completed ON slots | Skips | Valid recall |
|---|---:|---:|---:|
| Source-OFF smoke, 10 ms | 32 / 16 OFF only | 16 | Not a recall trial; zero OFF packets |
| 10 ms, 3 s source | 128 / 64 | 64 | Rejected; no accepted recall |
| 20 ms, 4 s source, repeat 1 | 128 / 128 | 0 | 73 / 3,988 = 1.8305% |
| 20 ms, 4 s source, repeat 2 | 128 / 128 | 0 | 85 / 3,991 = 2.1298% |
| 20 ms, 4 s source, repeat 3 | 128 / 128 | 0 | 75 / 3,992 = 1.8788% |

All three accepted trials had zero OFF packets, output drops, duplicate delivered
sequences, and skipped slots. Incomplete decoder candidates were 31, 21 and 43;
these are not unique lost-packet counts. The descriptive pooled ratio is
233 / 11,971 = 1.9464%, summing independent run-local numerators and denominators,
not deduplicating sequences across source resets. All complete END receipts
preceded the conservative source deadline; calibration and cleanup checks passed.

The rejected 10 ms trial retained 30 checked ON observations, but the source
reported 2,990 attempted versus 2,989 completed. No recall is assigned or salvaged.
A source-boundary in-flight attempt is possible, not established over-air loss.
It remains separate from accepted trials and is retained in the summary.

Actual candidate mean ON decode time was 10.932–10.957 ms per 1.02375 ms sample
window, roughly 10.7 times real time. Earlier benchmark timings used different
capture sizes and algorithms and are not substituted for this measurement. Ten-millisecond admission therefore
skipped half the slots; 20 ms had no skips in these short repeats. Whole ON
collection including paced END delivery took about 2.834–2.836 seconds for 128
windows; firmware session_us ends before that terminal output.

The earlier four-board raw-IQ8 161 / 31,865 result has different receiver count,
source duration, exposure and transport. These results demonstrate workable
bounded packet metadata delivery, not a controlled recall-gain estimate against
that baseline. Twenty-millisecond slots have nominal aperture fraction 5.12%
per receiver even with no skips, before session-edge/slack costs. No continuous
coverage claim follows.
