"""Noncoherent display fusion. Never synthesizes IQ or estimates RF coverage."""

from dataclasses import dataclass

import numpy as np

from .analysis import endpoint_counts, spectrum


@dataclass
class SpectrumFusion:
    frequency_mhz: np.ndarray
    power_dbfs: np.ndarray
    contributors: tuple[str, ...]
    excluded: dict[str, str]
    mode: str
    max_age_s: float


def combine_spectra(inputs: dict, now: float, max_age_s: float = 2.0) -> SpectrumFusion:
    """Inputs name -> (Capture, local monotonic arrival seconds).

    Arrival freshness is not RF simultaneity. Different clocks/gains/phases are
    not calibrated. Arithmetic averages linear FFT power, never IQ or dB values.
    Clipped buffers (>1% ADC endpoints) are excluded if a clean buffer exists.
    With all clipped, select least clipped and explicitly label the fallback.
    """
    valid = []
    excluded = {}
    for name, (capture, arrival) in inputs.items():
        age = now - arrival
        if not np.isfinite(age) or age < 0 or age > max_age_s:
            excluded[name] = 'stale or invalid arrival time'
            continue
        iq = np.asarray(capture.iq)
        if not capture.crc_ok or len(iq) < 2 or not np.isfinite(iq).all():
            excluded[name] = 'invalid samples or transport CRC'
            continue
        if capture.sample_rate_hz <= 0 or capture.frequency_hz <= 0 or capture.bits not in (8, 10):
            excluded[name] = 'invalid capture metadata'
            continue
        clipping = endpoint_counts(iq, capture.bits)['either_component_endpoint_percent']
        valid.append((name, capture, arrival, clipping))
    if not valid:
        return SpectrumFusion(np.array([]), np.array([]), (), excluded, 'unavailable', 0)
    # Newest valid observation sets the compatibility group; never mix tunings.
    anchor = max(valid, key=lambda x: x[2])[1]
    compatible = []
    for item in valid:
        name, capture, _, _ = item
        if (capture.frequency_hz, capture.sample_rate_hz, capture.bits) != (
            anchor.frequency_hz,
            anchor.sample_rate_hz,
            anchor.bits,
        ):
            excluded[name] = 'different frequency, sample rate or ADC format'
        else:
            compatible.append(item)
    clean = [x for x in compatible if x[3] <= 1]
    if clean:
        selected = clean
        mode = 'power average' if len(clean) > 1 else 'single usable receiver'
        for item in compatible:
            if item[3] > 1:
                excluded[item[0]] = f'possible clipping ({item[3]:.2f}% endpoints)'
    else:
        selected = [min(compatible, key=lambda x: (x[3], -x[2]))]
        mode = 'least-clipped fallback'
        for item in compatible:
            if item is not selected[0]:
                excluded[item[0]] = 'more ADC endpoints than selected fallback'
    nfft = min(512, min(len(x[1].iq) for x in selected))
    powers = []
    for _, capture, _, _ in selected:
        offsets, power = spectrum(capture.iq, capture.sample_rate_hz, nfft)
        powers.append(10 ** (power / 10))
    mean = np.mean(powers, axis=0)
    return SpectrumFusion(
        offsets / 1e6 + anchor.frequency_hz / 1e6,
        10 * np.log10(np.maximum(mean, 1e-16)),
        tuple(x[0] for x in selected),
        excluded,
        mode,
        max(now - x[2] for x in selected),
    )
