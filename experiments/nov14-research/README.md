# November 14 research preservation

This is an **opt-in, unpromoted research snapshot**, not a change to the default firmware or RF Studio backend. No claim of continuous I/Q, 100% packet capture, or Quest-controller compatibility is made. The compact and legacy comparison used the same firmware and decoder; only result encoding differed.

## Reconstructable sources

`materialize.py core-bank-v9 NEW_DIRECTORY` or `materialize.py compact-v2 NEW_DIRECTORY` reconstructs the source from repository commit `d23ddddeaabee46d340caba60b038f39946cd534` and a SHA-256-checked overlay. Run with Python 3.12+ and a full clone containing that commit. It refuses an existing destination and does not flash anything. The overlays are exact preserved source files; unchanged public evidence already lives in the base commit. Build directories, local environments, Git metadata, private evidence and recovery flash are not part of these snapshots.

- **core-bank-v9:** verified local recovery application after the experiments, not a promotion of the diagnostic bank path into the GUI.
- **compact-v2:** paused extraction and compact result transport candidate, physically compared against its legacy encoding. Full I/Q remains available for auditing.
- **host:** final layered-timeout-v2 adapter, injected collector, reference decoder, fake tests and historical negative controls. `ORIGINAL-SHA256SUMS` preserves original freeze hashes. `legacy-expected-version.json` is a publication-added synthetic fixture.
- **firmware-images:** application-only images, not full-device backups. v9 SHA-256 `8a8b9036a012d80017d05dd494acf8080d825f4b2149d587c70d7f778ee3b2b5`; compact-v2 `fc629ff663647f3e27c4b9494ef78e220ce74ac46cf5137ac8362edf3a73bea5`.

Firmware is supplied for preservation, **not blind flashing**. The two receivers have different layouts and identical USB serial labels. Determine device identity and correct application offset, preserve bootloader/settings/calibration and establish recovery before any installation. Historical build/audit scripts retain original workstation paths; they require an explicit toolchain/path adaptation. Do not execute old hardware harnesses unchanged.

## Validation and results

See [sanitized physical comparison](../../docs/evidence/nov14-compact-comparison/REPORT.md). All 480 captures passed I/Q checks; 96 transmitter-off captures produced no records. Compact output was 20.50% faster; complete audited capture was only 0.81% faster. The 82 versus 91 source-consistent observations do not demonstrate packet-recall superiority. Both boards were restored to exact v9 after that test; the transmitter was off.

Run `python experiments/nov14-research/test-publication.py` for snapshot/data integrity checks. With NumPy available, `python experiments/nov14-research/run-offline-tests.py` runs adapter, collector and codec tests in temporary copies. It relocates only two historical synthetic-fixture paths, leaving frozen files and decoder/reference hashes intact. It opens no serial ports. Test execution in this publication is separate from the original hardware evidence; no new hardware test or firmware rebuild is implied.

## Unpublished/private evidence index

The owner's separately preserved private project archive retains original raw I/Q, immutable run manifests, detailed device logs, application readbacks, calibration/recovery flash, intermediate experiments and full source working trees. These must not be discarded merely because this PR exists. Public JSONs deliberately project only numeric measurements/configuration and remove private identifiers and raw observations. They support aggregate review, not independent RF replay. Synthetic `mock-result` fixtures are generated test data, not ambient recordings.

Rejected overnight work remains documented rather than silently promoted:

- Raw/support-filter union accepted deliberately corrupted synthetic frames and was rejected.
- Exhaustive coherent-prefix search exceeded its candidate cap, yielding no recall result.
- Staged-header experiment completed 176 synthetic inputs but failed terminal memory accounting; a later probe did not retroactively pass it.
- A fixed-location historical diagnostic checked 1,025 previously successful bodies: 775 identical, 179 header rejections, 65 body rejections and six boundary exclusions. No different body was accepted. This is compatibility at known locations, not recall or new reception.
- Differential-prefix work failed its 52-case policy: endpoint/timing ambiguity and no correct nearest-frequency selections in the noisy/DC/faded cases. It was not a packet-decoding or MCU benchmark.
- Host timeout and cleanup failures were preserved with corrected revisions in `host/historical-*`; generic receipts do not establish packet reception or durable evidence.

These negative-study raw inputs and private audit trees remain in the private archive, not this public snapshot. Existing research PRs remain separate and unmerged; this snapshot does not supersede their review decisions.
