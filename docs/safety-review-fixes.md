# Independent review fixes

The combined source identifies as `esp32-pipeline-adaptive-q16-v5`, distinct from
previously measured v2, v3 and v4 applications. No public release or tag is implied.
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
- [Recording publication](host-recording-and-spectrum-safety.md) stages and syncs
  both files, then publishes without overwriting existing destinations. Handled
  data/metadata failures remove only the operation's own files. This is not a
  two-file power-loss transaction. SPC1 gain is retained in host frame telemetry.
- [RF analysis v2](offline-rf-analysis-v2.md) counts complete run manifests,
  including no-event runs. Missing retained-IQ analysis remains unknown. Current
  raw-control and gain-comparison metadata are accepted explicitly. Custom source
  payload patterns are rejected rather than scored against the default pattern.
  Historical hashed analyzers and published results remain unchanged.
- [Source distributions](source-distribution.md) include explicit public resources.
  Installed nRF firmware builds explain the required source-checkout workflow.

## Validation boundaries

Regression tests use host mocks for destructive NVS error paths, mutable image
paths, interrupted writes and permission failures. These do not establish real
hardware failure recovery. Any bounded v5 hardware validation is recorded below
with its exact revision and image digest. It is not a soak, a new RF benchmark,
or evidence of improved packet recall.
