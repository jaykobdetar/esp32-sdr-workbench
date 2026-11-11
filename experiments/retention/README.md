# Optional, unadopted retention experiment

The released `firmware/` remains **esp32-pipeline-optimized-v2**, with the strongest-candidate policy. This patch preserves the separately tested reservoir-retention research variant without making it the default or claiming an improvement.

The controlled trial recovered complete address/payload/RF-CRC frames in 3/12 reservoir ON buffers and 2/12 strongest ON buffers. The paired difference was +8.33 percentage points, with a descriptive bootstrap 95% interval of −16.67 to +33.33 points and exact McNemar p = 1.0. Both OFF sets were 0/12. These are selected-buffer outcomes, not packet recall. See [results](../../docs/nrf-validation-summary.md) and [public evidence](../../docs/evidence/nrf-validation/README.md).

## Source and reproduction

`retention-experiment.patch` contains the changes to the release's pipeline header, receiver routing and variant name, the reservoir selector, and the original host C harnesses. It applies to this public release. It does not include a firmware binary, flash command or recovery image. Test without touching hardware:

```sh
python -m pytest -q tests/test_retention_experiment.py
```

The test copies firmware to a temporary directory, applies the patch there, and compiles/runs the mocked selector/pipeline tests at `-O0` and `-O2`, with warnings as errors and undefined-behavior sanitizer. A host `cc` and `git` are required. The test skips explicitly if these tools are unavailable. These software tests do not reproduce the RF measurements.

For a deliberate experimental build, use a separate clean checkout, apply the patch with `git apply experiments/retention/retention-experiment.patch`, then follow the [receiver build guide](../../docs/firmware-build.md). The measured historical application hash was `06735715da244918ae149b5d26c748faacad3a83274a0a3b91d47eba14384e92`; a new build is not expected to reproduce this byte-for-byte. Flashing requires your own verified device, recovery backup and application artifact. No updater installs this experiment automatically.

After a deliberately installed experimental image, `scripts/nrf_retention_campaign.py` supports a finite controlled trial with explicit receiver/transmitter ports and `--rx-artifact`. The original experiment restored the unchanged optimized image afterward. This publication made no device changes.
