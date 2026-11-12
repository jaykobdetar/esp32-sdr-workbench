# Adaptive-v3 evaluation evidence

[Full report](evaluation-report.md) · [Machine-readable summaries](evaluation-results.json) · [Publication manifest](publication-manifest.json)

This supplement publishes existing 11–12 November 2026 measurements and reviewed
source changes. Publication accessed no device, flashed no firmware and generated
no new RF measurement. Private originals remain unchanged. The source changes are
the stable top-three tie-eviction fix, optional default-off heap/stack telemetry,
and tested passive-board, matched-gain and direct-raw validation harnesses.

## What the results support

925 completed pipeline runs processed 1,568,533 captures. All 1,818 saved I/Q
files have recorded valid UART transport CRCs. Ten passive runs retained no event.
Only the separate instrumented, tie-fixed candidate completed the 30-minute soak;
this is not a soak result for the unchanged released-v3 binary or a newly built
source-publication binary. The strong-source packet endpoint yielded 1/8 v2 AGC
ON runs and 0/8 in each other image/retention/gain stratum. There is no demonstrated
retained-packet advantage over v2. Candidate windows are not distinct packets.

The verified v2 application was restored. Stored PHY calibration changed in
173/1,904 bytes during the campaign, with timing and cause unknown. Application
restoration did not restore original calibration. Sequential RF comparisons cannot
assume identical calibration or attribute every difference to detector source.
Geometry was unmeasured and no calibrated sensitivity or packet recall is claimed.

A [separate 12 November calibration follow-up](calibration-follow-up.md) reproduced
conditional refresh using v2 alone: 150 bytes changed once, then two sessions were
stable. This favors normal refresh rather than a v3-specific defect, while leaving
the original trigger/timing unproven and calibration as an RF-comparison confounder.
Its later smoke results are not included in the original campaign totals.

## Image identities and provenance

| Image measured | Application SHA-256 |
|---|---|
| Known-good optimized-v2 | `8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad` |
| Unchanged released adaptive-v3 | `c5360d2b4e2ff5711d9b9ef43040b1290e5c31ec4de631a1f372fa5ecd0ce860` |
| Separate instrumented, tie-fixed candidate | `2f5be585ae66126496080cb1fcd6e59424dbaa959f5078286338bdbebab8dffe` |

The source base is `bc6472c8d361c63defb4dec5c5bb86f9bfd564cb`; measured candidate
changes were then uncommitted. The manifest records the published firmware/harness
bytes and the original report/result hashes. `publication_source_files` records
that snapshot, not a future-tree invariant: later firmware/harness edits must not
rewrite those historical hashes. CI checks only the immutable `evidence_files`. New builds may differ due to source
revision, timestamps, instrumentation and layout. No tag, binary release or device
installation is created here. Three original stage summaries have null local
artifact fields; they remain null rather than being retrospectively filled. The
report's image grouping also relies on private installation/verification records.

The original evaluation report SHA-256 is
`4a784d0708e32ef8634ffb6f939ff1127811094a42ba923584a7ce60ef2f9857`.
The original sanitized result SHA-256 is
`e8b14867c0e15e448b36c8e28f3656e6bf3b6bec95af1e860bafceb9db7cae40`.
Public copies have their own hashes because publication wording was clarified and
observed decoder byte strings were removed. Original per-file/source hashes are
provenance, not links to downloadable private files or cryptographic proof that a
measurement occurred as described.

## Reproduce public arithmetic and host checks

From the repository root:

```sh
python3 scripts/verify_adaptive_evidence.py
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

The verifier recomputes counts, summary processing/duty checks, per-run packet
endpoint counts, 95% Wilson intervals and exact paired sign-flip p-values from the
published records. It checks image hashes where populated and reports saved health
minima. It does **not** independently remeasure acquisition, re-decode RF, recompute
transport/RF CRCs from withheld waveforms, or repeat the private calibration audit.
The health records expose aggregate minima rather than all original telemetry;
checking their consistency is not a new heap measurement. Statistical intervals
are descriptive; temporal dependence, selection and multiple comparisons remain.

Optional broader source-audit sweeps (host C compiler, Python 3 and ASan/UBSan):

```sh
bash docs/evidence/adaptive-evaluation/audit-sources/run.sh
```

This relocatable runner compiles in a fresh temporary directory and never opens
hardware. It checks all 16,381 energy/crop/packing lengths, 524,288 Q16 transitions,
16,125 allocation lengths, 84 boundary/kernel/copy combinations, 100 acquisition
failure combinations, and the synthetic crop-alignment sweep. These sources are
adapted from the original audit; current-tree tie mismatches must be 0/4,096, not
the original release's 773/4,096. Integrated source is generated from this
checkout's actual pipeline fixture rather than an absolute-path archival copy.
LeakSanitizer is explicitly disabled to reproduce the original ptrace-limited
ASan/UBSan run. Do not describe that as a LeakSanitizer pass. No measurement of RF
recall follows from the synthetic crop test.

The hardware harnesses are deliberately separate from offline checks. See
[matched trials](../../matched-adaptive-gain-trials.md) and
[health telemetry](../../pipeline-health-telemetry.md). They require verified
identities, recovery planning and a separately authorized hardware session.

## Privacy allowlist and omissions

Only reviewed source/docs/tests and these curated summary files were included.
No raw I/Q, original SigMF metadata, flash/NVS/calibration bytes, recovery images,
application binaries, USB identities, private absolute paths, credentials or
private links are published. Basenames and SHA-256 digests identify withheld
artifacts without exposing their original directories.

The public JSON additionally omits eight `observed_payload_hex` values and two
observed `address_hex` values, including partial candidates, to avoid publishing
incidental decoded bytes. Expected known test payloads, the report's intentional
source address `efcdab89c3`, scalar CRC results, errors and sequence numbers remain.
Numeric measurements and success flags are unchanged. Publication annotations
clarify that earlier “nothing published” statements described that checkpoint.

This is a reviewed export, not an all-purpose sanitizer or a guarantee that other
campaign outputs are safe to publish. The harnesses intentionally record private
identity and path information in new local outputs. Review any future export
separately. Raw waveforms cannot be reconstructed from this supplement.

## Publication verification

The publication snapshot passed 448 host tests plus five subtests on Python 3.10 and 3.14,
Ruff lint/format checks, Git whitespace checks and all three offline evidence
verifiers. A fresh pinned-SDK default-off ESP32 build and a subsequent opt-in health
build both compiled successfully; neither new binary was flashed. The broader
O0/O2 source audit reran successfully under ASan/UBSan, with 0/4,096 tie-order
mismatches and the reported synthetic crop results. LeakSanitizer was disabled,
not passed. CI on the eventual remote commit is a separate check.
