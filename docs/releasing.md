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
