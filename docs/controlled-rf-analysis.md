# Controlled RF IQ analysis

**Publication scope:** This report describes the completed local experiment. Paths under `records/`, firmware artifact directories and recovery directories below are archival provenance labels, not public download links. The [public evidence](evidence/nrf-validation/README.md) contains scrubbed numeric exports and known test-packet bytes; raw I/Q, flash backups and binaries are withheld. This publication did not repeat hardware measurements or change the devices. Historical test counts below are not the current public-checkout test count.

## New analysis versus historical reproduction

For new work use `scripts/analyze_nrf_iq_v2.py` and the v2 screen/retention
summaries described in [offline RF analysis v2](offline-rf-analysis-v2.md).
They validate supported current metadata, include complete no-event run manifests
in denominators, keep missing analysis unknown, and reject custom payload patterns.
The original tools below are frozen to reproduce archived results. They retain
legacy metadata handling and default-payload assumptions; the old screen/retention
summaries may exclude runs without retained IQ. Do not use them for new inference.

## Reproduce historical inputs (offline only)

From the repository root, run `.venv/bin/python scripts/analyze_nrf_iq.py records/nrf-first` using the matching historical input dataset. Each invocation creates a new timestamped analysis directory, never overwrites prior results, and reads only existing SigMF IQ/metadata and run JSON. Outputs are `analysis.json` (metrics, hypotheses, SHA-256 input hashes) and `diagnostics.svg` (per-record time-domain power, Welch spectrum, phase discriminator). Numpy is the only dependency. Campaigns still running produce a snapshot rather than a final dataset. Do not interpret missing files as failures.

## Signal contract and limitations

Firmware source `nrf52840-transmitter/firmware/main.c` configures proprietary Nordic 1/2 Mbps, not BLE. PCNF0 is LENGTH8, PCNF1 BALEN4 with little-endian and whitening disabled, BASE0 0x89abcdef, PREFIX0 0xc3. CRC length is two bytes, polynomial 0x11021, initialization 0xffff. Payload is `RFTX`, four-byte little-endian attempted-packet sequence, then byte `(k + sequence) mod 256` at payload offset k. Decoder uses actual per-run mode and payload length. The source defaults are 1 Mbps/32 bytes, while campaigns configure 2 Mbps/64 or 128 bytes; do not substitute source defaults for logged configuration.

Each retained IQ buffer has 16,380 complex float32 little-endian samples at 16 MS/s: only 1.02375 ms nominal aperture. These are discontinuous captures, not a continuous record of the entire run. Run-level transmitter completed counts cover a much longer interval. Energy windows, firmware detections and retained waveform counts therefore cannot be divided by transmitter count to obtain packet recall. Optimized and baseline retained buffers are selected by the device rather than random samples; their energy is selection-biased. The `retained_crc_valid` field validates transfer integrity, **not the Nordic packet CRC**.

The decoder integrates differential phase over each symbol, searches every integer sample timing phase, both polarities, and CFO decision thresholds from -2 to +2 MHz in 125 kHz increments. LENGTH+RFTX correlation is only a candidate locator. Full recovery is claimed only if all known payload bytes match, including sequence and counter-derived suffix. It reports partial matching evidence separately. For complete packets with available leading/trailing bits, it verifies the recovered five-byte address and RF CRC. The CRC recurrence shifts MSB-first with polynomial 0x1021 and init 0xffff, consuming the actual LSB-first on-air bits of address, length and payload because SKIPADDR=0. The trailing CRC is read MSB-first. This model matches all eight complete packets in the gain sweep, spanning seven independent sequence values. A 1.5 MHz low-pass/DC-removal exploratory pass did not restore the corrupted 128-byte suffixes described below. Unknown timing drift, interference, receiver distortion, filtering and incomplete captures can all prevent decode; negative results do not establish absence of the transmitter.

