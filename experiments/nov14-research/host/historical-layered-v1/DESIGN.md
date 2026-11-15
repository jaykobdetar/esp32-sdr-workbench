# Layered timeout policy: design v1

Design only, not implementation or operational approval. Preserve bounded-adapter-v2-final and the three applicability results. No devices, serial imports, new IQ, full transcript replay, timing sleeps or stress work.

## Confirmed problem and unchanged outer contracts

The pinned v2 adapter assigns the caller's entire whole-call timeout to the backend, then charges setup and restoration against that same whole-call budget. Three deterministic tests of the actual pinned Collector.read establish full-timeout empty/partial results fail at 102 ms for a 100 ms request with synthetic 1 ms setup and 1 ms restoration; a 10 ms early return succeeds at 12 ms. These are fake schedules, not pySerial measurements.

Keep the collector unchanged: requested transport timeout still bounds the whole call, polling reads remain at most 100 ms, existing session/frame deadlines and four-second I/O silence/ownership rules remain, and empty returns do not reset progress. The collector's existing read comparison allowance is not enlarged or repurposed. Writes retain their exact whole-call comparison. Quiet remains a zero-wait backend read with the existing 10 ms whole-call allowance. Never treat four seconds of silence allowance as permission to overrun one call.

## Proposed fixed policy: HALF_WAIT_QUARTER_SETUP_V1

Choose a fixed fractional inner wait, rather than a dynamically changing backend timeout. This deliberately trades a maximum half of the requested wait for setup, restoration, audit and return headroom. It avoids repeated timeout setters and keeps the exact configured backend wait reconstructible from the pinned source plus existing metadata timeout field.

For a positive finite built-in caller timeout T (at most 1 second), let B = floor(T * 1e9) integer nanoseconds. Require B >= 8 ns before backend access; otherwise fail closed for insufficient representable headroom. Conversion uses the pinned Python binary64 arithmetic, not a claim of exact mathematical decimal time. Reject overflow/nonfinite. Existing metadata position 4 stores B.

* Inner wait I = floor(B / 2) ns.
* Setup/admission deadline A = floor(B / 4) ns after the operation's initial clock observation.
* Planned restoration/journal interval after latest admitted full wait: up to floor(7B / 8) ns, leaving approximately B/8 for final return and collector observation.
* Final adapter-ready deadline F = floor(7B / 8) ns after the initial observation. Equality may pass the final deadline; pre-I/O elapsed must be strictly less than A.
* Assigned timeout seconds is nextafter(I / 1e9, 0.0) for I > 0. This is one deterministic inward binary64 rounding step, never an added grace period. It is fixed for that operation, not recomputed after setup. Validate the actual property equals that assigned value.

For timeout T == 0, use B = 10,000,000 ns only for whole-call accounting; metadata position 4 remains zero, backend timeout stays exactly 0, A = 2,500,000 ns and F = 8,750,000 ns. The same policy identifier disambiguates this rule. No blocking wait is introduced into quiet.

The fractional choice is a conservative initial applicability policy, not fitted to physical timing and not a universal bound. A 100 ms poll configures approximately 50 ms backend wait; with the synthetic 1+1 ms setup/restoration it should finish around 52 ms. A 10 ms early return remains around 12 ms. A 1 second write configures approximately 500 ms backend wait. Partial/zero writes remain fatal and are not retried; reduced write patience is an explicit compatibility tradeoff requiring later real-backend qualification. An empty/partial read is an ordinary result only if all other validity and timing checks pass.

## Admission, cleanup and final checking

1. Existing bounded event/operation admission, immutable argument checking and audit reservation remain before backend activity. Start the operation clock early enough to include that admission work in its budget, without backend getters. Source preparation must identify the exact timestamp placement; no renewed clock after setup. If local setup already exhausts A, fail before timeout setters/read/write.
2. Check original settings/timeout state, set the single fixed inner timeout, verify it, and recheck settings. Immediately before the backend call, observe elapsed again. Require a nonnegative elapsed < A and sufficient remaining whole-call time for I plus the declared restoration/return headroom. Since I and A are fixed, this second condition is arithmetically redundant except integer boundaries, but state/assert it explicitly. No recomputation/retry if insufficient; restore any attempted timeout change, poison, retain failure audit and issue no read/write.
3. Backend call is at most once. Retain compliant returned bytes before post-return clock/getter work. Preserve prior behavior for malformed returns, partial writes, consumed bytes not delivered to collector and restoration failure. No blind STOP/DROP/RELEASE or descriptor reset.
4. Always attempt necessary timeout restoration even when the budget has expired. Restoration may itself block or fail; the adapter cannot preempt backend code. Record observed deadline failures as DEADLINE, not missing clock. Preserve restoration error precedence and explicit unknown timeout state.
5. Prepare the bounded operation journal record and perform a last clock/deadline/poison check as late as feasible before committing return eligibility and returning, including observed encoding work. If the observed elapsed exceeds F, fail closed even if still below B: this is exhausted declared return headroom, not an assertion that the original caller deadline was already crossed. Record a distinct fixed reason/stage code for this conservative subdeadline. No apparent 'success' followed by ignored observed overrun. Source review must verify the exact final timestamp/commit ordering; postcheck commit/release/return remains covered only by headroom plus the caller's unchanged whole-call check.

