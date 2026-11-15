# Layered timeout design review

2026-11-14. Design only; verified DESIGN.md SHA256 `f0ad7fe86aa00212c8cc305654090cde2058bde4ed1f470f352386c139fe86a2`. No implementation, tests, sleeps, new outcomes or devices.

**Sound direction for separately authorized preparation. No blocking mathematical defect identified. Live host-client HOLD remains.** A fixed inner half-wait makes an ordinary full-inner-timeout return compatible with a shorter whole-call budget without widening the collector contract. This is a deliberately conservative policy, not an optimized or physically qualified choice.

For integer B >= 8, use I=B//2, A=B//4 and F=(7*B)//8. With nonnegative integer pre-I/O elapsed e<A, e+I < 3B/4, leaving at least the intended approximately B/8 restoration/commit interval before F and B-F return reserve thereafter. Declare the redundant admission inequality explicitly using these integers, rather than ambiguous rounded fractions. Multiplication/division for A/I/F must remain integer arithmetic. For positive I, one `nextafter(I/1e9, 0.0)` step is inward relative to the positive exact rational even if the initial binary64 division rounded upward. Source tests should verify representability and reconstruction from B. Do not derive the wait again from the original T using a different rounding path.

The existing 100 ms fake schedule would wait approximately 50 ms and leave room for its deliberately chosen 2 ms overhead. That is arithmetic prediction only, not a new executed result. A short caller budget or expensive getters can still reject before I/O. Half-length writes explicitly reduce patience; keeping partial-write rejection/no retry is appropriate, not proof of live compatibility.

## Source-review gates

- Place the initial clock before charged reservation/admission work and never renew it. Invalid arguments and clock failures still need bounded fail-closed handling without backend access. Include negative elapsed rejection at all observed timing boundaries, not merely final checking.
- Give precise integer conditions and precedence to setup insufficiency, final return-headroom exhaustion and observed outer overrun. When elapsed>B, do not hide that behind the weaker elapsed>F classification. Preserve restoration failure and unknown-timeout state separately.
- Prepare/encode the journal before the late observation where possible; make the final timestamp, any required re-encoding, eligibility assignment, append and return ordering explicit. The unavoidable work after the observation is not measured by that observation. Do not silently rename this checkpoint total call duration.
- Collector starts timing outside the adapter, so some entry/lock work can precede the adapter's initial observation; collector observes after return. The declared reserve is policy headroom for these gaps, not a guarantee. Keep its existing independent check and trust revocation. A callback can be late even if the adapter's own observed checkpoint passed.
- Retain exact caller-timeout metadata, receipt schema 3/policy identifier and a fresh receipt bound. Preserve old freezes and applicability evidence. A fresh implementation must explicitly document newly added fixed error codes so old audit validators cannot silently misread them.
- Quiet stays true backend timeout zero with the existing outer 10 ms contract. Empty returns must not renew collector I/O progress or ownership. No cleanup/retry is authorized after poison.

The proposed finite fake cases address the confirmed problem and boundaries, including actual collector read/quiet/write contracts where applicable. Full partial-read delivery will require a small local transcript destination and normal collector logging fields in the prior minimal harness; do not confuse that plumbing with a complete session/native replay. No full replay, maximum-load study or physical experiment is needed for this design review.

Preparation approval belongs to the parent. This review does not authorize execution or remove awake recovery/exclusivity gates. Scheduling, preemption, timeout-property behavior and actual backend compliance remain unqualified; no finite reserve establishes a universal real-time bound.