Synthetic smoke tests generate noisy Gaussian-smoothed FSK for both 1 and 2 Mbps, recover the entire known payload and reject independent noise. They test software consistency, not Nordic over-the-air compatibility, receiver calibration or real RF sensitivity.

## Completed first campaign: -20 dBm, 64 bytes

Snapshot: `records/nrf-first/analysis-20261111T205046330540Z/analysis.json`, all 48 observations.

At receiver 2440 MHz, ON minus OFF mean retained power was -4.70 dB for raw, -2.06 dB baseline, and -0.65 dB optimized. Firmware baseline candidate counts ON [114,86,91,81] versus OFF [85,79,83,66]; optimized ON [198,175,74,185] versus OFF [255,90,111,181]. There is no clear clean ON/OFF separation and no full known payload recovered.

At the 2470 MHz offset control, raw ON/OFF power difference was +11.66 dB, while selected baseline and optimized buffers gave +0.55 and -0.34 dB. This is a warning against attribution based solely on a small raw-power sample: the 30 MHz offset is outside the nominal 12 MHz receiver bandwidth, and environmental signals and selection effects remain uncontrolled. No full payload recovered in any of these 48 buffers.

## Stronger source: 0 dBm, 128 bytes

Interim snapshot: `records/nrf-strong/analysis-20261111T205136318202Z/analysis.json`.

The first 2440 MHz selected buffers show materially more ON candidate activity: baseline ON 446/404 versus OFF 32/36; optimized ON 932/945 versus OFF 106/183. This is promising ON/OFF energy contrast but not packet recall or packet authentication.

More specifically, raw phase demodulation found:

- `0014-baseline-on`: exact length+RFTX and sequence 631 at sample 12921. All 424 available payload bits match the known payload, but the recording ends before the expected 1024 payload bits. This is partial transmitter-linked evidence, **not a decoded complete packet**.
- `0015-optimized-on`: exact length+RFTX, sequence 198 at sample 274. First 91 payload bytes match exactly; later bytes are corrupted (123 total payload bit errors under the best saved unfiltered hypothesis).
- `0016-optimized-on`: exact length+RFTX, sequence 603 at sample 5176. First 87 bytes match exactly; later bytes contain errors (112 total payload bit errors under the best saved unfiltered hypothesis).

These long matches substantiate source-linked modulation in specific captures. No full 128-byte known payload or valid RF CRC has yet been recovered in this snapshot. Partial candidates must not be relabeled as valid packets.

## Recommended next measurement

Keep 0 dBm source for the controlled experiment, use shorter 64-byte packets and introduce interval jitter to avoid repeated relative timing. Short packets leave room in the 1.024 ms aperture for a complete packet and CRC. A 252-byte packet at 2 Mbps has an entire frame longer than this buffer, so it can help energy duty-cycle diagnosis but cannot provide complete-frame validation in a single retained buffer. Separate packet-identity tests from energy throughput tests. Hold geometry and receiver settings fixed for paired controls; collect sufficient OFF runs, log actual TX configuration, and preserve raw IQ. Tune only one factor at a time and describe results as receiver behavior rather than calibrated sensitivity.


## Completed gain sweep: full RF packets verified

Artifact: `records/nrf-gain-scope/analysis-20261111T205356035909Z/analysis.json`; three-panel representative figure `representative.svg` in that directory shows gain60 OFF, gain60 ON, and gain80 ON. The full `diagnostics.svg` shows every retained buffer. Both expected and observed payload hex, exact sample offset, polarity, CFO threshold, recovered address and computed/received CRC are preserved in JSON, alongside input SHA-256 hashes.

Firmware0.2.0, 2Mbps, 64-byte known payload, 0dBm, interval1000us, jitter150us, fixed geometry. Six raw ON and six raw OFF buffers per gain. Average ON/OFF power ratios: gain20 +0.57dB, gain40 +8.36dB, gain60 +11.44dB, gain80 +13.09dB. Gain80 has up to10.04% component clipping by the normalized near-full-scale test and is not the preferred linear measurement setting. Gain60 had zero such clipping in these captures.

