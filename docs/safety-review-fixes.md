# Independent review fixes

The combined source identifies as `esp32-pipeline-adaptive-q16-v6`, distinct from
previously measured v2, v3, v4 and intermediate v5 applications. No public release or tag is implied.
The detector and single-candidate default are unchanged from v4. Three-crop mode
remains experimental; its containment and copy-cost limitations still apply.

## Storage and updates

Original-ESP32 startup no longer erases NVS when initialization fails. It reports
that storage was preserved and stops before radio startup. Recovery requires a
private backup and an explicit migration plan, not an automatic erase. Host-only
fault injection covers both documented NVS incompatibility/full-storage errors,
a generic failure, and normal startup. No device NVS fault is deliberately induced.

The nRF updater reads its requested UF2 once and validates and writes the same
immutable bytes. Private owner-only session directories replace package-local
backup defaults. Existing unsafe destinations are rejected, not repaired.
Successful transfer followed by expected version/health/stopped status is labeled
`version_health_verified`, never an exact installed-image assertion. Any write or
flush error remains an uncertain update, even if an older same-version app answers.
See [updater recovery details](../nrf52840-transmitter/docs/recovery-and-update.md).

## Input, recording and analysis

- [SPEC parsing](spec-argument-validation.md) rejects malformed optional and extra
  tokens before starting acquisition, including requests with zero duration.
  The shared serial boundary rejects whole lines containing embedded NUL bytes.
- [Recording publication](host-recording-and-spectrum-safety.md) stages and syncs
  both files, then publishes without overwriting existing destinations. Handled
  data/metadata failures remove only the operation's own files. This is not a
  two-file power-loss transaction. SPC1 gain is retained in host frame telemetry.
- [RF analysis v2](offline-rf-analysis-v2.md) counts complete run manifests,
  including no-event runs. Missing retained-IQ analysis remains unknown. Current
  raw-control and gain-comparison metadata require final matching passed report rows. Custom source
  payload patterns are rejected rather than scored against the default pattern.
  Historical hashed analyzers and published results remain unchanged.
- [Source distributions](source-distribution.md) include explicit public resources.
  Installed nRF firmware builds explain the required source-checkout workflow.

## Validation boundaries

Regression tests use host mocks for destructive NVS error paths, mutable image
paths, interrupted writes and permission failures. These do not establish real
hardware failure recovery. Any bounded final-image hardware validation is recorded below
with its exact revision and image digest. It is not a soak, a new RF benchmark,
or evidence of improved packet recall.


## Intermediate v5 check

The first integration, runtime commit `b9ad40a9362b9442a87549148081bf9a5e39cd9c`,
passed 554 tests plus five subtests on Python 3.10 and 3.14 and in a fresh extracted
source distribution. Its isolated wheel imported 29 supported modules; packaged
module bytes matched source, with no private captures, recovery or vendor downloads.
The original-ESP32 application built with the pinned SDK, health telemetry disabled:
687,312 bytes, SHA-256 `d2c8229645a80dac549b7d5fce643087d21d16a2fc7db513672f7cbcf261861b`,
embedded build time `2026-11-12T02:40:52Z`.

This exact intermediate image passed a passive smoke: 210 calibration observations,
three raw and six retained CRC-valid buffers, four 250 ms pipeline runs, and a finite
spectrum run with 69 CRC-valid frames retaining gain telemetry. Two malformed finite
SPEC commands were rejected. Cleared heap was unchanged across hash queries and
pipeline runs. The stored calibration matched independent offline blob hashing and
was equal at pre-install/post-v5 snapshots. V2 was restored and verified, with three
raw captures, a finite pipeline run and final cleared heap 137,688/largest 73,728.
Application writes preserved the protected prefix; the transmitter stayed stopped.

Independent verification then found embedded NUL could truncate a command before
SPEC validation and raw-control metadata alone could precede a later run failure.
The v5 smoke did not cover those paths and does not establish their correction.
The final v6 source includes follow-up fixes and has a separate build identity.
