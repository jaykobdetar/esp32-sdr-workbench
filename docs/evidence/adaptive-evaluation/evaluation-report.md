# Adaptive-v3 firmware evaluation

## Conclusion

The board completed extensive acquisition, retention and memory checks without a reported pipeline failure. The instrumented candidate passed a 30-minute soak and all tested boundary settings. However, **these measurements do not establish that released adaptive-v3 receives or retains more valid packets than optimized-v2**.

The stronger-source test recovered one complete known packet from v2 and none from either v3 retention configuration. That is too little packet evidence to establish either image's superiority. Three-crop retention also had lower observed sampling duty and more accumulated retention-copy time than single retention. Keep v2 as the known-good reference while improving packet-linked validation and separately validating any proposed release fix.

The known-good v2 application has been restored and its application digest verified. Final cleared heap is 137,688 bytes, with a 73,728-byte largest block. A final comparison also found that stored PHY calibration changed during the campaign. This adds an RF-comparison confounder and means NVS was not preserved byte for byte. The final recovery smoke passed: three raw captures and one 500 ms optimized-v2 pipeline run, all saved files transport-CRC-valid. The version exactly matches the initial reference; hardware AGC, initial selectors and source configuration were restored. The source is healthy and stopped. Nothing had been published at the evaluation checkpoint. This report is a later privacy-reviewed export; it does not describe any new hardware session.

“No failed runs” refers only to the completed acquisition/pipeline runs. The overall evaluation was **not issue-free**: it found the tie-retention defect, initial device-path preflight needed correction, higher-baud backup transfers failed before a slower recovery method succeeded, and byte-for-byte NVS preservation did not pass. These findings remain part of the result.

## What was tested

Final completed coverage:

- **925 pipeline runs**, all passed, with **1,568,533 captures processed**.
- **24 additional direct controlled-source captures**.
- **1,818 saved I/Q files:** 1,733 retained buffers and 85 direct/raw captures. Every saved file has a recorded valid transport CRC.
- **Ten successful passive-control runs retained no event.** These had zero detections and empty retained-file lists. They are not CRC failures.
- No reported pipeline capture errors or packing failures in the completed runs.

The firmware images were kept separate:

1. Optimized-v2 reference, SHA-256: `8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad`.
2. Original released adaptive-v3, SHA-256: `c5360d2b4e2ff5711d9b9ef43040b1290e5c31ec4de631a1f372fa5ecd0ce860`.
3. Separate instrumented, tie-eviction-fixed candidate, SHA-256: `2f5be585ae66126496080cb1fcd6e59424dbaa959f5078286338bdbebab8dffe`.

The tie fix exists in the instrumented candidate, not the unchanged released-v3 image. Instrumented timing and memory results must not be presented as measurements of the release binary.

| Test group | Pipeline runs | Additional raw captures | Main coverage |
|---|---:|---:|---|
| Weak-source matched tests | 96 | 0 | v2 before/after; released v3 single/three retention; four ON/OFF pairs per gain |
| Release smoke | 10 | 5 | Alternating single/three retention |
| Instrumented short | 10 | 5 | Initial acquisition, retention, heap and stack checks |
| Instrumented boundary matrix | 216 | 0 | Nine sizes × three rates × two retention modes × two kernel configurations × two copy options |
| Instrumented medium | 40 | 0 | Five-second runs, alternating retention |
| Instrumented controls | 48 | 48 | Frequency, bandwidth, gain and raw bit-depth controls |
| Instrumented soak | 360 | 0 | Five-second runs after an explicit fresh boot |
| Strong-source matched tests | 144 | 0 | Three image/retention groups; eight ON/OFF pairs per gain |
| Strong-source direct controls | 0 | 24 | Matched ON/OFF plus frequency-offset ON, separately for v2/v3 |
| Final recovered-v2 smoke | 1 | 3 | 500 ms optimized pipeline plus raw capture checks |

The boundary sample sizes were 256, 257, 2,048, 5,119, 5,120, 5,121, 8,192, 16,379 and 16,380. Rates were 16, 40 and 80 MS/s. Kernel0/reference and kernel3/optimized were paired configurations, with copy option0/1 and one/three retention.

Passive controls covered 2,402/2,440/2,480 MHz, 12/67 MHz bandwidth, manual gain0/40/79 or hardware AGC, both retention modes, and 8-/10-bit raw captures.

