# Four-receiver experimental setup

The coordinated experiment uses the existing, preserved **core-bank v9** application on four original ESP32 receivers. The firmware accepts an independent absolute trigger deadline and fractional period on each board. Coordination is in the host, not a new shared clock or phase-coherent firmware mode. The default application source remains unchanged.

Use the [multi-receiver timing campaign](multi-receiver-timing.md) for nominal acquisition-window coverage and the separate [known-packet control](four-receiver-packet-control.md) for actual sparse-snapshot packet recovery. RF Studio supports four physical devices; its combined spectrum remains asynchronous diversity. Do not confuse these three paths.

## Identity and recovery first

Identical CP2102 USB serial labels do not identify a board. Verify the physical USB path, ESP32 silicon identity, actual flash capacity, security configuration, boot-selected partition, and application region. Keep a private full-device backup checked against device-side block and whole-flash digests. Preserve the original bootloader, partition layout, settings, and device-specific calibration. Never exchange another board's full flash or NVS. A saved application-only image is not a recovery backup.

The evaluated four-board setup used one application at `0x10000` and three at `0x100000`; these are observations, **not offsets to assume on other devices**. The two added factory boards required a checksum-only compatibility step before v9 could start. A high-baud read failure was not treated as a valid backup: conservative, resumable digest-verified reads were used before writing.

## Legacy partition-table checksum compatibility

The two added boards had six valid factory partition entries but no MD5 footer. The pinned modern SDK, built with partition-table MD5 verification enabled, rejected the table. Consequently `nvs_flash_init()` returned **261 (`ESP_ERR_NOT_FOUND`)**, and the application's preservation guard idled without starting RF. This did not mean NVS was corrupt or should be erased.

The existing working OTA-layout receiver had the identical bootloader and identical partition entries, with a valid footer. Computing the footer from each new board's own entries produced that same verified table. The repair changed only 18 non-FF bytes in the footer; no partition offset, size, type, label or flag changed. The private migration verified the whole table sector and every byte outside it and retained exact rollback material. Flashing a table is still more consequential than preparing one: an interrupted sector write requires reliable ROM-downloader recovery.

`scripts/prepare_partition_md5.py` is an **offline-only**, conservative 4 MB layout helper. It opens no serial ports and never flashes. It requires exactly one verified 4096-byte sector, refuses existing checksums/nonempty trailing data, overlapping or unsupported entries, an input hash mismatch, or overwriting an output file. It preserves entries and padding byte-for-byte except for the checksum slot.

```sh
python scripts/prepare_partition_md5.py PRIVATE_TABLE_SECTOR.bin PRIVATE_CHECKSUM_TABLE.bin \
  --expected-sha256 REVIEWED_INPUT_SHA256
```

The output is not a generic replacement partition table. Independently verify the chosen board, selected offset, exact original-sector recovery, compatibility, and all unaffected bytes before any separately authorized write. This repository deliberately provides no blind flash command. Keep these private sector artifacts out of Git.

## Validation boundaries

Firmware compilation and host tests do not validate RF behavior. A verified flash write precedes, rather than proves, successful boot. Record postboot protocol health, passive CRC-valid I/Q and each board's stored-PHY fingerprint. First initialization can alter NVS normally; do not claim factory calibration bytes unchanged without comparison. The original full recovery image must remain intact. During timing and packet trials, a changed/missing fingerprint, regressing clock, incomplete serial evidence or uncertain transmitter shutdown fails the run.
