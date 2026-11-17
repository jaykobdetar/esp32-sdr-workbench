# Layered timeout v2: scoped correction review

2026-11-14. Verified manifest `545644c6ccaacb10409bb24c5708e579de116f0ef599d1b0fcf23d2a3047e2d1`, all seven current entries, and unchanged original v1 review pins. Adapter SHA256 `fc9da9790e3b3698c0806c67b6761830bdff03f495c4243c6c5f706ae85c0356`.

**Both initial source findings are resolved.** Independently ran the 35 tiny generic/layered tests, all passing in 0.031 seconds. No historical corrected-three controls rerun, native/full-session replay, sleeps, devices or new IQ.

Sequential clock observations are now validated, including the post-backend timestamp. Backward return time is preserved in its field, raw bytes remain retained, delivery is rejected and a fixed reversal flag records the observation. A reversal above the initial timestamp also rejects; checking only elapsed from start would have missed it.

A later actual outer overrun upgrades an earlier secondary headroom-only outcome to DEADLINE. Chronological first_failure remains headroom where that happened first. An outer-overrun flag preserves the later observation even when a restoration error correctly keeps secondary precedence. The four focused regressions cover these distinctions.

No fractions, collector timeout contracts or operational scope changed. No new blocker identified in this scoped correction review; suitable for separate offline freeze. The prior successful three-case controls are historical v1 evidence, not re-executed v2 outcomes. Host-client live HOLD remains: generic fake coverage does not qualify real backend setup, restoration, return scheduling, continuous exclusivity or hardware recovery readiness.
