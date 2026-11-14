# Stored calibration fingerprints

Current experimental original-ESP32 firmware identifies as
`esp32-dual-sparse-iq-experimental-v7`; adaptive-v8 is the pre-stream baseline.
The read-only query was introduced in v4.
It advertises `CALHASH` and answers `CALHASH?` with a single JSON record containing
schema version 1, algorithm `sha256`, `bytes` (1904 for the pinned SDK), the digest
and `device_us` (device monotonic microseconds after the read/hash).

The command opens the `phy` NVS namespace **read-only** and hashes only its
logical `cal_data` blob. It does not initialize, erase or write NVS, request
calibration, reset the board, or return calibration bytes, MAC addresses or other
stored settings. Missing data, unexpected length and allocation/read failures
return explicit errors, not an empty or invented digest. Temporary storage is
freed on every path. The command runs between acquisitions, not inside the RF
capture loop. Its small allocation and SHA computation still add host-session
overhead; they are not part of device-local pipeline wall-time measurements.

## Campaign records

The passive validation, matched-gain and direct raw-control runners now append
`calibration_observations` at stage start/end and before/after each run. Queries
are made while the controlled source is stopped. Each observation contains a
host UTC timestamp and boundary name. Valid observations include the stored hash,
byte count, device clock, and whether the hash changed or the clock regressed
since the preceding valid observation. No observation repairs or restores data.

V4, v5 and v6 trials require this capability and fail if the observation is missing
or malformed. Supported-query errors fail the campaign; cleanup still stops the
source and restores available receiver settings. A broken receiver connection is
recorded as unavailable without sending another command. Historical v2/v3 images
remain selectable by the matched/raw runners, but are explicitly **unsupported**
for this telemetry. They are not reflashed or reset automatically to obtain it.

Keep complete results private. A calibration digest is device-derived and can be
a stable fingerprint even though it does not expose the underlying bytes. For a
public report, export only reviewed equality/change results and observation
coverage; do not publish raw digests, NVS dumps or device identifiers by default.
New output directories are created with owner-only access.

## Interpretation and stage transitions

Compare the ending hash of one stage with the starting hash of the next, along
with exact application identity, boot/reset history and RF configuration. A
change brackets a stored-record transition; mark comparisons spanning it as
confounded rather than pooling them as identical-calibration trials. Preserve the
records and investigate separately. This observation does not disable the SDK's
normal conditional calibration refresh.

The hash is **not** a validity/checksum test, a snapshot of live RF coefficients,
a calibrated receiver-response measurement, or proof that nothing changed and
changed back between queries. Stage-start occurs after firmware startup, so it
cannot identify the exact time or cause of a boot-time refresh. Two equal hashes
do not eliminate gain, geometry, ambient RF or other confounders. Legacy stages
without telemetry remain unknown, not unchanged. Old campaign data are not
retroactively populated with observations that were never made.


## Firmware installation versus boot-time refresh

A changed fingerprint after reboot is not, by itself, corruption or a reason to
restore older calibration. The pinned SDK starts in partial-calibration mode and
can save updated PHY data when measurements make the stored data outdated, even
when its NVS CRC and internal PHY checksum are valid. This behavior was previously
[reproduced on the older v2 firmware](evidence/adaptive-evaluation/calibration-follow-up.md)
and observed in the [adaptive-v7 evaluation](evidence/v7-evaluation/README.md).

Keep two different checks separate:

1. **Installer preservation:** verify exact board identity and partition layout,
   retain a verified current backup in the same bootloader session as the write,
   and require every non-application region to be byte-identical immediately
   before and after an application-only flash, before application startup.
2. **Runtime provenance:** after startup, record a new calibration baseline and
   compare it around the actual tests. Investigate changes with logical-key and
   integrity checks, and do not pool trials across different calibration states.

A backup taken before an intervening application boot may legitimately no longer
be the current state. Preserve that backup, inspect the differences, and retain a
verified new current-state backup rather than forcing a stale comparison to pass.
Never erase NVS, roll back a calibration blob, disable persistence, or suppress
normal calibration merely to make two fingerprints equal. Valid storage checks
also do not establish calibrated sensitivity or unchanged RF performance.