## Memory, continuity and soak

Only the separate instrumented, tie-fixed binary received this soak; the unmodified released-v3 image did not. The instrumented soak completed **360 runs, 1,082,671 captures and 720 retained buffers**. Its pipeline wall times sum to **1,800.599 seconds**, approximately 30 minutes. Host timestamps span about 33 minutes including between-run work. This is neither a one-hour soak nor continuous RF recording.

Across the completed instrumented stages:

- Lowest local DMA-capable heap reading: **30,448 bytes**.
- Lowest command-task lifetime free-stack watermark: **2,748 bytes**.
- Both exceed the predeclared screening gates of 8,192 heap bytes and 2,048 stack bytes.
- Every logged clear restores the stage's baseline heap, with no monitor error or invalid health record.
- Every recorded multi-crop run has distinct saved acquisition generations, with saved trigger/generation metadata matching its per-crop candidate.

Health IDs are consecutive within each logged stage. IDs restart between exclusive sessions, consistent with transport-triggered boots. The evidence supports continuity within individual stages, not uninterrupted operation across the whole campaign.

Heap minima conservatively sum per-region lows, which need not occur simultaneously. Stack measurements are the command task's lifetime watermark, not a per-run minimum or all-task proof. These are useful engineering checks, not guarantees against every memory fault or production workload.

## Controlled-source RF results

The known nRF source used 2 Mbps, 64-byte payloads, a 2,000 µs interval and 150 µs jitter at 2,440 MHz. Weak tests used −20 dBm configured transmit power; the extension used 0 dBm. These are transmitter settings, not calibrated received power. Physical placement, distance, orientation and stability were unmeasured and unverified, even where earlier records described the setup as “untouched.”

### Predeclared stronger-source packet endpoint

Before collecting the stronger-source data, the exploratory endpoint was frozen: **whether any retained buffer in an ON run contains the complete known address and payload with a verified over-air CRC**, reported separately by gain and image/retention. Multiple crops in one run do not increase its statistical sample size.

| Gain mode | v2 single retention | Released v3 single | Released v3 three crops |
|---|---:|---:|---:|
| Hardware AGC | **1/8 ON runs** | 0/8 | 0/8 |
| Manual40 | 0/8 | 0/8 | 0/8 |
| Manual60 | 0/8 | 0/8 | 0/8 |

Every corresponding OFF group was 0/8. Descriptive 95% Wilson intervals are 2.24–47.09% for 1/8 and 0–32.44% for 0/8. They illustrate the small sample size; temporal dependence and selection limit generalization.

The verified v2 AGC packet was sequence 521: all 64 known payload bytes and address `efcdab89c3` agree, and computed/received RF CRC both equal `4527`.

Neither image's direct raw controls produced a verified complete frame: each had four matched ON, four matched OFF and four offset ON captures. One v3 matched ON capture recovered all 64 payload bytes for sequence 56, but the address disagreed and computed/received CRC were `f9ac`/`63b7`. This is **complete-payload-only evidence**, not a verified full frame. No exact sync candidate occurred in the raw OFF or offset controls. Strong power outliers occurred in OFF/offset captures, reinforcing that power alone is not source identity.

No weak-source retained file yielded a verified complete packet under the documented conservative decoder. A negative search does not prove the transmitter was absent or that the receiver cannot receive it.

### Candidate activity is not packet reception

Mean strong-source ON−OFF candidate windows per local second, with exact two-sided paired sign-flip p-values:

| Gain | v2 single | v3 single | v3 three |
|---|---:|---:|---:|
| AGC | +232.03; p=.0078 | +232.58; p=.0078 | +235.08; p=.0078 |
| Manual40 | +278.65; p=.0078 | +294.15; p=.0078 | +286.56; p=.0078 |
| Manual60 | +174.76; p=.0078 | +26.57; p=.0469 | +14.62; p=.0703 |

These are within-stage exploratory energy contrasts. Tests assume exchangeability and are unadjusted for multiple comparisons. They do not establish a cross-image advantage or represent distinct packets.

Weak-source groups had only four temporal pairs per gain, whose minimum attainable two-sided sign-flip p is .125. The same v2 manual40 ON−OFF contrast changed from +5.51/s before testing to +71.59/s afterward. This change on the same reference image warns against treating sequential differences as firmware effects alone.

