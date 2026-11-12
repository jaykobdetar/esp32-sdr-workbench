# Offline RF analysis, version 2

Use these entry points for new analysis. They access files only, never radios:

```sh
python scripts/analyze_nrf_iq_v2.py /path/to/campaign
python scripts/summarize_nrf_screen_v2.py /path/to/screen
python scripts/summarize_nrf_retention_v2.py /path/to/trial/analysis-v2-TIMESTAMP/analysis.json
```

The screen directory contains one subdirectory per variant, each with its original
`*-run.json` manifests and an `analysis-*/analysis.json` file. The screen picks the
last lexically sorted analysis directory within each variant. Keep only the chosen
analysis there if comparing analyzer versions. A variant without analysis is still
reported, with retained-buffer outcomes marked unknown.

The retention analysis directory must be directly inside the trial directory that
contains the manifests. The summarizers accept historical analyzer records as well
as v2 records. V2 records carry an explicit `run_key`; historical records use the
complete leading numeric filename component, checked against the manifest index.
Duplicate, orphaned or condition-mismatched records are errors. These two
summarizers support the single-buffer screen/retention campaigns, not multi-crop
gain trials. Multi-crop inputs fail rather than double-count a run.

## Denominators and missing data

All passed detector run manifests contribute to candidate-rate and duty summaries,
including those with no retained IQ. Candidate rate is the mean of per-run rates,
not a pooled exposure-weighted rate. Runs must have successful receiver summaries,
nonnegative detection and retained-sample counts, and positive elapsed time.
Failed manifests are listed under `excluded_runs`; they are not treated as zeros.

A completed run with zero retained samples contributes zero to retained-frame
yield. This does **not** assert that no RF packet was transmitted or received.
A run that retained IQ but has no analyzer record is `missing_analysis`, not zero.
Its candidate rate remains available, but its group's frame-yield totals and
confidence interval are null. Retention pairs come from manifest pair keys, not
retained-buffer availability. Missing arms or missing analysis suppress paired
inference; an empty pair set produces null inference rather than a crash.

IQ-only metrics such as component clipping average only analyzed buffers. The
output separates run count, analyzed-buffer count, no-retention count, and missing
analysis count. Inspect those denominators before comparing results.

## Supported inputs and explicit limits

The v2 analyzer supports the original `controlled_source` metadata and passed
campaign manifests, and current `raw_source_control` / `gain_comparison` metadata
joined to passed runs in adjacent `results.json`. Raw controls require a passed
campaign report as well, matching capture filename, index, conditions, source
configuration, receiver identity/reference hash and recording frequency. Embedded
raw metadata is saved while the run is still running, so it alone cannot prove
that later source-stop and calibration checks passed. Conflicting legacy manifests
are rejected rather than allowed to bypass the current raw-report checks.
Gain inputs require that report because the metadata alone does not establish the
transmitter configuration. Multiple gain crops are analyzed separately, not treated
as independent experimental runs by the screen/retention summarizers.

Unknown metadata, missing metadata, no input files, unsupported datatype, malformed
IQ, missing transmitter configuration and incomplete gain runs fail explicitly.
The command writes no success output directory when input validation fails.

The frozen DSP decoder currently supports the default RFTX/sequence/deterministic
tail only. V2 **rejects custom `payload_hex` patterns** rather than reporting false
known-payload bit errors against the default tail. Custom-pattern decoding remains
future work. The historical `component_clip_fraction` definition remains
`abs(I)>=.999 or abs(Q)>=.999`; it is not the newer signed ADC endpoint metric.
Transport CRC and on-air packet CRC are distinct.

## Historical evidence

The original analyzer and summarizers remain byte-for-byte unchanged to preserve
`docs/rf-source-provenance.json`. Archived results, including the 48-buffer retention
trial and historical 550-record analysis, have not been regenerated or invalidated.
Those complete-retention datasets do not demonstrate the omitted-no-retention bug.
V2 introduces schema version 2 and new output names; it does not silently replace
published measurement claims. The analyzer records its own and the frozen DSP
source hashes. Regression tests are in `tests/test_nrf_analysis_v2.py`.
