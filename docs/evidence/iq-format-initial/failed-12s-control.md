# Failed 12-second source control: retained data, no accepted recall

The initial matched-stagger control used IQ10, 100 ms host staggering, a 10 s
acquisition budget and a 12 s source duration. It retained 56 OFF and 56 ON raw
snapshots: 14 per receiver in each condition, all transport-CRC valid. Neither
condition reached its 32-round cap. Calibration fingerprints were unchanged,
the source was stopped, and its original configuration was restored.

The source reported **11,979 attempted and 11,978 completed transmissions**,
12,000 scheduled slots, 21 missed slots, and zero device errors. Its final state
was healthy and not running. The strict denominator check rejected this mismatch;
the run remains failed, and no recall percentage is accepted. Retaining and
decoding raw data does not retroactively pass the campaign.

The 0.2.2 source checks its duration deadline in `radio_task()` and calls
`radio_stop()`. The stop controller requests radio disable, waits for Disabled,
and accounts a completion only if a tracked transmission has a pending END
event. Disabling an in-flight transmission before END can therefore leave
attempted one greater than completed without incrementing the device error
counter. These observations are consistent with such a stop-boundary
interruption, but do not establish the exact cause or prove a receiver missed an
over-air packet. No per-attempt RF trace or completed-sequence list was recorded.

The original batch was aborted and preserved. The subsequent balanced series
uses a 16 s source duration and 10 s acquisition budget for **all** format and
stagger conditions. Previously successful 16 s runs motivated that choice, but
16 s does not guarantee future accounting consistency: every run must still
pass the unchanged checks. Its recall percentages are not directly comparable
with the earlier 14 s acquisition / 16 s source experiments, because the amount
of acquisition time relative to the denominator differs.

[Sanitized failed-control record](failed-12s-control.json) preserves the counts
and failure explicitly. It must not be pooled into the passed-controls summary.