Complete address+payload+CRC verified captures:

| Gain | File index | Sequence | Computed = received RF CRC |
|---|---|---|---|
|40|0015|107|212d|
|40|0017|108|097f|
|40|0022|99|614f|
|60|0025|107|212d|
|60|0026|105|0421|
|60|0030|101|e573|
|60|0035|92|5c79|
|80|0039|85|3fe7|

All recover the actual expected address efcdab89c3 and all64 payload bytes exactly. No exact length+RFTX sync candidate or complete payload occurred in any of the24 OFF buffers. Complete packet-containing buffer counts were0/6,3/6,4/6,1/6 ON for gains20,40,60,80 respectively; these are **capture-level observations, not packet recall**. Some additional ON captures contained correct but truncated partial payloads. The source is therefore directly attributable in eight captures, not merely inferred from ON/OFF energy. Gain60 is a defensible next comparison setting; this does not establish an optimum across geometries or calibrated sensitivity.

The completed 56-record stronger-source snapshot is `records/nrf-strong/analysis-20261111T205303057265Z/analysis.json`; only the three same ON buffers yield exact header candidates, with no full128-byte payload in any record and no exact-header candidate in OFF or offset buffers. Timing/CFO hypotheses can trade prefix length against total error count: the91-byte prefix in0015 occurs with start273/CFO125kHz and149 total errors, while the minimum123-error hypothesis has a shorter exact prefix. Thus minimum total errors and longest correct prefix are distinct diagnostics; neither is packet acceptance.


## Completed controlled gain60 campaign (80 observations)

Final artifact: `records/nrf-controlled-g60/analysis-20261111T205711389919Z/analysis.json`. This snapshot uses the final analyzer with script SHA-256 provenance and gain retrieved from nested controlled-source settings where needed. Representative and full three-panel SVGs are alongside the JSON.

At2440MHz, all4 raw ON buffers contain a complete address+64-byte payload+correct RF CRC (sequence55 after each restarted TX run), versus0/4 OFF. Raw ON mean power exceeds OFF by22.56dB. Selected baseline ON has1/8 CRC-valid retained buffers (file0022, sequence936); optimized ON has0/8. Neither mode has a full packet in any OFF buffer. Across the entire offset2470MHz group there is no exact length+RFTX candidate or complete payload. In fact there are no exact header candidates in any OFF or offset buffer across this80-record campaign.

