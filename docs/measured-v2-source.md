# Measured optimized-v2 source provenance

The proposed retrospective source tag `measured-v2-source` targets
`d6f0e7eaa7b1407db43abbe56363a08c4d28bdd2`, the first public source snapshot.
A local annotated tag has been prepared; publication is a separate owner decision.

The measured application SHA-256 is
`8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad`.
Its original metadata records variant `esp32-pipeline-optimized-v2`, revision
`unknown` and build timestamp `2026-11-10T23:21:02Z`. The archived source tarball
SHA-256 is `fa94dc0df60ccfd2d9c5134dce3453c72c85459a89e60a559377fcb4d615b197`.
The [published build manifest](evidence/build/manifest.json) and later
[measured results](evidence/README.md) identify that binary separately.

A byte-for-byte comparison against the private archived build source found:

- 495 of the tag target's 500 firmware files match, including **all 100 files in
  firmware/main**, the version generator, ESP32 defaults and variant file.
- Three changed files are packaging-only: README, the target catalog (ESP32
  retained while other targets are removed), and CMake (reject non-ESP32 targets).
- Two files are added provenance/license notices.
- The public subset omits 319 archive files, including research tests, tooling,
  documentation, non-ESP32 defaults and component extras. No main/ files are omitted.
- All 13 recorded checksums in the original private artifact set verify.

This establishes source correspondence, **not** that the original binary was
built from this Git commit. That Git provenance was not recorded. A rebuild
embeds a different Git revision and timestamp and need not reproduce the binary
hash or timing. The tag is a discoverable historical source reference, not a
new binary release, reproducible-build certificate or approval to flash.
