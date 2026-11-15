# Opt-in cyclic GC deferral experiment

`multi_stream_campaign --defer-cyclic-gc` is default-off and restricted to at
most three runs of 1–120 seconds without a phase sweep. It is a host scheduling
experiment, not a firmware fix or a guarantee of continuous RF coverage.

The coordinator performs full collection before probing clocks and scheduling
stream deadlines, then disables cyclic GC around the entire coordinated run.
It restores the exact previous enabled/disabled state after all submitted
workers finish, including failure cancellation and same-descriptor diagnostics.
A partial worker-submission failure also cancels and joins submitted workers.
Anchors and subsequent analysis retain the original GC policy. No individual
receiver worker changes global GC state. Concurrent policy scopes are refused.
Do not combine this option with other code independently changing GC settings.

Private reports include policy timing, original/restored state, collection count,
peak RSS, exception status, and helper source hash. RSS is a process peak, not
current memory consumption. Deferred cyclic collection can increase memory
usage; reference counting remains active, and retained report records stay
allocated regardless. Bounds limit exposure but do not guarantee sufficient
memory. Keep default behavior unless intentionally comparing this experiment;
passing trials do not establish GC as the sole cause of serial corruption.