Mean firmware candidate rates (detections divided by each run's local wall seconds, then averaged):

| RX frequency | Mode | ON candidates/s | OFF candidates/s |
|---|---|---|---|
|2440MHz|baseline|196.73|73.55|
|2440MHz|optimized|437.74|168.99|
|2470MHz|baseline|51.46|50.33|
|2470MHz|optimized|144.00|175.78|

The center ON excess is123.18 candidates/s baseline and268.75 optimized. Offset controls do not exhibit that same positive contrast. These rates substantiate source-dependent energy activity, not distinct packets, false-alarm probabilities or packet recall.

For center ON runs, mean nominal RF sampling duty is29.68% baseline versus62.33% optimized using device local wall time. Including host command/session overhead reduces the corresponding figures to24.49% and51.08%. These figures use summed nominal N/fs capture apertures; they do not prove uninterrupted timing, symbol-valid coverage or end-to-end packet opportunity. The analyzer retains the underlying receiver summaries for independent denominator checks.

Selected OFF buffers have *greater* mean IQ power than selected ON buffers at center: ON minus OFF is-3.20dB baseline and-2.59dB optimized. The selection rule evidently does not guarantee retaining the known transmitter's packet. This explains why selected-buffer CRC yield is not a valid comparison of detector recall: the optimized run can see more candidate activity yet retain only a stronger unrelated waveform. Source-triggered retention or multiple saved candidate buffers would be needed to compare packet identities without this severe selection bottleneck.


## Actual-image ABAB comparison (32 runs)

Independent image phases historical-1, optimized-1, historical-2, optimized-2 each contain four randomized ON/OFF pairs. Source firmware0.2.1,64B/2Mbps,0dBm,interval2000us,jitter150us,gain60,2440MHz. These are genuinely separate flashed images, unlike baseline-vs-optimized kernels in one image. Statistics artifact: `records/nrf-abab/comparison-20261111T210109616756Z.json`; reproduce with `.venv/bin/python scripts/compare_nrf_abab.py records/nrf-abab`.

| Image phase | ON candidates/s | OFF candidates/s | Paired ON−OFF mean (bootstrap95%) | Local / host nominal RF duty ON |
|---|---|---|---|---|
|historical-1|217.26|82.67|134.60 (116.19, 149.08)|32.11% / 26.50%|
|historical-2|210.65|79.46|131.19 (118.96, 152.06)|32.11% / 26.50%|
|optimized-1|438.30|201.93|236.37 (222.36, 250.37)|62.35% / 51.10%|
|optimized-2|427.05|192.98|234.08 (219.36, 248.79)|62.31% / 51.08%|

Optimized minus historical ON/OFF excess was101.77 candidates/s in cycle1 (bootstrap95%80.90–125.00) and102.89 in cycle2 (78.29–124.24). Intervals resample independent ON/OFF pairs within each phase,20,000 deterministic seeded bootstrap samples; they do not treat IQ samples as replicates. With only four pairs per phase these percentile intervals can substantially under-cover. ABAB has only two temporal repetitions and is confounded with changing ambient activity: these are descriptive uncertainty intervals, not robust causal guarantees.

Complete verified retained frames: historical1 0/4 ON; historical2 1/4 ON (file0001,seq996). Optimized1 retains one complete known64-byte payload (file0007,seq656) with address truncated at the left edge, so full-frame CRC validation is unavailable. Optimized2 retains one complete payload (file0002,seq616) with trailingCRC truncated at the right edge. Thus optimized full-frame validation0/8 ON, historical1/8 ON, while complete known-payload counts are optimized2/8 versus historical1/8. Missing boundaries are not CRC failures. No full payload or exact-header candidate occurs in the16 OFF retained buffers. These tiny, selected-buffer yields do not estimate detector packet recall.

### Retention-source inspection and offline policy check

The historical artifact source archive `firmware-experiment/artifacts-v2/source-v2.tar.gz` (`main/targets/esp32/detector_experiment.h`) and optimized `firmware-optimized-v2/main/targets/esp32/detector_pipeline.h` both retain the highest **peak/background ratio**, not highest mean power. Background warms for16 captures and subsequently updates via63/64 EWMA only on non-events. Energy removes each64-sample complex block mean.

A reproducible offline proxy is in `scripts/evaluate_nrf_retention.py`; result `records/nrf-gain-scope/analysis-20261111T205650264285Z/retention-proxy-20261111T205937811458Z.json`. Across six independent gain60 raw ON buffers, strongest DC-removed block peak selects a CRC-valid buffer; uniform reservoir has expected4/6 valid yield. A preliminary boundary rule selects three eligible buffers, all valid, but rejects one other valid buffer. This does not show reservoir or boundary selection superior. The proxy uses a pooled OFF floor and independently acquired buffers, not the unavailable rejected-event stream or exact dynamic firmware score.

Before endorsing a policy change, use held-out real event streams or controlled counterbalanced policy trials, keeping byte budget/source geometry/settings fixed. Compare strongest-ratio, seeded uniform reservoir, and soft boundary preference. Record every candidate score and retention reason; count full address+payload+CRC outcomes separately from truncated payloads. Use decoder labels only for evaluation, never selection. Account for retention-copy overhead and randomization seed. Original strongest-ratio behavior should remain the default unless actual measurements establish improvement.


## Completed17-variant one-factor screen (238 observations)

Summary artifact: `records/nrf-screen/summary-20261111T210832681388Z.json`. Reproduce with `.venv/bin/python scripts/summarize_nrf_screen.py records/nrf-screen`; each variant has its own immutable timestamped IQ analysis JSON/SVG. There are three ON/OFF detector pairs per mode and one raw pair per variant, with1-second detector runs. Conditions are sequential, not randomized across variants, and ambient-time confounding remains. This is exploratory screening, not sensitivity certification, a factorial experiment, or calibrated received-power measurement.

Each table row shows baseline/optimized ON-minus-OFF candidate rates and ON nominal local/whole-host-session RF duty. CRC yield is the number of retained ON buffers with complete address+payload+RF CRC, shown baseline/optimized/raw with denominators3/3/1. All119 OFF buffers have zero exact header candidates and zero full-frame validations.

| Variant | Candidate excess/s B / O | Local duty% B / O | Host duty% B / O | CRC buffers B / O / raw |
|---|---|---|---|---|
|bandwidth24|63.6 / 192.0|29.55 / 61.82|20.76 / 42.94|0 / 0 / 0|
|buffer8192|91.6 / 250.1|19.99 / 45.32|16.43 / 36.71|0 / 0 / 0|
|burst5|57.6 / 69.5|29.55 / 61.21|20.76 / 42.52|0 / 0 / 0|
|hopping|29.7 / 82.5|29.57 / 62.01|20.78 / 43.07|0 / 0 / 0|
|interval10ms|25.0 / 51.9|29.59 / 61.98|20.79 / 43.06|0 / 1 / 0|
|mode1|141.5 / 311.4|29.71 / 62.09|20.88 / 43.13|0 / 0 / 0|
|payload128|141.1 / 270.1|29.55 / 61.96|20.76 / 43.03|0 / 0 / 0|
|payload32|97.2 / 231.4|29.58 / 61.88|20.78 / 42.98|1 / 0 / 0|
|payload8|95.8 / 160.4|29.61 / 61.93|20.81 / 43.01|1 / 0 / 0|
|power-minus20|-6.0 / 14.1|29.57 / 62.06|20.78 / 43.10|0 / 0 / 0|
|power-minus40|-2.7 / -0.7|29.55 / 62.46|20.76 / 43.38|0 / 0 / 0|
|power-minus8|112.3 / 262.6|29.62 / 62.29|20.82 / 43.27|0 / 0 / 0|
|rate40|75.3 / 177.4|14.38 / 27.45|10.11 / 19.06|0 / 0 / 0|
|rate80|65.8 / 110.9|7.78 / 13.81|5.47 / 9.59|0 / 0 / 0|
|reference|131.1 / 252.5|29.59 / 61.96|20.80 / 43.04|0 / 1 / 1|
|threshold2|98.7 / 237.9|29.59 / 61.90|20.80 / 43.00|0 / 0 / 0|
|threshold8|91.8 / 214.5|29.67 / 62.19|20.86 / 43.21|0 / 0 / 1|

Six complete source-validated captures were recovered: reference optimized and raw, payload8 baseline, payload32 baseline, interval10ms optimized, and threshold8 raw. Observed and expected payload hex, sample indices, address and CRC values are in each variant analysis. No other complete known payloads were recovered in this screen. Zero recoveries in three selected ON buffers must not be interpreted as zero packet reception.

### Boundaries and interpretation

- Eight-byte payloads contain onlyRFTX and an unconstrained sequence number, with no deterministic incrementing suffix. A matching header/sequence alone is consequently weaker evidence than a long known payload. The payload8 result above additionally verifies the actual address and RF CRC; do not promote a header-only8-byte candidate to source validation.
- At1Mbps the64-byte frame lasts about584us rather than292us at2Mbps. It fits the1.02375ms aperture, but with much less placement margin. No full frame was recovered; the larger candidate excess is consistent with greater airtime, not evidence of improved packet decoding. Synthetic1Mbps decoding passes, but synthetic tests do not certify RF performance.
- The128-byte2Mbps frame is about548us and also fits nominally, while being more vulnerable to boundary cuts and corruption. No full128-byte packet recovered in this screen.
- The8192-sample16MS/s aperture is512us, so a292us64-byte frame fits but has only220us placement margin. Its nominal duty is lower despite more captures potentially fitting per second.
- At40MS/s,16,380 samples span409.5us, leaving only117.5us margin around a292us frame. At80MS/s the aperture is204.75us: even LENGTH+64-byte payload alone requires260us, so a complete payload/frame is impossible in one retained buffer. Zero complete decodes at80MS/s is a structural aperture limit, not a sensitivity finding. Header/partial scanning still runs on short buffers.
- Hopping cycles2420/2440/2460MHz while the receiver stays2440MHz; only the center-frequency subset is expected in-band. The transmitter completion count covers all hops, and firmware status is not an RF-arrival trace, so it cannot be a denominator for fixed-channel recall.
- Burst5 uses five packets followed by20ms gap; interval10ms similarly reduces packet opportunities. Compare energy rates under their actual traffic schedule rather than assuming the reference packet rate.
- Lowering the threshold increases OFF activity as well as ON activity; candidate excess and complete source validation must remain separate from detection totals. All variants share the same selection bottleneck.

Across all119 ON bracketing intervals there were zero increases in transmitter missed_slots and no timing_saturated status. Logged maximum launch lateness across the runs was1201–1259us, including startup and all elapsed run activity rather than only the short retained aperture. Thus planned scheduling is not perfectly punctual even when no slots are counted missed. Timing/counter deltas for each ON run are preserved in the summary; they do not timestamp individual RF arrivals.

The repeatable center/source contrast disappears near-40dBm and is weak at-20dBm in this geometry, while-8dBm still produces strong candidate excess. Those are transmitter-setting observations, not receiver sensitivity in dBm: antenna coupling, received power and ambient interference are uncalibrated, and the conditions ran at different times.


## Controlled strongest-versus-reservoir retention trial (48 runs)

Final refined IQ artifact: `records/nrf-retention/analysis-20261111T211056187993Z/analysis.json`; paired summary: `records/nrf-retention/analysis-20261111T211056187993Z/retention-summary-20261111T211124035441Z.json`. Reproduce with `.venv/bin/python scripts/analyze_nrf_iq.py records/nrf-retention --cfo-step-hz 25000`, then `scripts/summarize_nrf_retention.py` on its analysis JSON. This final pass applies the same25kHz CFO threshold spacing to all48 buffers. The earlier125kHz search missed one otherwise valid strongest packet; its counts are superseded here. No raw data or earlier analyses were overwritten.

Twelve counterbalanced repetitions include strongest/reservoir crossed with TX ON/OFF, same source64B/2Mbps/0dBm/2ms+jitter150us andgain60. Twelve distinct seeds52840 through1204859 are paired across policies, rather than one seed reused for the entire experiment. Metadata reports retention_policy0 for strongest and1 for reservoir on every run; selected_candidate_index lies within1..detections, errors=0, pack_failed=0, and UART retention CRC valid throughout. Reservoir replacement counts range3–16; strongest4–41. These replacement counts are buffer copies, not packet detections.

| Policy/state | CRC-valid retained buffers | Complete payload buffers | Candidate rate/s | Local RF duty% | Host RF duty% | Mean retention-copy time ms |
|---|---|---|---|---|---|---|
|strongest ON|2/12|2/12|419.20|61.49|50.36|20.24|
|strongest OFF|0/12|0/12|163.96|61.63|50.48|10.96|
|reservoir ON|3/12|3/12|414.11|61.72|50.55|6.90|
|reservoir OFF|0/12|0/12|155.03|61.76|50.59|6.11|

Full-frame ON yields are reservoir3/12 (25%) versus strongest2/12 (16.7%). There is one jointly successful pair, two reservoir-only successes, and one strongest-only success. The paired difference is+8.33 percentage points; descriptive paired-bootstrap95% interval-16.67 to+33.33 points, exact two-sided McNemar p=1.0. This small trial **does not establish reservoir superiority**. Per-policy Wilson intervals are preserved in JSON. Capture-level retained-frame yield is not packet recall.

Verified source frames: reservoir files0000/0007/0015 have sequences664/815/490 and CRC0989/04d7/93c4; strongest files0006/0031 have sequences981/911 and CRCd9fc/058a. All recover full address and deterministic payload. Both policies have zero exact headers, full payloads or RF-CRC source attribution in their12 OFF buffers. Zero observed attribution does not prove zero false-attribution probability.

Mean ON reservoir-minus-strongest host duty differs by only+0.198 percentage points; nominal local duty differs by+0.231 points. ON candidate rates are414.11 versus419.20/s, and ON-minus-OFF excess259.07 versus255.23/s. Reservoir copies less in these runs (6.90ms versus20.24ms average ON), but the tiny duty difference should not be promoted to a general throughput improvement. Strongest ON retained samples have mean4.42% near-full-scale component clipping versus0% reservoir; this illustrates energy-selection bias, not proof that each clipped waveform is unrelated to the source.

Representative three-panel figure `representative.svg` alongside final analysis shows reservoir0000 successful, strongest0001 without an exact source marker, and strongest0006 successful after finer demodulation. No clear failed strongest boundary-truncation example was found in this trial; none is invented. Earlier ABAB data contain the explicitly documented truncated frames.

Recommendation: retain the original strongest policy as default; keep reservoir experimental/optional. More counterbalanced runs over independent seeds and times would be needed to resolve a useful yield difference. The parent restored the original optimized image after this trial; this analysis performed no hardware operation.


## Final reproducibility and outcome separation

The exact analyzer used for final retention counts is copied beside the results as `records/nrf-retention/analysis-20261111T211056187993Z/analyze_nrf_iq.py`, with `reproduction.json` documenting the command, environment, settings and equal treatment of all48 ON/OFF buffers across both policies. SHA-256: `8884d783847ca0bed5600273467310f2f3f26ea5bded40e77cb8543e23e8538e`. This matches the analyzer hash already stored in the final analysis. Original optimized firmware remains restored and reservoir unadopted.

The same25kHz refinement was also applied to all14 buffers of the1Mbps screen. Results: `records/nrf-screen/mode1/analysis-20261111T211231310937Z/analysis.json`, with its own exact script copy and reproduction manifest. No full payload/address/CRC was recovered, so the coarser grid alone does not explain the missing full frames. However, baseline ON file0005 recovers exactRFTX, sequence483 and all119 available payload bits before truncation; baseline ON file0006 recovers sequence513 and all296 available bits exactly before truncation. Optimized ON file0013 has an exact header candidate but a corrupted partial suffix (71errors among409 available bits), so it is not accepted. No OFF exact-header candidate appears. Thus1Mbps has positive partial source evidence, not demonstrated radio failure.

Final terminology:

- **Validated complete frame:** observed address, entire expected payload and observed RF CRC all agree.
- **Complete payload only:** every expected payload byte agrees, but address/CRC boundaries may be unavailable; not a full-frame validation.
- **Truncated partial recovery:** available known bits agree but the capture ends or begins within the frame; not a CRC failure.
- **Corrupted/undecoded candidate:** some bits disagree or no acceptable marker appears under the documented search; this does not establish absence or radio failure.
- **Untested:** exhaustive fractional timing/clock recovery/equalization, calibrated sensitivity, true packet recall, and broad policy superiority were not established. Synthetic tests are software checks, not substitutes for RF evidence.