No finite reserve can guarantee arbitrary scheduler, clock, property getter/setter or backend behavior. A stall after the final observation may only be detected by the collector's return-time check. That invalidates collector trust and must prevent further commands; do not claim the adapter independently detected an interval it never observed. Existing fail-closed ownership behavior stays intact. No full physical lease or real-time scheduling guarantee is introduced. Concurrency/exclusive-use prerequisites remain unchanged.

## Audit version and reproducibility

Do not change the 24-scalar operation layout or reinterpret its requested-timeout field as backend wait. Pin the source and add a fixed timeout-policy identifier to a new bounded receipt schema version (proposed version 3); include it in README/provenance and re-prove the 4,096-byte receipt bound. Existing receipt v2 and all old timing evidence remain historical. Derive I/A/F and assigned binary64 wait exactly from field 4 and the policy. Zero denotes the explicit quiet rule, not an unknown timeout.

Metadata elapsed is a named observed checkpoint, not guaranteed end-to-end transport latency. Preserve flags for missing clock and incomplete byte evidence. Record pre-I/O insufficient headroom separately from final headroom exhaustion and actual observed whole-call overrun, using fixed codes and no arbitrary exception text. An audit cannot infer backend compliance, device-side command timing or source transmissions. No dynamic actual-wait field is needed for this fixed policy; if implementation later chooses dynamic timing, that is a new reviewed schema/design, not a silent substitution.

## Small proposed fake tests, not executed here

Use the existing actual Collector.read harness and pinned collector unchanged, with scalar fake clock and no sleeping/native decoding:

1. Existing full-empty schedule: backend advances by its newly assigned inner wait; 1 ms setup + 1 ms restore. Expect valid empty return, restored properties, no poison, collector progress unchanged.
2. Existing full-partial schedule: same schedule, one byte for a two-byte request. Expect normal partial read delivered and recorded once by collector; no invented frame completion.
3. Existing early-empty schedule: 10 ms backend time plus 1+1 ms overhead still succeeds. Compare to preserved v2 results, not overwrite them.
4. Setup reaches A exactly or exceeds it: no backend read/write; attempted setter restored; poison and fixed insufficient-headroom reason. Also tiny positive timeout below representable policy bound fails before backend access.
5. Backend violates inner wait enough to exceed B, or restoration pushes elapsed beyond B: consumed bytes retained, collector delivery false, restoration attempted, actual overrun distinguished from missing-clock error.
6. F < observed finish <= B: reject conservatively with return-headroom reason, not actual-whole-call-overrun label. Exact F boundary test uses integer fake clock.
7. T == 0: backend receives exactly zero; promptly empty quiet succeeds, unexpected byte remains collector quiet failure, setup exhaustion prevents I/O, actual 10 ms overrun rejects. No grace increase.
8. Writes: backend receives fixed half wait, full count within headroom succeeds; partial/zero counts fail without retry. Insufficient setup reserve produces zero writes.
9. A finite sequence of early/full-inner empty polls exercises actual collector silence tracking: empty results do not reset io_progress; advance fake clock to the existing four-second threshold, and verify collector refuses before an additional backend call. Use a few calls plus deliberate clock advance, not an 80-call or unbounded loop.
10. Source/record derivation tests for fractions, zero special case and inward conversion; unchanged property restoration, poison, bounded-audit and helper-status regressions. No full transcript/large fragmentation test until separately authorized.

Before any implementation, independent design review and parent approval are required. Later live admission still requires an awake user/recovery readiness, actual backend setup/restore/return measurements and source-OFF scope; these fake cases cannot authorize or replace it.
