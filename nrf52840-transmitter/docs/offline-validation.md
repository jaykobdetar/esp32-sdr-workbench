# Public source verification

Checked 2026-11-11 without opening a device, flashing firmware or transmitting RF:

- Host tests: **30 passed**, including UF2 protected-range/format rejection, controller framing errors, finite duration, exact serial matching, missing/invalid target rejection, ambiguous devices, verified symlink-port aliases and explicit-port mismatch.
- C schedule tests: passed (missed/late slots, wrap, bursts, 20,000 seeded jitter slots, saturation).
- C stop-control tests: passed (END before/during stop, cancellation, counted completion, timeout, stalled timer, wrap).
- C CRC32 tests: passed (standard vector and empty input).
- Actual parser/status extraction test: passed with host address/undefined-behavior sanitizers.
- Python host tooling: compile check passed.
- ARM compile/link: passed with GCC 15.1.0 (devkitARM release 66), using the pinned local official dependency checkouts. Upstream Nordic headers emit unused-parameter warnings.
- Write-once public packager: produced valid 55-block UF2; application payload range `[0x23000, 0x26700)`, safely below `0x40000`.
- BIN SHA-256: `ad269f4dc63a32eaa95f631f164d2ab45c1ef70248cf2b75f93ccd21228bdfe9`, identical to the retained historical 0.2.2 BIN with this compiler/dependency combination.
- UF2 SHA-256: `e05c5ee383179fc485fe34bff18ca75c002e2a082d01f896fa6fb521af171416`.

This checks the public-source build and packaging, not a new hardware run. Official dependency revisions and submodule pins were verified locally; downloading dependencies into a fresh machine and alternative compiler versions were not separately tested. Repeat offline checks and verify recovery before using a new build on hardware. Generated artifacts, debug outputs and dependency checkouts are ignored by Git and are not part of this publication.
