# Timeout applicability: three authorized deterministic cases

Executed only three tiny fake-clock cases against the exact frozen bounded adapter and report-only collector source pins saved in outputs.json. cases.py supplies an already-open fake object, a scalar clock and simulated 1 ms timeout-setting plus 1 ms restoration cost. No sleep, serial/device backend, new IQ, native decoder, production patch or full-session rerun. Collector initialization is intentionally bypassed; actual Collector.read, remaining and connection methods are exercised with minimal fields.

| Case | Simulated backend wait | Whole call | Outcome |
|---|---:|---:|---|
| Full-timeout empty | 100 ms | 102 ms | DEADLINE, collector trust revoked |
| Full-timeout partial (one byte/request two) | 100 ms | 102 ms | DEADLINE; byte retained only in adapter audit |
| Early-return empty | 10 ms | 12 ms | Empty returned successfully; collector trust retained |

All assertions passed. Both failure cases restore timeout settings and subsequent reads make no backend call. Failed partial byte is not inserted into collector RX. All durations are deliberately chosen fake values, not physical measurements or recommended reserves.

This confirms conservative interoperability rejection, not an unsafe command, false packet or physical pySerial finding. The four-second collector silence policy does not make a full-budget backend poll compatible with the same whole-call timeout. Collector's independent whole-call read limit (timeout plus one microsecond) also needs consideration; these failures propagate from the adapter before that subsequent collector check. Static review shows increasing only adapter tolerance would not solve both layers.

The prospective design remains in TIMEOUT-APPLICABILITY-PLAN.md: separate outer session/frame/silence deadlines, transport whole-call deadline and shorter backend wait, explicitly covering setup/restoration/return costs. No finite reserve or fake test guarantees arbitrary scheduling, preemption or backend timeout compliance. No redesign implementation is authorized by these results.

The nonfrozen awake plan now places live host-client admission on HOLD pending resolution/qualification of ordinary timeout compatibility. Prior plan preserved; firmware and conditional receiver0-only source-OFF recovery/exclusivity gates unchanged.
