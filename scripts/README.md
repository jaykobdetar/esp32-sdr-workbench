# Scripts

Run everything from the repository root. Only the campaign scripts and the multi-receiver runner open serial devices; none of them flashes firmware.

## Run the viewer

| Script | Purpose |
|---|---|
| `launch.sh` | Start the viewer from a source checkout. |

## Check the published evidence (offline, standard library only)

| Script | Purpose |
|---|---|
| `verify_evidence.py` | Recompute the benchmark, soak and GUI headline numbers from `docs/evidence/`. |
| `verify_nrf_evidence.py` | Recompute the controlled-source totals, duty and rate comparisons and known-packet CRCs from `docs/evidence/nrf-validation/`. |

## Analyse recordings you hold locally (offline)

These need the original recordings or campaign reports, which are not published.

| Script | Purpose |
|---|---|
| `count_sigmf_endpoints.py` | Count ADC endpoint codes in one SigMF recording. |
| `analyze_nrf_iq.py` | Diagnose recordings and search them for the known Nordic test frames. |
| `compare_nrf_abab.py` | Run-level historical versus optimized comparison of an ABAB campaign. |
| `summarize_nrf_screen.py` | Summarise a parameter-screen campaign. |
| `summarize_nrf_retention.py` | Paired summary of a retention-policy trial. |
| `evaluate_nrf_retention.py` | Offline proxy for retention policies on saved raw buffers; not a firmware replay. |

## Run a controlled-source campaign (opens hardware)

These drive an ESP32 receiver and the [nRF52840 transmitter](../nrf52840-transmitter/README.md) through explicitly named ports. Read the [campaign guide](../docs/nrf-controlled-source-campaign.md) first.

| Script | Purpose |
|---|---|
| `nrf_rf_campaign.py` | Shared campaign engine and the basic finite ON/OFF experiment. |
| `nrf_raw_scope.py` | Randomised raw-I/Q contrast sweep, for example across gain indices. |
| `nrf_receiver_compare.py` | Historical DET1 versus optimized pipeline on one installed image. |
| `nrf_parameter_screen.py` | One-factor screen of source and receiver settings. |
| `nrf_retention_campaign.py` | Counterbalanced strongest versus reservoir retention trial; needs the [experimental image](../experiments/retention/README.md). |
| `multi_receiver_capture.py` | Run a finite JSON receiver plan; dry-run unless `--run` is given. See [multi-receiver preparation](../docs/multi-receiver-preparation.md). |

## Why some of these files are not auto-formatted

The campaign and analysis scripts above, `sdr_research/multireceiver.py` and three of their tests have their exact bytes recorded in [`docs/rf-source-provenance.json`](../docs/rf-source-provenance.json). Most are byte-identical to the code that produced the published measurements. They are excluded from ruff in `pyproject.toml`, and `tests/test_source_provenance.py` fails if one changes. To edit one deliberately, update its `public_sha256` in the provenance file and set `byte_identical` to `false` in the same change.
