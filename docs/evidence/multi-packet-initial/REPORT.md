# Initial two-receiver packet-only controls

Completed receipts and raw ASCII wire were independently revalidated offline.
This is bounded known-source packet metadata delivery, not continuous capture,
synchronized RF sampling or general/Quest protocol support. Source evidence is
aggregate completed counters, not an event-level trace.

The first two-receiver source-OFF qualification completed 32 requested 20 ms
slots on each receiver, with zero packets, skipped slots and output drops.

The first concurrent ON/OFF trial requested 128 slots per receiver at 20 ms with
zero planned host delay and a shared finite 5-second source run at 0 dBm:

- Union: 95 / 4,982 completed transmissions = 1.9069%.
- Receiver A: 51 packets; receiver B: 87 packets.
- 138 observations include 43 cross-receiver duplicates. Neither receiver had
  within-board duplicate observations.
- Both completed all 128 slots, with zero OFF packets, skipped slots and output
  drops. Incomplete candidates were 10/ 25; these are not unique RF packet losses.
- Mean ON decode duration was 10.930/ 10.973 ms; full host collection including END
  delivery was 2.835/ 2.840 s. All receivers finished before the conservative source
  deadline. Calibration and final cleanup passed.

Removing raw-IQ UART output permits substantially more acquisition opportunities,
but these unmatched initial controls do not establish a quantitative advantage
against prior raw-IQ trials. Receiver count, source duration and exposure differ.
The two-receiver union also overlaps substantially: more receivers are not
independent packets by default. A host start delay is not RF synchronization.

The projection groups separately by receiver count, slot count/period, output
cap, host delay, source duration, OFF-only mode and complete source configuration.
Any failed campaign is retained with no accepted recall; surviving sibling
observations cannot salvage it. No failed multi-receiver receipt was included in
these three completed controls. Individual trials are descriptive only.

## Host-delay control

A separate completed trial kept 128 slots/ 20 ms, 5-second source and 0 dBm, but
requested a 5 ms host start delay for B (A delay 0). Its exact packet union was
177 / 4,980 = 3.5542%, with A 76 and B 101 observations, zero duplicates, zero OFF
packets, skips and output drops. Incomplete candidates were 31/ 60. Both receivers
finished full END delivery before the conservative source deadline; calibration
and cleanup passed. Full host collection took about 2.836/ 2.837 seconds.

This single paired comparison is descriptive, not a causal or statistical
estimate of delay benefit. Planned host delay does not establish actual RF
phase separation or stable device-clock alignment. Conditions remain separate
in the projection rather than pooled. Repeat and counterbalance before making
comparative performance claims.

## Four-receiver expansion

Five additional completed controls were independently revalidated from their
retained wire and receipts. Source-OFF qualification requested 32 slots on each
of four receivers; all completed, with zero packets, skipped slots or drops.
Four subsequent ON/OFF campaigns used 128 slots/ 20 ms per receiver, a shared
5-second 0 dBm source, and the same strict source/calibration/cleanup gates:

| Condition | Per-board unique packets A/B/C/D | Union / completed source | Recovery | Duplicate observations |
|---|---|---|---|---|
| No planned delay | 68 / 109 / 76 / 80 | 134 / 4,979 | 2.6913% | 199 |
| Host delay 5 ms, repeat 1 | 81 / 106 / 79 / 94 | 360 / 4,977 | 7.2333% | 0 |
| Host delay 5 ms, repeat 2 | 77 / 108 / 74 / 86 | 345 / 4,976 | 6.9333% | 0 |
| Host delay 5 ms, repeat 3 | 69 / 104 / 80 / 84 | 337 / 4,983 | 6.7630% | 0 |

The delay plan is 0/ 5/ 10/ 15 ms at host command start, not synchronized RF aperture
phases. The three predeclared delayed repeats sum to 1,042 / 14,936 = 6.9764%.
This is a descriptive pooled ratio of run-local unions, never a cross-reset
sequence deduplication. Each repeat and its denominator remains separately
visible. These three same-condition repeats share a group; no-delay, two-board,
and OFF-only qualification groups remain separate.

Every four-board ON/OFF campaign completed all 128 slots per receiver and had
zero OFF packets, skips and output-cap drops. All full END receipts preceded the
conservative source deadline; calibration and cleanup passed. The no-delay
trial had 333 observations, of which 199 were duplicates across receivers; no
board had internal duplicates. The delayed repeats had no delivered duplicates.
Incomplete decoder candidates remain explicit in the numeric summary and do
not measure unique lost RF packets. No failed four-board trials were reported
for this declared batch; the earlier failed single-board 10 ms source-denominator
control remains in its separate evidence set, not silently omitted or salvaged.

The delayed-repeat mean ON decode time across individual receivers ranged
10.927–10.986 ms per 1.02375 ms aperture. Full host collection including END
readout ranged 2.834–2.838 seconds per receiver. A 20 ms period offers nominal
5.12% aperture time per board; summing four such fractions is not a measured
union coverage guarantee. Observed distinct packet delivery does not establish
continuous capture, stable RF phase spacing, or general/Quest compatibility.
The repeated bounded result is useful evidence of this known-source metadata
path; it is not a direct efficacy comparison with the differently configured
raw-IQ baseline or a randomized estimate of host-delay benefit.
