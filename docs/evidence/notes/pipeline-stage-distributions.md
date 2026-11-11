# Pipeline stage distributions

These measurements come from the compact fast-packing diagnostic image, not the final release. They describe one representative 2-second retained-event run at2440 MHz,16 MS/s,16,380 samples, gain40 and bandwidth setting12 MHz. Quantiles are inclusive histogram bounds, not fabricated point estimates.

The same fast-packing diagnostic image measured62.65–62.74% nominal local duty with profiling OFF and60.52–60.58% with profiling ON. Instrumentation has measurable observer overhead. Telemetry is emitted after the measured loop with explicit gaps and is included only in host time. Do not use these stage sums as an exact decomposition of the uninstrumented release.

| Stage | Observations | Mean µs | Min | Median bounds | p95 bounds | p99 bounds | Max |
|---|---:|---:|---:|---|---|---|---:|
| prepare | 0 | — | — | not observed | not observed | not observed | — |
| calibration_check | 1185 | 14.40 | 13 | 14–14 | 18–18 | 29–29 | 45 |
| tune_calibration | 0 | — | — | not observed | not observed | not observed | — |
| gain | 0 | — | — | not observed | not observed | not observed | — |
| rx_prepare | 0 | — | — | not observed | not observed | not observed | — |
| clear | 1185 | 77.77 | 77 | 78–78 | 81–81 | 81–81 | 93 |
| filter_apply | 1185 | 18.12 | 18 | 18–18 | 19–19 | 19–19 | 25 |
| register_setup | 1185 | 3.17 | 3 | 3–3 | 4–4 | 4–4 | 7 |
| trigger_to_done | 1185 | 1027.73 | 1027 | 1027–1032 | 1027–1032 | 1027–1032 | 1032 |
| poll_after_overlap | 1185 | 173.54 | 146 | 168–175 | 176–183 | 176–183 | 1020 |
| hardware_finalize | 1185 | 11.64 | 11 | 11–11 | 12–12 | 19–19 | 20 |
| register_restore | 1185 | 0.82 | 0 | 1–1 | 1–1 | 1–1 | 8 |
| filter_restore | 1185 | 4.33 | 4 | 4–4 | 5–5 | 5–5 | 12 |
| validate_or_fused_copy | 1185 | 476.80 | 467 | 467–471 | 467–471 | 840–847 | 1349 |
| acquire_total | 1185 | 1657.10 | 1645 | 1645–1663 | 1645–1663 | 1984–2047 | 2528 |
| energy | 1185 | 848.94 | 845 | 848–855 | 848–855 | 848–855 | 876 |
| decision_including_retention | 1185 | 8.95 | 1 | 1–1 | 2–2 | 13–13 | 875 |
| retention | 11 | 815.18 | 800 | 808–815 | 864–871 | 864–871 | 871 |
| separate_copy | 0 | — | — | not observed | not observed | not observed | — |
| yield | 37 | 788.86 | 93 | 1000–1006 | 1000–1006 | 1000–1006 | 1006 |
| iteration | 1185 | 1686.18 | 1650 | 1650–1663 | 1664–1727 | 2624–2659 | 2659 |
| timer_pair | 255 | 0.49 | 0 | 0–0 | 1–1 | 1–1 | 1 |
| histogram_update | 16893 | 0.84 | 0 | 1–1 | 1–1 | 1–1 | 25 |

Energy overlaps the hardware acquisition window. Decision/retention is nested within the fused validation/copy callback; acquisition and iteration span multiple stages. These rows must not be added indiscriminately. Zero observations for tuning or receiver preparation mean those phases did not execute inside this steady-state run, not that cold tuning is free. Initial setup/allocation is reported separately as `init_us`; this experiment does not provide a cold-start phase distribution.

The remaining critical path is dominated by complete-aperture validation plus copying (median467–471 µs here), full sentinel clearing (78 µs), calibration checks and receiver setup/restoration. The optimized energy kernel is already mostly hidden by the nominal1,023.75 µs RF window. The final focused packing comparison reduced same-image mean retention packing from2,642.8–2,644.6 µs to815.2–821.8 µs, with exact format equivalence and CRC checks. The actual observation count in the table is explicit; these are occasional strongest-event replacements, not every detected packet.

The original32-bit-bin diagnostic could not fit full retained data plus all23 histograms. The compact variant halves bin storage to22,080 bytes, keeps exact totals/extrema, and rejects histogram overflow rather than saturating silently. It is restricted to at most2 seconds, full-size buffers and16 MS/s when profiling is enabled. All8 compact OFF/ON trials passed retained and post-run raw CRC checks without overflow.

Yield cadences32/64/128 produced no useful improvement in the uninstrumented side of the earlier same-image test: all measured about61.75%. The proven32-capture cadence is retained. No watchdog setting was changed.

Evidence: `records/campaign/packing-v1.json`, `records/campaign/pipeline-compact-v1.json` and `records/campaign/pipeline-profile-v1.json`. The latter preserves18 completed trials and its final host-side memory-rejection handling error; the strict client has since been corrected and tested.
