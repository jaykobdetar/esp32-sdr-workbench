# Preparing a release

The host version has one source: `sdr_research/_version.py`. Package metadata and
recording metadata read it. Transmitter firmware has its independent firmware version.

1. Finish the Unreleased changelog, choose a version and update `_version.py`.
2. Run all host tests, lint, format, firmware compile jobs and dependency smoke checks.
3. Build a wheel and source archive with `python -m build`; install the wheel in a
   fresh environment and check `esp32-sdr --help` and campaign module imports.
4. Review artifact contents for device identifiers, backups, raw RF and private paths.
5. Obtain the owner's explicit publication approval before creating/pushing a release
   tag or publishing a GitHub release. Pushing reviewed source does not itself create a tag or public release.

A successful compilation is not a device validation. List hardware checks separately
and attach exact source revision, compiler and firmware identity to measured results.

Campaigns use the installed `nrf_tx` and `nrf_campaigns` packages, not `sys.path`
modifications. Install the checkout with `python -m pip install -e .`, then invoke
`python -m nrf_campaigns.nrf_rf_campaign --help` (or the corresponding campaign module).
Legacy direct transmitter commands remain supported. `nrf-rf-tx` is the packaged
controller entrypoint; running it without arguments may require a configured device.

## PR #4 pre-merge decisions

These choices must be settled **before merging**, independently of passing CI.
This PR is still draft; the documentation does not authorize a merge, release,
new tag, archive deletion or history rewrite.

### Default firmware and the pre-stream baseline

Merging the current layout makes `firmware/` build
`esp32-dual-sparse-iq-experimental-v7` by default on `main`. Streaming remains
experimental even though its bounded board checks pass. If the default should
remain the pre-stream detector instead, keep the streaming changes separate or
review an explicit source/build-layout change before merging.

The [adaptive-v8 baseline source](https://github.com/jaykobdetar/esp32-sdr-workbench/tree/2c06109317d0ad13af5f0273f5ca12e5befc2e0d)
and [separate-worktree build recipe](firmware-build.md#build-the-pre-stream-adaptive-v8-baseline-instead)
make that source discoverable without a new tag. Adaptive v8 is compiled and
host-tested, not board-tested; neither a tag nor retaining it as default would
make it a validated stable release. A descriptive source tag can be created
separately with owner approval.

### Self-contained evidence versus smaller clones

At review head `2eb570d`, tracked files total 59,046,004 bytes versus 16,847,275
bytes on the pre-stream `main`: a 42,198,729-byte increase. The **14 compressed
timing archives themselves total 40,777,617 bytes** (40.78 MB / 38.89 MiB), all
new in this PR. These are file/blob sizes, not measured network clone sizes.
The evidence is not an application runtime dependency or part of the wheel, but
it is included in the source distribution and exercised by evidence tests.

Two viable choices remain:

- **Keep the archives in Git.** A checkout/source distribution remains
  self-contained for offline timing reproduction and hash checks. Accept the
  added history/clone cost deliberately before a normal or squash merge.
- **Keep only summaries, packet proofs and manifests in Git.** Publish the
  unchanged archives to versioned assets (or choose LFS), verify their stored
  bytes, add a checksum/size-verifying fetch/cache step, and update the evidence
  tests, checksum inventory, source-distribution allowlist and reproduction
  instructions. Evidence CI must fail if required data is unavailable or invalid,
  not silently skip it. Once downloaded, reproduction can still run offline.

A deletion commit alone **does not** produce a small full clone after an ordinary
merge or rebase-merge: earlier PR commits still contain the archives. Before a
merge, however, an archive-free final tree can be **squash-merged without rewriting
this published branch**, keeping those blobs out of main's ancestry. Retire the
archive-bearing PR branch afterwards and avoid new advertised refs to that
ancestry, since an ordinary clone fetches all branches by default. Existing clones
and GitHub's retained PR objects are not automatically purged. Alternatively,
rewriting the PR's archive-bearing history before a normal merge changes commit
IDs and disrupts review references, and requires coordinated approval.

After a normal merge, removing that ancestry from main is much more disruptive.
Thus the small-clone decision is still actionable now; it must not be deferred
on the mistaken premise that the archives have already entered main. No archives
or historical evidence bytes were changed in this documentation follow-up.
