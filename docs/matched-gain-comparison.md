# Matched AGC versus manual gain, 11 November 2026

## What was measured

Twenty-four bounded one-second detector runs used the **unchanged installed
`esp32-pipeline-optimized-v2`** firmware: four temporal blocks, each containing
hardware AGC, manual gain 40 and manual gain 60 with the nRF source ON and OFF.
Block ordering was seeded and mode/state ordering counterbalanced. The receiver
was not flashed. Each run used 2440 MHz, nominal 16 MS/s, 16,380 samples, a 12 MHz
bandwidth setting and 4× threshold. The source used 64-byte known payloads,
2 Mbps, nominal 2 ms intervals with 150 µs jitter, and **−20 dBm**, not the 0 dBm
of the earlier ABAB campaign.

The physical bench placement was unchanged but **distance and orientation were
not measured**. This is a gain comparison at one uncontrolled placement, not the
requested measured-distance/power trial or calibrated sensitivity measurement.

## Results

Candidate windows per second of local detector wall time, averaged over four runs:

| Gain mode | OFF | ON | Mean paired ON minus OFF |
|---|---:|---:|---:|
| Hardware AGC | 178.72 | 393.56 | +214.84 |
| Manual 40 | 81.57 | 100.84 | +19.26 |
| Manual 60 | 175.43 | 164.92 | −10.51 |

The four AGC ON-minus-OFF block differences were approximately 27.05, 327.62,
219.46 and 285.23 candidate windows/s. The AGC-minus-manual matched contrasts
have exact two-sided sign-flip **p = 0.25 for both manual settings**. Four blocks
and strong temporal variability do not establish superiority. The sign test
assumes exchangeable signs; enumeration cannot establish that assumption.

All 24 retained buffers passed transport CRC. Both manual modes had zero signed
ADC endpoints in all eight retained buffers each. AGC had endpoints in seven of
eight retained buffers. These are selected buffers, not an unbiased sample of
all acquisitions. Zero endpoints does not establish analog linearity, and this
comparison did not decode packets or measure packet recall.

The data show that candidate rates depend strongly on gain configuration under
these conditions. They do **not** demonstrate that one mode detects more actual
packets, that the source-off rate is a packet false-positive rate, or that the new
Q16 detector improves over the installed detector. The historical background
latch remained present during this test.

## Safety, provenance and reproduction

The transmitter had independent packet-count and duration ceilings for every ON
run and was explicitly stopped between conditions and at completion. Its initial
configuration and the receiver's initial gain mode were restored and read back.
No firmware, recovery image, security setting or network setting was changed.

[Scrubbed per-run evidence](evidence/gain-comparison-20261111.json) includes every
count, denominator, gain-mode readback, exact contrast, transport-CRC result, raw
IQ hash/byte count and signed-endpoint count. Raw IQ and device identifiers remain
private. The firmware artifact hash identifies the preserved local reference;
installed flash was not read back during this trial.

After installing the package, use `python -m nrf_campaigns.nrf_gain_compare --help`
for the bounded runner. It deliberately refuses firmware other than the measured
optimized-v2 family. `python -m nrf_campaigns.nrf_gain_analysis --help` analyzes
private originals; `tests/test_nrf_gain_compare.py` also independently recomputes
the public rates and exact contrasts without devices or raw RF.

## Remaining physical work

Measure and record antenna-to-antenna distance, orientation, mounting height and
obstructions before distance/power trials. Fix the gain, frequency, packet format
and settings across matched trials; record source OFF controls at each placement.
Do not turn the unmeasured bench description above into a guessed distance.
