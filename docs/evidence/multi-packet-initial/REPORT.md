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
  drops. Incomplete candidates were 10/25; these are not unique RF packet losses.
- Mean ON decode duration was 10.930/10.973 ms; full host collection including END
  delivery was 2.835/2.840 s. All receivers finished before the conservative source
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

A separate completed trial kept 128 slots/20 ms, 5-second source and 0 dBm, but
requested a 5 ms host start delay for B (A delay 0). Its exact packet union was
177 / 4,980 = 3.5542%, with A 76 and B 101 observations, zero duplicates, zero OFF
packets, skips and output drops. Incomplete candidates were 31/60. Both receivers
finished full END delivery before the conservative source deadline; calibration
and cleanup passed. Full host collection took about 2.836/2.837 seconds.

This single paired comparison is descriptive, not a causal or statistical
estimate of delay benefit. Planned host delay does not establish actual RF
phase separation or stable device-clock alignment. Conditions remain separate
in the projection rather than pooled. Repeat and counterbalance before making
comparative performance claims.
