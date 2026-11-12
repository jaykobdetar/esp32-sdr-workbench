# Review follow-up: 12 November 2026

## Findings and changes

1. **Variant collision: confirmed.** Corrected source now identifies as
   `esp32-pipeline-adaptive-q16-v4`, distinct from the original released-v3 and
   instrumented tie-fixed images. Revision, build configuration and binary hash
   still identify an exact artifact; a family name alone cannot do that.
2. **Measured-v2 tag: confirmed missing.** A local annotated `measured-v2-source`
   tag targets `d6f0e7eaa7b1407db43abbe56363a08c4d28bdd2`. See the
   [source/archive comparison and original unknown-revision caveat](measured-v2-source.md).
   No tag, source commit or release has been published by this follow-up.
3. **Three-crop limitations: supported.** Single retention stays the default;
   no crop redesign or performance optimization was added. The 3.893% synthetic
   containment result depends on energy shape and is not measured packet recall.
   Mean accumulated copy time in the stronger-source observations was about
   4.7 times v3 single, not an intrinsic fixed threefold cost. The
   [adaptive guide](adaptive-detector.md#research-status-of-three-crops) records
   the evidence and the need for a packet-linked design before further investment.
4. **Calibration boundary logging: useful and implemented.** `CALHASH?` hashes
   the logical stored PHY blob using a read-only NVS handle. Campaign helpers
   record stage/run boundaries, changes, unsupported legacy firmware and errors.
   No repair, erase, reset or forced calibration occurs in this command.
   See [privacy and interpretation limits](calibration-fingerprints.md).

Historical measurements and their source checksums were left unchanged. No old
campaign was given invented calibration observations.

## Exact software and build checks

Runtime-code commit: `2af1e946c8c17ed97c1ed6028a4fe701e2bb49de`.
Later documentation edits do not change the tested runtime code.

- **463 tests and five subtests passed** on both Python 3.10 and 3.14.
- Ruff lint, format check, Git whitespace check and all three offline evidence
  verifiers passed.
- New command tests at `-O0` and `-O2` under UBSan cover exact read-only keys,
  output size, failed open/read/allocation, wrong lengths and balanced cleanup.
- Host tests cover changed/unchanged hashes, clock regression, malformed values,
  no query after transport failure, current-v4 capability requirements, historical
  unsupported markers and source-stopped boundaries across all three runners.
- Original-ESP32 default-off firmware compiled with pinned ESP-IDF
  `25fe69f946311abdaf9ad56591f25fedbc20ac98` and its Xtensa toolchain.
- Built application: 687,488 bytes, SHA-256
  `3041df5098cb72c40024c2d17e056a4f15b0f6e8434c7b881aa6bee714aff817`.
  Embedded v4 revision is the code commit above; build timestamp is
  `2026-11-12T02:09:08Z`. `DETPIPE_HEALTH=OFF`; main-task stack config is 8192 bytes.

These are local checks, not new remote CI results. Transmitter firmware and
historical-retention firmware were not changed or rebuilt for this follow-up.

## Bounded passive board check

On the previously verified original ESP32, secure boot and flash encryption were
checked disabled, the compatible partition table and known-good v2 application
were verified, and private recovery material was retained. A fresh protected-prefix
snapshot recorded the current calibration/settings before installation.

Only the application partition was written. The bootloader, partition table,
NVS and PHY-init prefix matched byte-for-byte immediately after each application
write and before the subsequent normal firmware boot. No calibration rollback,
full-chip erase, permission change or transmitter START was performed.

Two local preflight setup errors stopped before any application write: an export
subdirectory mismatch, then a Boolean-versus-integer check of the SDK's disabled
secure-boot flag. Paths and the SDK return contract were verified before proceeding;
no security gate was removed.

The exact default-off v4 image above passed:

- 210 valid read-only stored-calibration observations, including 200 repeated
  queries, stage boundaries and before/after four pipeline runs.
- Unchanged cleared heap after the query series and after each pipeline run.
- Three raw captures and six retained buffers with valid transport CRCs.
- Four 250 ms pipeline runs: three single-retention and one three-crop compatibility
  check. No pipeline status, packing or capture errors were reported.
- Correct v4 revision/capabilities, complete capability framing, and explicit
  disabled heap/stack instrumentation readback.
- An independent offline NVS parse plus Python SHA-256 exactly matched the firmware
  hash. The pre-install and post-v4 sampled calibration blobs were identical.

The known-good optimized-v2 application was restored and its flash digest verified.
A final receive-only check passed three raw captures plus one 250 ms pipeline run
with a valid retained transport CRC. Cleared v2 heap was 137,688 bytes with a
73,728-byte largest block. Original gain/selectors were restored. The transmitter
remained healthy and stopped, with its completed-packet counter unchanged.

## Limits

This is a short functionality/recovery smoke check, **not** a new soak, stack
high-water evaluation, sensitivity test, packet-yield comparison or v4 performance
benchmark. The single three-crop run checks compatibility, not usefulness.
No RF source transmission was needed. No desktop interaction occurred.

Equal stored hashes at sampled boundaries do not prove unchanged live coefficients
or exclude intervening change/reversion. V2 does not support the new query, so
its final boot has no live fingerprint observation. The observer does not change
the SDK's normal calibration refresh or pre-existing firmware startup/error paths.
Raw I/Q, device identities, calibration fingerprints and flash/NVS remain private.
