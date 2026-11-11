# Diagnostic clients and source provenance

## Support decision

Keep the historical clients and source for interpretation of recorded experiments. Do not advertise them as supported commands of the optimized-v2 release. No diagnostic handler was wired into the release and no hardware was accessed as part of this publication.

- `sdr_research/profiling.py` expects `PROFINFO?` / `PROF1`, initialization, stage histograms and a finite summary. Corresponding historical headers `profile_command.h`, `profile_acquire.h` and `profile_stats.h` already remain in `firmware/main/targets/esp32/`. The release `receiver.c` includes `profile_acquire.h` (and through it `profile_stats.h`), so those static helpers are compiled but never called; it does not include `profile_command.h` and dispatches no `PROF1` command. Header presence is not runtime support. The include was left in place so the published source stays identical to the tree that was clean-built.
- `sdr_research/validate_copy.py` expects `VCTESTINFO?`, `VCTEST`, `VCTESTGET` and `VCTESTCLEAR`. Corresponding `validate_copy_test.h` and `validate_copy_runtime.h` already remain in that directory. `receiver.c` includes neither `validate_copy_test.h` nor a dispatch for it; `validate_copy_runtime.h` is included by `detector_pipeline.h` because the normal pipeline's fused validation/copy uses it. Normal pipeline fused validation/copy is distinct from the VCTEST benchmark.
- `sdr_research/pipeline_profile.py` is an adapter around DETPIPE1 for historical `PIPEPROFILE` / `PIPEYIELD` selectors and `PPROF1 INIT` / `PPROF1 STAGE` telemetry. The release does not implement these selectors or emit these records. PPROF1 is a telemetry prefix, not the acquisition command.

The missing PPROF1 implementation is now preserved in [diagnostic-sources/pipeline-profile](evidence/diagnostic-sources/pipeline-profile/) (INIT version 1) and [diagnostic-sources/pipeline-compact](evidence/diagnostic-sources/pipeline-compact/) (INIT version 2). Both archives contain complete original `pipeline_profile.h`, `detector_pipeline.h`, `receiver.c`, `profile_acquire.h`, `profile_stats.h` and `ascii_frame.h`. They show selection, instrumentation, telemetry serialization, allocation and overflow behavior in context. They are source excerpts from larger experimental trees, **not standalone buildable firmware packages** and not drop-in release replacements. Their other local/common headers and SDK dependencies are not all duplicated here.

The adapter accepts both telemetry versions and checks 23 stage identities/order, histogram intervals, selectors and summary consistency. Version 2 additionally checks histogram overflow signaling. Histogram p50/p95/p99 bounds are intervals, not exact percentile point estimates. Large original histogram allocations can fail before BEGIN; that is not successful profiling. Do not substitute ordinary DETPIPE1 output for missing telemetry or claim a profile was measured when allocation failed.

All three clients are retained for provenance and offline parser review; running them against this release is unsupported. Consult the actual firmware identity/capabilities and matching experimental sources before any future authorized hardware work. Nothing in these archives requests flashing, bypassing guard checks or changing the current receiver.

## Generator provenance

The original `generate_dispatcher.py` and its required source plus generated output are available in [diagnostic-sources/energy-candidates](evidence/diagnostic-sources/energy-candidates/). See [energy candidates](energy-candidates.md) for the reproduction command and relation to the release's renamed generated body. This is a complete small generation input/output set, not the full experiment or its RF fixtures.

[SOURCE_PROVENANCE.json](evidence/diagnostic-sources/SOURCE_PROVENANCE.json) records original relative paths, original/published SHA-256 digests and per-file sanitization. These archived files needed no personal-path/device-identifier substitutions. Original working copies remain unchanged. Existing source notices are preserved; the project source is GPL-3.0-or-later, with the license at `firmware/LICENSE`.

## Other-chip backends and ESP-DSP

Keep the historical upstream other-chip source for provenance. The public build catalog and top-level `firmware/CMakeLists.txt` restrict support to original ESP32. The broader list in `firmware/main/CMakeLists.txt` reflects inherited upstream dispatch, not a promise that S2/S3/C-series/H2/S31 builds work from this package. Missing files/dependencies or unverified builds on those targets are not release regressions being repaired here. No cross-chip test was performed for this publication.

Keep ESP-DSP as the existing vendored dependency, not a newly converted submodule. It is an actual dependency of the original-ESP32 spectrum build, not just an irrelevant other-chip artifact. Vendoring preserves the supplied dependency without adding a new fetch requirement. The pinned upstream revision is `a53a0756833c045311ea1d79a2badf495cdfde4c` from https://github.com/espressif/esp-dsp; the retained subset includes component metadata and modules, including module test includes required by builds. Upstream examples, media and unrelated tests are omitted. Its Apache-2.0 license remains in `firmware/components/esp-dsp/LICENSE`.

See [firmware source provenance](../firmware/SOURCE_PROVENANCE.md) for upstream ESP-SDR/SDK revisions and licensing. This evidence supplement adds historical sources/reports without expanding the supported target list or claiming fresh hardware validation.
