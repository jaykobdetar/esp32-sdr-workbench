# Source distributions and installed host tools

The wheel installs the Python host tools. Firmware building is a checkout workflow:
run `python nrf52840-transmitter/host/build_firmware.py --version VERSION` from
an actual Git checkout after following the pinned dependency instructions in
`nrf52840-transmitter/README.md` and `nrf52840-transmitter/THIRD_PARTY.md`.
The installed `nrf_tx.build_firmware` module supports `--dry-run`, but an actual
build deliberately reports a checkout requirement before creating files.
The wheel does not bundle the nRF SDK or other downloaded vendor dependencies.

The source distribution includes the public tests, firmware source, documented
experiments and filtered evidence needed for offline verification. It is not a
Git checkout and does not include downloaded SDKs. `MANIFEST.in` explicitly lists
public resources rather than recursively including arbitrary local directories.
When adding test fixtures, firmware files or public evidence, add their exact
paths to that manifest. Never add raw RF recordings, recovery backups, firmware
binaries, private data or downloaded nRF vendor trees.

To check a release, build both artifacts, extract the source archive into a clean
directory, and run `QT_QPA_PLATFORM=offscreen python -m pytest --collect-only -q`
and `QT_QPA_PLATFORM=offscreen python -m pytest -q` there with the declared test
and runtime dependencies installed. C-model tests additionally use a host C
compiler; retention-patch verification uses Git. Install the wheel into a
separate environment and smoke-test its imports from outside the checkout.

## Offline verification of this packaging change

With Python 3.10, setuptools 81.0.0 and PySide6 6.11.3:

- Built an sdist and wheel using the setuptools build backend.
- Fresh extraction: 466 tests collected; 466 passed and 5 subtests passed with
  the offscreen Qt backend.
- Audited the source archive: every existing tracked public resource under
  docs, experiments, firmware, transmitter, tests and scripts is present;
  prohibited raw-RF/binary extensions and vendor/backup/recovery directories
  are absent.
- Installed the wheel into a separate target directory and imported all
  `sdr_research` modules, the three packages, transmitter build/updater/controller
  modules and the RF/receiver/retention campaign modules from outside the source
  checkout (25 imports). This is not a blanket import-all claim: historical
  command-line scripts such as `make_uf2` and `nrf_parameter_screen` parse command
  arguments at import time.
- Installed firmware builder: normal invocation exits with the checkout guidance
  (status 2); `--dry-run` prints a plan successfully. Three regression tests cover
  the error without writes, dry-run, and Git worktree-file recognition.

No firmware compilation, flashing, hardware access or vendor download was part
of this check. Evidence/provenance source bytes were not changed.
