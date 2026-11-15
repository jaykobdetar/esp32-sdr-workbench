# Prospective trial-local RF clock brackets (opt-in)

`python -m nrf_campaigns.multi_stream_campaign --trial-clock-brackets` changes
only a new campaign's clock-calibration protocol. The default legacy selector
is unchanged. This does **not** reclassify earlier failed experiments, change
firmware, relax timing screens or enable cyclic-GC deferral implicitly.

The dry-run plan declares `trial-batches-v1` before any device opens:

- Each trial gets a fresh **before** and **after** calibration batch with unique
  immutable IDs and its trial index. No phase sweep is supported in this mode.
- Every non-reference receiver needs **at least eight distinct shared capture
  groups on each side** against receiver zero. Multiple packets in one capture
  remain one group. A batch has at most 60 capture attempts, each using the
  existing finite 2-second / 4,000-count transmitter bound.
- **Every assigned valid anchor** is included, even if a peer obtains more than
  eight groups while another catches up. No residual-selected exclusions, no
  eight-group truncation, no borrowing from earlier or later batches.
- Every pre-anchor must be strictly before the requested start and at most
  **60 seconds** old; every post-anchor strictly after the requested end and at
  most **60 seconds** later. The checks use receiver-zero time, not host receipt
  time. Actual min/max ages and exact used group IDs are recorded per receiver.
  Stale or insufficient batches fail, with no automatic retries under new IDs.
- The existing screens remain: relative drift at most **1000 ppm**, maximum
  affine residual at most **20 µs**, and leave-one-whole-capture-group-out error
  at most **20 µs**, along with complete CRC/sequence/terminal accounting.

Fresh pre-batch collection is followed directly by scheduling, without a full
historical report serialization between them. Predictions use all anchors of
that pre-batch only. If independently requested, the scoped-GC experiment can
still perform its bounded precollection before scheduling; its time counts
against the age limit. Post-batch collection follows the existing post-stream
accounting/calibration/full checkpoint. That overhead also counts against the
post-boundary age limit, rather than being hidden or excused.

## Durability without serializing old streams per anchor

Each batch atomically updates its own private
`anchor-progress-trial-NNNN-before.json` or `...-after.json`, containing current
batch metadata, assigned anchors and capture-pair metadata. File contents and
the directory rename are fsynced on the Linux host. Raw anchor snapshots remain
separate private files as before. Previous full `results.json` checkpoints stay
in place; lightweight saves do not overwrite or discard them. Full stream
results are still checkpointed at stream completion, and the full report is
saved after post-batch analysis and in final cleanup. Failure checkpoints remain
failed and may need both the progress file and the prior full checkpoint for
inspection; progress is not a successful coverage result.

Only the newly bracketed trial is analyzed. Its result is frozen, so future
calibration batches do not retroactively alter it. The analysis can still be
recomputed from its exact assigned evidence for audit; malformed batch receipts,
missing identities, duplicate anchors, incomplete batches and cross-batch
capture-group reuse are rejected. Completed receipts include an exact canonical
anchor count and SHA-256 inventory seal covering every assigned identity and
both clock timestamps. Removing an outlier or mutating an anchor without
changing the sealed receipt fails analysis; receipts are not regenerated while
analyzing. Anchor START, partial worker submission and interrupted waits share
a cleanup path that stops the source and positively joins every reader before
any port cleanup, preserving the primary error.

## Interpretation

This prospective local-model hypothesis addresses the legacy selector's ability
to pull distant calibration epochs into earlier fits. Passing screens does not
prove affine timing throughout a long trial, calibrated RF apertures or packet
recall. Residuals and held-out errors remain empirical checks, not certified
uncertainty bounds. Record failed trials as well as successful ones. Do not
claim a sustained fix from bounded trial success or from choosing a policy
post hoc on the same previously rejected data.
