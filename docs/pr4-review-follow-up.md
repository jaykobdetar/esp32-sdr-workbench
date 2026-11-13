# PR #4 review follow-up

This follows the review of `688b5a4`. The PR remains draft and unmerged.
The new firmware family is `esp32-dual-sparse-iq-experimental-v7` so that the
published v6 campaigns are not mistaken for measurements of this changed binary.

## Implemented

- **Capture-SRAM ownership:** all acquisition callers share a coarse scheduling
  wait before setup, ADC/filter overrides, or handing SRAM to the MAC. The final
  trigger wait contains no cooperative yield. This covers first deadlines,
  `TIMEDCAP`, traces, and every capture at long periods. C regression tests run
  the actual acquisition function with ownership-checking mocks at `-O0` and
  `-O2` under UndefinedBehaviorSanitizer. They are not a hardware timing model.
- **Complete capabilities:** send `CAPS` from a compiler-sized constant, bypassing
  `reply()`'s 256-byte scratch buffer. Tests compile all four CP2102/health
  combinations, including the one whose line exceeds 255 bytes.
- **Background policy:** the host checks BEGIN against an explicitly expected
  policy. The Studio worker passes its verified policy; campaigns expect the
  rule 1 they select. Bench session/campaign defaults are rule 1. Studio's GUI
  preserves the current firmware policy by default, whose boot default is rule 2,
  as does the recorder. Those are different defaults, not equivalent algorithms.
- **Failure diagnostics:** read optional deferred `ERR` text after a failed stream
  summary with a one-second bound and include it in the error. Success and normal
  STOP do not wait for a nonexistent diagnostic; missing text never makes a
  failed stream valid.
- **Evidence in CI:** recompute all 14 published archives / 36 timing trials and
  compare their analysis fields with `summary.json`, including sensitivity and
  whole-burst metrics. Verify manifest hashes/sizes and all 12 packet-proof runs.
  Verifiers support direct-script and module invocation. Historical evidence and
  measurement source identities are unchanged; only the documentation checksum
  changes with its documented command examples.
- **Installed launcher:** `esp32-sdr studio` now launches Studio, with normal
  `--help` and `--demo` support and dispatch regressions.
- **Source distribution:** checking the installed-command/package path exposed
  missing allowlist entries for this PR's firmware headers and evidence. Add
  exact public files, not a broad directory graft, so an sdist can build the
  firmware and run the evidence tests without shipping local backups or raw RF.
- **Build guide:** correct its stale claim that the current tree is adaptive v8,
  identify the experimental build and the pre-stream source commit explicitly,
  and correct the NVS-error behavior to idle rather than reboot.

## Suggestions deliberately not applied

- **Tagging or selecting the merge/release layout:** the adaptive-v8 base remains
  reachable at `2c06109317d0ad13af5f0273f5ca12e5befc2e0d`. No tag, merge, or branch
  restructuring is necessary to fix this review. The experimental branch remains
  isolated while the owner chooses what to release.
- **Moving 42 MB of evidence to LFS or release assets:** moving files alone would
  not shrink existing Git history. Purging/replacing historical evidence needs an
  explicit repository-distribution decision, changes offline reproducibility, and
  can require history rewriting. This follow-up preserves the published evidence.
- **Larger sparse-I/Q chunks:** worthwhile to benchmark separately, but it changes
  the 48-byte wire format and queue/latency tradeoff. It is not a safe mechanical
  substitution in a protocol with existing firmware, hosts and measured-binary
  evidence. The 70,272-byte wire cost per snapshot remains documented.
- **Splitting this large PR:** sensible review organization, not a correctness fix.
  Rewriting/splitting 32 existing commits would obscure this focused follow-up and
  disturb review context. The PR's review map and this checklist retain clear
  boundaries without making that repository-level choice for the owner.

## Validation scope

The follow-up includes host regressions, full-suite validation, source/wheel
packaging checks and pinned-SDK compilation. Hardware checks are bounded passive
control/CRC checks, not a repeated coverage campaign or a 30-minute soak.
Only the exact installed image and settings from a hardware check can support its
results. No v6 coverage, packet count, or throughput result is reassigned to v7.
Device identities, flash backups, calibration fingerprints and incidental RF stay
private. Application-only validation must preserve each board's different layout
and protected regions; it must not rewrite bootloader, partition table or NVS.
