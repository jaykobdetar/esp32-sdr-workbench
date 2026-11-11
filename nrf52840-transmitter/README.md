# nRF52840 bounded RF test transmitter

Application source **0.2.2** for the Makerdiary nRF52840 MDK USB Dongle. The original 0.2.2 application was hardware-validated with RF stopped afterward. This public checkout generalizes host configuration and build paths; a fresh build is not automatically hardware-validated or guaranteed byte-identical to the historical binary. No Quest protocol compatibility is claimed.

## Build from a clean checkout (Linux)

Install Python 3, Git, GNU Make, a host C compiler, and the official Arm GNU Toolchain for `arm-none-eabi` (or your distribution's `gcc-arm-none-eabi` and `binutils-arm-none-eabi`). Put its `bin` directory on PATH. From this directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p vendor
git clone https://github.com/makerdiary/uf2-bootloader.git vendor/uf2-bootloader
git -C vendor/uf2-bootloader checkout --detach 4d08cbb6150a833f146531fa787c3c28fa3ffabb
git -C vendor/uf2-bootloader submodule update --init lib/nrfx lib/tinyusb
# Exact dependency commits are in dependencies.json.
python host/build_firmware.py --version 0.2.2
```

The pinned TinyUSB repository already includes the CMSIS headers used by this build; its unrelated MCU submodules are not required. Only dependency sources are used: this does not build or replace a bootloader. `CROSS_COMPILE=/path/to/arm-none-eabi-` can select another installed compiler. The builder verifies clean pinned dependencies, records source hashes/compiler, validates application-only UF2, and refuses to overwrite a version. Output is in `artifacts/VERSION/`. ELF/map files remain local build products, not public artifacts. Do not publish private logs or recovery backups.

## Offline checks (no device access)

```sh
python -m pytest tests
make -C firmware VERSION=0.2.2
(cd firmware && python test_offline.py)
for name in schedule stop_control crc32; do
  cc -std=c11 -Wall -Wextra -Werror -Ifirmware firmware/$name.c firmware/test_$name.c -o firmware/build/test_$name
  firmware/build/test_$name
done
python host/flash_uf2.py artifacts/0.2.2/rf-test-tx.uf2 --validate-only
```

## Device selection and deliberate updates

Read [recovery and update requirements](docs/recovery-and-update.md) before installing anything. The updater is Linux-specific and requires `udevadm`, `findmnt`, and a user-mounted VFAT `UF2BOOT` volume. It does not mount volumes or change permissions. Set `RF_TX_SERIAL` to your dongle's exact 16-character uppercase hexadecimal USB serial, or pass `--serial` separately to each controller/updater command. There is no default target and no wildcard match. VID/PID, serial, board/version, SoftDevice boundary and image-range checks remain enforced. Even an explicit controller `--port` must match that identity.

```sh
# Read health without transmitting (also sends STOP on context exit).
python host/rf_tx.py --status-only
# Application-only update: deliberate hardware write, never automatic after build.
python host/flash_uf2.py artifacts/0.2.2/rf-test-tx.uf2 --expected-version 0.2.2
```

Use `--initial` only when already in the verified bootloader. Existing application BOOTLOADER support allows hands-free subsequent updates. On a new dongle, manually verify recovery and its memory layout first. Hardware identity checks are guardrails, not authentication of firmware. Firmware boots RF-off, uses finite transmission bounds, and stops on disconnect. The firmware command protocol and detailed timing caveats are in [firmware/README.md](firmware/README.md). RF use must be lawful and controlled, preferably shielded or conducted; supported frequencies do not confer permission to transmit.

See [third-party provenance](THIRD_PARTY.md). Private recovery dumps, device serials, local paths, raw logs, and old broken firmware builds are intentionally excluded.