## Timing and selected waveform quality

Strong-source mean nominal sampling duty was **62.28% v2, 61.20% v3 single and 59.88% v3 three** using device-local wall time. Including host/session overhead, it was 43.24%, 42.36% and 41.89% respectively. These are sequential observations, not isolated causal overhead estimates.

Accumulated retention-copy elapsed time per strong-source run:

| Configuration | Min | Median | Mean | Max |
|---|---:|---:|---:|---:|
| v2 single | 2.386 ms | 8.360 ms | 8.291 ms | 19.861 ms |
| v3 single | 0.854 ms | 5.607 ms | 5.347 ms | 10.398 ms |
| v3 three | 7.938 ms | 24.797 ms | 25.304 ms | 56.415 ms |

These accumulated times depend on event/replacement activity; they are not exclusive CPU profiles or per-copy benchmarks. Acquisition timing already overlaps processing and must not be added to energy-compute time.

At 16 MS/s, a full 16,380-sample retained buffer spans 1.02375 ms; each 5,120-sample crop spans 0.320 ms. Summed apertures divided by wall time do not prove continuous coverage.

Signed ADC endpoint hits were counted using the actual 10-bit limits −512/+511, once per complex sample if either component reached a limit. In the early weak-source v3 three-crop series, manual60 endpoint rates were 12.22% ON and 12.31% OFF, versus zero in the single-retention manual60 series. The later strong-source manual60 three-crop files had zero endpoint hits. These selected-waveform changes are confounded by time, gain and selection; they cannot be attributed solely to cropping, treated as whole-run clipping rates, or used alone to identify the transmitter.

## Calibration preservation finding

The final read-only preservation investigation localized the non-application difference to NVS, the device's persistent settings/calibration storage. The bootloader area, partition table and separate PHY-initialization region matched their originals. Recorded NVS page, written-entry and calibration-blob integrity checks were valid both before and afterward. Namespaces and the other logical NVS values were unchanged.

The changed logical value was the PHY calibration blob: **173 of its 1,904 bytes differed**. No direct NVS write was performed, and calibration was not rolled back. The SDK contains an automatic refresh/save path when calibration loading fails or PHY reports checksum/outdated data. Firmware SDK logs were suppressed, so the actual trigger and timing are unproven. Automatic refresh is a plausible mechanism, not an established explanation of this specific change.

This is material to RF interpretation: the comparison cannot assume identical calibration across sequential stages. Many resets and both released images occurred during the campaign; the change cannot be attributed uniquely to v3. It is not appropriate to claim byte-for-byte NVS preservation or attribute every RF difference solely to the detector algorithm. The v2 application verification remains a separate, successful check. The subsequent recovered-v2 smoke passed. This confirms recovered application operation, not restoration of the original calibration bytes.

## Independent source audit and confirmed retention defect

The offline audit exercised production energy, crop and packing code against independent calculations: 16,381 sample lengths for each check, 524,288 Q16 transitions, all 16,125 legal three-crop allocation lengths, 84 boundary/kernel/copy combinations and 100 acquisition-failure combinations. The integrated fixture also covered all 13 allocation-failure and 13 address-rejection positions in the full retention layout.

Property and integrated sweeps completed at O0 and O2 without ASan/UBSan diagnostics. LeakSanitizer initially failed under the environment's ptrace limitation, so leak detection was disabled for successful runs. **LeakSanitizer did not pass**; outstanding allocation counts were checked separately. These are host software tests, not hardware measurements.

A real **tie-eviction correctness bug** was reproduced: replacement evicted the first minimum-score slot rather than the newest equally weak generation. For example, generations 17/18/19 at score 100 followed by generation 20 at score 200 could discard generation 17, violating the preference to keep earlier captures. **773 of 4,096 six-capture score streams** disagreed with stable score/generation ordering. The strongest score and multiset of top scores remained correct; this was a retention-identity defect, not demonstrated memory corruption.

The isolated fix evicts the **greatest generation among equal lowest scores**, preserving earlier captures even after replacements reorder slots. Incoming equal-score candidates still do not replace existing ones. The equivalent fixed model agreed with all 4,096 reference streams. A regression fixture covers selection, packed retrieval, strongest-slot tracking and timestamps. At the original follow-up checkpoint the C regression had not yet run; the subsequent instrumented build and final host suite are later evidence. The original released-v3 binary remains unchanged.

