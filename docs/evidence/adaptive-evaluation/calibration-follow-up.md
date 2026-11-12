# Calibration follow-up: 12 November 2026

This follow-up is **separate from the original adaptive evaluation**. Its receive-only
smoke observations are not included in the original 925 pipeline runs or 1,818
saved-file totals. It changes the interpretation of the calibration finding,
not the recorded historical measurements or their uncertainty.

## Finding

The original campaign's active PHY calibration value changed by 173 of 1,904
bytes. Further offline analysis found valid NVS integrity checks and valid
reconstructed PHY internal checksums, including superseded calibration records
predating the campaign. The examined ESP-IDF/PHY implementation can refresh saved
calibration after newly measured values differ, even when saved checksums are valid.

A later bounded test used only the known-good optimized-v2 application, with the
separate RF source stopped. Four read-only prefix snapshots bracketed three boot
sessions: the first transition changed 150 calibration bytes; the next two left
the entire NVS byte-for-byte unchanged. This reproduces refresh without v3 and
does not show an unconditional every-boot write loop.

The evidence supports normal conditional calibration refresh, but does **not**
establish the original campaign's exact trigger or timing. The changed data
includes receive-path DC calibration, so calibration remains a confounder in
sequential RF comparisons. No calibrated sensitivity measurement or proof of
unchanged RF performance was obtained.

## Separate recovery smoke and unchanged scope

The later receive-only smoke passed independently: three transport-CRC-valid raw
captures and a 500 ms pipeline run processing 302 captures, with zero acquisition
or packing errors. No calibration rollback, flash erase, persistence suppression
or firmware change was made during this follow-up.

These findings do not establish packet-detection superiority, validate a new v3
release binary, or turn the original application restoration into byte-for-byte
calibration restoration. Original and follow-up observations must remain separate.

## Provenance and limits of public reproducibility

The source review used pinned ESP-IDF commit
`25fe69f946311abdaf9ad56591f25fedbc20ac98`:

- [`phy_init.c`, lines 798–880](https://github.com/espressif/esp-idf/blob/25fe69f946311abdaf9ad56591f25fedbc20ac98/components/esp_phy/src/phy_init.c#L798-L880) and [lines 946–969](https://github.com/espressif/esp-idf/blob/25fe69f946311abdaf9ad56591f25fedbc20ac98/components/esp_phy/src/phy_init.c#L946-L969).
- [`esp_private/phy.h`, lines 38–45](https://github.com/espressif/esp-idf/blob/25fe69f946311abdaf9ad56591f25fedbc20ac98/components/esp_phy/include/esp_private/phy.h#L38-L45).
- [`esp_phy_init.h`, lines 44–61](https://github.com/espressif/esp-idf/blob/25fe69f946311abdaf9ad56591f25fedbc20ac98/components/esp_phy/include/esp_phy_init.h#L44-L61).

Value-comparison behavior and field mapping were reconstructed from the actual
v2 ELF paired with application SHA-256
`8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad`.
The reconstructed internal checksum excludes the final 516 bytes; the outer NVS
CRC covers the whole calibration blob. Valid checksums alone do not mean the
radio library will preserve every calibration byte indefinitely.

The ELF, raw snapshots, calibration bytes, device identities and complete private
investigation report remain withheld. These source links and reviewed findings
are provenance, not enough to independently repeat the snapshot comparison from
public artifacts. No new device access was performed to publish this note.
