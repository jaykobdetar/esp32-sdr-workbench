"""Conservative exploratory detectors. Scores are NOT transmitter identity."""

import numpy as np
from numpy.typing import ArrayLike, NDArray


def spectrum(
    iq: ArrayLike, rate_hz: float, nfft: int = 1024, remove_dc: bool = True
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x = np.asarray(iq, dtype=np.complex64)
    nfft = min(int(nfft), len(x))
    if nfft < 2:
        raise ValueError('Need at least two samples')
    x = x[: len(x) // nfft * nfft].reshape(-1, nfft).copy()
    if remove_dc:
        x -= x.mean(axis=1, keepdims=True)
    w = np.hanning(nfft)
    f = np.fft.fftshift(np.fft.fft(x * w, axis=1), axes=1)
    power = np.mean(abs(f) ** 2, axis=0) / max(w.sum() ** 2, 1)
    return np.fft.fftshift(np.fft.fftfreq(nfft, 1 / rate_hz)), 10 * np.log10(
        np.maximum(power, 1e-16)
    )


def detect_event(
    iq: ArrayLike, rate_hz: float, threshold_db: float = 10
) -> dict[str, bool | float | str]:
    # Block-energy change detector avoids comparing passband peaks to out-of-band floor.
    # Cannot detect an event spanning the entire capture without a calibrated baseline.
    x = np.asarray(iq, dtype=np.complex64)
    x = x - x.mean()
    block = min(64, max(8, len(x) // 16))
    n = len(x) // block
    power = np.mean(abs(x[: n * block].reshape(n, block)) ** 2, axis=1)
    floor = max(float(np.quantile(power, 0.25)), 1e-15)
    peak = max(float(power.max()), 1e-15)
    snr = 10 * np.log10(peak / floor)
    active = power > floor * 10 ** (threshold_db / 10)
    f, ps = spectrum(x, rate_hz, min(1024, len(x)))
    # Descriptive occupied bandwidth, not calibrated modulation classification.
    p = 10 ** (ps / 10)
    cum = np.cumsum(p) / max(p.sum(), 1e-20)
    lo = min(np.searchsorted(cum, 0.05), len(f) - 1)
    hi = min(np.searchsorted(cum, 0.95), len(f) - 1)
    return dict(
        detected=bool(active.any()),
        peak_dbfs=float(10 * np.log10(peak)),
        noise_dbfs=float(10 * np.log10(floor)),
        snr_db=float(snr),
        bandwidth_hz=float(f[hi] - f[lo]),
        duration_us=float(active.sum() * block / rate_hz * 1e6),
        confidence='uncalibrated candidate',
        detector='within-capture block-energy v1',
    )


def endpoint_counts(iq: ArrayLike, bits: int) -> dict[str, int | float]:
    """Count samples whose I or wire-Q component sits on a signed ADC endpoint code.

    Endpoints are the lowest and highest codes of a signed ``bits``-wide component
    (-512/511 for 10-bit, -128/127 for 8-bit). Captures are stored as
    ``(I - 1j*wire_Q) / 2**(bits-1)``, so wire-Q is the negated imaginary part.
    Values beyond full scale (possible only for non-ADC replay data) count as endpoints.
    A high share indicates likely converter saturation; it does not identify the cause,
    and a zero count does not prove the analog chain was linear.
    """
    if bits not in (8, 10):
        raise ValueError('bits must be 8 or 10')
    x = np.asarray(iq, dtype=np.complex64)
    scale = 1 << (bits - 1)
    i = np.rint(x.real * scale)
    q = np.rint(-x.imag * scale)
    i_end = (i <= -scale) | (i >= scale - 1)
    q_end = (q <= -scale) | (q >= scale - 1)
    either = int(np.count_nonzero(i_end | q_end))
    return dict(
        samples=len(x),
        i_endpoint_samples=int(np.count_nonzero(i_end)),
        wire_q_endpoint_samples=int(np.count_nonzero(q_end)),
        either_component_endpoint_samples=either,
        either_component_endpoint_percent=100 * either / len(x) if len(x) else 0.0,
    )


class NoiseCalibration:
    """Per-setting PSD reference. User must collect idle data; resets on setting changes."""

    def __init__(self) -> None:
        self.key = None
        self.frames = []
        self.baseline = None

    def add(self, key: object, power_dbfs: ArrayLike) -> NDArray[np.floating]:
        if key != self.key:
            self.key = key
            self.frames = []
            self.baseline = None
        self.frames.append(np.asarray(power_dbfs).copy())
        self.frames = self.frames[-100:]
        self.baseline = np.median(self.frames, axis=0)
        return self.baseline
