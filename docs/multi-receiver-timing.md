# Two-to-four receiver timing campaign

`python -m nrf_campaigns.multi_stream_campaign` extends the existing bounded,
no-retention DSTREAM timing experiment. It does not flash firmware or turn
telemetry into continuous retained I/Q. Use only individually verified receivers
with DSTREAM, TIMEDCAP and the selected scheduler capability. Preserve each
board's original flash and calibration separately before installation.

Supply two to four distinct `--port` paths, one `--tx-serial`, a new private
`--output` directory, and optionally `--phases 34,34,34,34`. Defaults select phase
zero for each receiver. Without `--run`, only a plan is printed. Trials are
bounded to 1–600 seconds, with at most 20 trials. The nRF transmits finite
2-second/4,000-count bursts at 2440 MHz and 0 dBm for clock anchoring; it is
stopped during each timing trial and in cleanup. Every anchor phase is limited
to 60 attempts (40 is no longer the default). Stop on inadequate shared packets
rather than manufacturing synchronization from USB arrival times.

Receiver zero is the reference. Each other receiver gets its own affine clock
fit from common full-payload, address-verified, over-air-CRC-verified packets
with receiver zero. Receivers need not all observe a single common packet.
Each pair must independently pass the existing dual analyzer's bracketing,
independent capture-group count, residual, drift, and whole-group held-out
screens. One bad/missing stream or pair invalidates the combined result.

Scheduled phases are equally spaced in reference time, then mapped into each
local clock. Period compensation is independent per device. Results preserve
the requested reference-time observation boundaries, including startup and end
gaps. The union counts overlap only once. A separate completion-inclusive union
ends at the latest mapped device terminal timestamp; it does not include host
pre-arm, RF calibration, or final UART delivery. Full-burst opportunity erodes
individual windows before union: adjacent captures cannot reconstruct a packet.

Sensitivity reports enumerate constant relative-offset corners for all
non-reference receivers at ±1, ±5 and ±20 microseconds and erode every nominal
window by the assumed endpoint error. These are scenarios, not measured error
bounds, exhaustive drift analysis, confidence intervals or a guarantee. Clock
fits cannot exclude nonlinear drift during a trial. All union values describe
nominal trigger-plus-sample-duration windows, not calibrated RF apertures.

This campaign does **not** measure packet recall. RF anchors are selected shared
observations and cannot provide a recall denominator. A separate known-source
experiment must count completed transmissions and deduplicate CRC-verified
packet sequences across all receivers. No Quest protocol compatibility, 100%
packet recovery, or continuous retained I/Q follows from this timing report.
Private output contains raw RF and device details; review and sanitize before
publication. No hardware experiment is implied by the synthetic unit tests.

## Final campaign acceptance

Legacy calibration reanalyzes earlier runs when new anchor batches arrive. The
campaign acceptance gate checks **every intended measurement trial**, not only
the latest result, after each reanalysis and before final validation. If a later
anchor epoch invalidates an earlier intended trial, the campaign fails even if
its newest trial remains verified. Run indices are recorded explicitly.
Exploratory phase-sweep rows are labeled separately and are not required to pass
this measurement-trial gate; the sweep still requires a verified phase before
measurement trials begin. This does not retrospectively change saved reports.
