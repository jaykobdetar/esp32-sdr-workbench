# Stride V4: measured original-ESP32 bench candidate

This opt-in experimental app is the receiver firmware used in the best held-out four-board result on the November 17–18, 2026 controlled bench. It is not the default firmware. It only checks known frames from the dedicated Nordic test source; the result does not establish arbitrary device decoding or continuous coverage.

The same firmware was used at both settings: 200 snapshots at 8 ms with a 2 ms board stagger recovered **1,792/10,500 (17.07%)**, versus **658/10,500 (6.27%)** at 20 ms with a 5 ms stagger. The 2.72× comparison is a scheduling result, not a firmware-only speedup. Three runs selected the setting; three subsequent runs scored it. The denominator includes source startup and slack. The subsequent endurance study completed 106 accepted trials, with 371,000 controlled transmissions.

## Reconstruct without hardware

From the repository root, use a new directory. The existing materializer needs Git base object `d23ddddeaabee46d340caba60b038f39946cd534`, and Python 3.12+.

```sh
patch="$PWD/experiments/packet-only-stride-v4/candidate.patch"
python3 experiments/nov14-research/materialize.py core-bank-v9 /tmp/sdr-stride-v4
git -C /tmp/sdr-stride-v4 apply --check "$patch"
git -C /tmp/sdr-stride-v4 apply "$patch"
```

[Source hashes and measured build identity](manifest.json) cover the complete materialized firmware tree before SDK configuration. The reconstructed firmware was checked byte-for-byte against the archived V4 source (excluding generated SDK configuration/build artefacts). The measured app was 720,864 bytes; its SHA-256 identifies the archived app, not a promise of deterministic binary output across build environments.

## Build only, no flashing

Use ESP-IDF at `25fe69f946311abdaf9ad56591f25fedbc20ac98` and its managed Xtensa compiler `esp-16.1.0_20260609`. After activating the SDK:

```sh
idf.py -C /tmp/sdr-stride-v4/firmware -B /tmp/sdr-stride-v4-build \
  -DIDF_TARGET=esp32 -DSDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32 \
  -DPACKET_ONLY_PROBE=ON build
```

This package includes no flash or transmitter scripts, firmware binary, raw RF captures, or device-specific recovery data. Do not use the generic flashing command printed by the SDK: bench boards can use different application offsets.