A synthetic crop sweep tested all 1,464 aligned placements of a 4,672-sample burst inside a 16,380-sample capture. A selected 5,120-sample crop fully contained the burst in **57/1,464 placements (3.893%)** with uniform energy, first-block emphasis or last-block emphasis, versus **1,464/1,464** with high-energy center-block emphasis. This is a synthetic alignment/energy-shape test, **not RF packet recall, not actual transmitter modulation and not sensitivity evidence**. A 320 µs crop can exceed a 292 µs frame's duration yet truncate it. At 40/80 MS/s the crop is already shorter than that frame regardless of alignment.

## Assessment of the six raised concerns

1. **Legacy background policy is not runtime selectable: confirmed capability limitation.** Production policy is fixed at 2; PIPEKERNEL selects an energy implementation, not background policy. The Python reference supports policy 1, but same-image on-device A/B is unavailable. Adding a selector would require policy telemetry and lifecycle/reset tests. None was added.

2. **No tag marking measured source: locally confirmed provenance improvement.** The inspected public checkout had no tags; remote tags were not inventoried. A named tag improves discoverability but does not replace immutable source/binary hashes and manifests. No tag was created or published.

3. **Stack growth: confirmed, but static buffers are not automatically safer.** Formatting arrays grew from 1,400 bytes to 900+3,000=3,900 bytes. Retained Xtensa command-function frames were **4,432 bytes in v3 versus 1,792 bytes in historical v2**; the configured main stack is 8,192 bytes. Frame size excludes callers, nested library calls and interrupts, and is not a runtime high-water measurement. Static arrays would permanently reserve roughly 3,900 RAM bytes, potentially reducing heap headroom and adding shared-buffer/reentrancy constraints. The separate instrumented board measurements above provide runtime screening evidence. No array relocation was applied.

4. **“Two 64-bit divisions every capture; shifts do the same job”: contradicted by compiler output.** Two division-helper call sites occur on different paths: warmup averaging and score calculation. Constant /64 and /256 already compile to shifts. Arbitrary Q16 score denominators and general warmup counts cannot normally be replaced with shifts; negative captures can skip score division. No new microsecond cost was measured by the audit.

5. **Three-crop selection rescans with the baseline kernel: confirmed performance opportunity.** A qualifying retention invokes block energy scans over 16,320 samples at full length, outside the overlap callback. An archived full-capture baseline benchmark measured 301,589–301,590 cycles, about **1.257 ms at 240 MHz**. This is historical context, **not a newly measured block-by-block crop-rescan cost**. Increasing qualifying scores can cause repeated replacements, so retention need not be rare. Reusing the first peak-block index from the initial pass could avoid rescanning, but requires exact tie/offset-equivalence and performance tests. No such optimization was applied.

6. **PIPEKEEP remains armed after invalid DETPIPE1: confirmed, consistent with the current contract.** It applies to the next *valid* command. Argument validation fails before consuming it; allocation failure after validation consumes it. Consuming it on every attempted command would be an intentional protocol/UX change, not a correction of the documented semantics. No semantics change was made.

## Software verification and remaining limits

The final host suite passed **445 tests plus five subtests**. Ruff check/format and Git whitespace checks were clean. These are software checks, not extra RF observations. Firmware C did not change after the frozen instrumented build; subsequent changes were test formatting.

Remaining limitations include sequential, nonrandomized firmware phases; sparse packet recovery; unmeasured geometry/stability; changed stored PHY calibration with unknown timing; short, selected capture apertures; no calibrated sensitivity or packet-recall measurement; no all-task stack coverage; and no thermal/power endurance characterization. The independent tie-selection fix still needs an explicitly versioned release candidate and its own release-image validation.

A defensible next step is packet-linked testing with repeatable geometry, stronger direct-source positive controls and interleaved image/retention trials. The existing data justify operational confidence within the tested matrix, not a general reception-performance claim.

## Public evidence and source

See [public evidence](README.md) for the machine-readable records, privacy exclusions, original versus public hashes and offline checks. Observed decoded payload/address byte strings are omitted, including partial candidates; the known test-source identity and expected payload pattern are retained. The committed tie fix changes source, not the immutable released-v3 binary. No new release tag or firmware installation is created by publication.
