# Controlled nRF RF validation: public evidence

Measurements from 11 November 2026. A privacy-filtered numeric export of seven controlled campaigns, not a raw radio recording release.

## What the counts mean

| Campaign | Retained IQ files | Transport CRC valid | Files with complete known RF packet |
|---|---:|---:|---:|
| First | 48 | 48 | 0 |
| Strong source | 56 | 56 | 0 |
| Gain sweep | 48 | 48 | 8 |
| Controlled gain 60 | 80 | 80 | 5 |
| Actual-image ABAB | 32 | 32 | 1 |
| Parameter screen | 238 | 238 | 6 |
| Retention trial | 48 | 48 | 5 |
| **Total** | **550** | **550** | **25** |

Transport CRC verifies UART transfer integrity. RF validation additionally requires the observed five-byte test address, entire known payload, and observed over-air CRC to agree. **25/550 is not packet recall.** Retained captures are discontinuous and selection-biased; transmitter counters bracket much longer host-controlled runs and are not matched to individual RF arrival opportunities. Candidate windows are not distinct packets. Three final receiver-health recordings are outside this campaign population.

## Files and provenance

- recordings.json: one row per original recording, original IQ/metadata SHA-256, byte count, sample rate, numeric receiver/source metadata, scalar and window diagnostics, and separate complete-payload/full-frame counts. Raw original files are intentionally absent. Their hashes are provenance commitments, not downloadable references.
- known-packets.json: observed and expected bytes from only the 25 fully validated self-generated test packets, plus observed/computed CRC and saved decoding hypotheses. No corrupted or unidentified payload bytes are released.
- analysis-summaries.json: original aggregate analysis values and original source-analysis hashes. Latest completed analysis per recording directory is selected, including the 25 kHz CFO-refined retention and 1 Mbps passes. Analyzer hashes identify historical versions; null indicates an earlier analysis did not record a hash.
- abab-comparison.json, parameter-screen.json, retention-comparison.json: numeric statistics, paired observations, and cautions from saved analyses, with original source hashes.
- campaign-totals.json: recording-level totals recomputed during export.
- source-provenance.json: hashes of original private reports and analysis scripts. Paths are relative provenance labels, not claims that these unredacted files are published.
- manifest.json: hashes and sizes of the public evidence files.

Numeric values are copied without rounding. Free-form metadata strings, device identity blocks, host paths, serial/USB identifiers and hardware recovery dumps are omitted. Numeric controlled-source settings/counters and numeric receiver summaries are retained. A missing/null gain or setting is unavailable in that selected analysis, not a zero setting. Original metadata hashes cover unredacted originals, not the filtered rows.

The saved parameter-screen summary predates the refined 1 Mbps analysis. Its zero complete-frame count remains unchanged; use recordings.json and analysis-summaries.json for final partial-recovery diagnostics. Decoder candidate lists are capped at 12 hypotheses and are not unique packet counts.

## Offline verification

From the repository root, run:

    python scripts/verify_nrf_evidence.py
    python -m unittest discover -s tests -p test_nrf_evidence.py

No dependencies beyond Python's standard library, network, devices, or radio transmissions are needed. The verifier checks public-file hashes, 550 unique recording rows, transport/full-frame totals, sample apertures and byte sizes, all 25 payload patterns and RF CRCs. It also recomputes ABAB candidate rates from detection counts and elapsed microseconds, local/host nominal duty from total samples, sample rate and the corresponding elapsed denominator, paired ON-minus-OFF excess, and cycle differences. It compares these point estimates and per-run values against the saved ABAB summary. Retention counts and paired difference are independently recomputed from recording condition/pair metadata and full-frame flags. Saved bootstrap confidence intervals are not recomputed. Tests also reject corrupted payloads, CRCs, addresses, artifact contents, sample/detection counts and retention pair results.

This independently recomputes CRC from the **published decoded bytes**, not from original IQ. Full independent demodulation and transfer-CRC revalidation are unavailable from this export because original IQ and wire-transfer bytes are not included. No synthetic IQ is substituted for measured evidence. Whole ambient IQ and plots capable of exposing unrelated signals are withheld. No IQ crop is released: decoded controlled test frames provide the narrowest useful disclosure.

The test address is the deliberately configured constant efcdab89c3, not a hardware identifier. Payloads are RFTX, a little-endian 32-bit sequence, then byte (offset + sequence) mod 256 for offsets 8 onward. Proprietary Nordic framing uses an 8-bit length, no whitening, and a 16-bit CRC initialized to ffff with polynomial 1021, including address, length and payload in LSB-first data order; CRC bits are MSB-first. This is not BLE.

## Conclusions and limitations

- Four of four center-frequency raw ON buffers in the gain-60 campaign validated, versus zero of four OFF buffers; ON mean power exceeded OFF by 22.563 dB in that small set. Offset controls had no exact known-header matches.
- In actual-image ABAB, optimized source-dependent candidate excess exceeded historical by about 102 windows/s in both cycles. Retained full-frame counts were historical 1/8 ON and optimized 0/8 ON. Optimized retained two complete payloads with missing frame boundaries, which are **not CRC failures**.
- The 17-variant screen was sequential, one-factor exploratory testing with three detector pairs per mode, not calibrated sensitivity certification.
- Retention yielded reservoir 3/12 versus strongest 2/12 ON, paired difference +8.33 percentage points, bootstrap 95% interval -16.67 to +33.33 points, exact McNemar p=1.0. Superiority is not demonstrated; strongest remains the adopted policy.
- ABAB has only four pairs per phase and two temporal repetitions. Bootstrap intervals are descriptive and may under-cover; ambient activity and order confound causal interpretation.
- Configured TX power is not calibrated received power. Gain indices are not dB. Nominal summed N/fs apertures do not establish continuous observation. Host timing does not identify individual RF arrivals.
- Partial 1 Mbps matches are evidence of partial reception, not complete validation or mode failure. An 8-byte test payload has no deterministic suffix beyond its marker/sequence, making its verified address and CRC especially important.
- At 80 MS/s, 16,380 samples span 204.75 microseconds, less than the 260 microseconds needed for length plus 64-byte payload at 2 Mbps.
- No packet recall, calibrated sensitivity, minimum reliable range/duration, real hopping-protocol decoding, general retention-policy improvement or multi-receiver continuous coverage is established.
