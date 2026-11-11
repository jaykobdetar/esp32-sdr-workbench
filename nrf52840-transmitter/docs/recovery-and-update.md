# Application-only updates and recovery

## Compatibility, not exact factory identity

The tested Makerdiary nRF52840 MDK USB Dongle reported UF2 bootloader 0.7.1, board `nRF52840-MDK-USB-DONGLE`, bootloader USB VID/PID `2886:f00f`, and application VID/PID `2886:f010`. Its preserved SoftDevice information header at `0x3004` has magic `0x51b1e5db` and application boundary `0x23000` at `0x3008`. These are prerequisites, not assumptions valid for every nRF52840 board.

The installed bootloader supports `GPREGRET=0x57` followed by system reset; this was verified by successful application-to-UF2 roundtrips. Makerdiary source commit `4d08cbb6150a833f146531fa787c3c28fa3ffabb` implements that mechanism. This old source is **not** an exact reconstruction of the installed 0.7.1 bootloader. The manufacturer's published 0.7.1 binary also implements it, but a later read-only code-region CRC of the installed bootloader differed from the published release. Exact byte-for-byte factory identity is not claimed.

Reference release: https://github.com/makerdiary/nrf52840-mdk-usb-dongle/tree/af232a084f3027c3230a2595a404bd37cfe9220c/firmware/uf2_bootloader/0.7.1

## Guarded updater

`host/flash_uf2.py` validates every UF2 block's magic, flags, nRF52840 family, numbering, contiguous destination, application vectors and recovery marker. Every supplied payload stays in **[0x23000, 0x40000)**, inclusive last byte `0x3ffff`. A marker indicates a contract, not proof of safe behavior or trusted code. Use only trusted application source/images.

The normal path identifies the exact configured serial and application, requests STOP and BOOTLOADER, checks the matching USB bootloader and mounted VFAT volume, then saves `CURRENT.UF2`, `INFO_UF2.TXT` and `INDEX.HTM` in a local recovery directory. It checks the preserved SoftDevice boundary before writing. It never writes a raw block device, mass-erases, or supplies bootloader/MBR/UICR/settings payloads. The installed bootloader can update its own application-size/CRC bookkeeping in settings; application-only images do not imply all settings bytes remain unchanged.

The updater waits for the same application serial and exact version, updater capability, health and RF-off state. Disconnect/write errors remain uncertain until that check succeeds; no blind rewrite is attempted. This is version/health confirmation, **not** a cryptographic readback of the installed application. Failed confirmation requires investigation or manual recovery.

The bootloader-visible `CURRENT.UF2` on the tested device covered `0x1000..0xe9fff`, excluding bootloader, MBR and UICR. It is not a whole-chip backup. No pre-install full-chip backup is claimed. Read-only DEVICE checksums are change-detection baselines, not authentication or proof of untouched history. Private backups and diagnostics containing device identities are not included in this public repository.

## Manual recovery

For the compatible Makerdiary board, unplug, hold its button while reinserting USB, then release. Confirm the green LED, `UF2BOOT` volume, expected board/version and your device serial. Use the guarded updater with `--initial` and a trusted application-only UF2. Do not copy a bootloader-update image or the entire CURRENT.UF2 backup as an ordinary application update. Do not rely on double reset or change pin/UICR configuration.

The firmware starts RF-off and retains `GPREGRET=0x57` during application execution so watchdog/unexpected resets request recovery. Power removal clears retention. On another device or build, verify recovery without transmitting before any bounded RF test. Earlier 0.1.0/0.1.1 CDC builds were broken and are not distributed here.
