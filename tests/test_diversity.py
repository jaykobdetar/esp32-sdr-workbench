import numpy as np
import pytest

from sdr_research.analysis import spectrum
from sdr_research.diversity import combine_spectra
from sdr_research.protocol import Capture


def capture(amplitude=0.1, phase=0, frequency=2440000000, rate=16000000, n=1024):
    iq = amplitude * np.exp(1j * (2 * np.pi * np.arange(n) * 32 / 512 + phase))
    return Capture(iq.astype(np.complex64), rate, frequency, '', 0, 1000, 100, bits=10)


def test_opposite_phases_do_not_cancel():
    a = capture()
    b = capture(phase=np.pi)
    result = combine_spectra({'A': (a, 10), 'B': (b, 10)}, 10.1)
    _, expected = spectrum(a.iq, a.sample_rate_hz, 512)
    np.testing.assert_allclose(result.power_dbfs, expected, atol=1e-6)
    assert result.mode == 'power average' and result.contributors == ('A', 'B')


def test_linear_power_not_db_average():
    a = capture(0.1)
    b = capture(0.2)
    result = combine_spectra({'A': (a, 10), 'B': (b, 10)}, 10)
    _, pa = spectrum(a.iq, a.sample_rate_hz, 512)
    _, pb = spectrum(b.iq, b.sample_rate_hz, 512)
    np.testing.assert_allclose(
        result.power_dbfs, 10 * np.log10((10 ** (pa / 10) + 10 ** (pb / 10)) / 2)
    )


def test_stale_and_invalid():
    bad = capture()
    bad.crc_ok = False
    result = combine_spectra({'A': (capture(), 0), 'B': (bad, 10)}, 10)
    assert not result.contributors and len(result.excluded) == 2
    assert result.power_dbfs.size == 0


@pytest.mark.parametrize(
    'field,value', [('frequency_hz', 2450000000), ('sample_rate_hz', 40000000), ('bits', 8)]
)
def test_mismatch_uses_newest_compatible_group(field, value):
    a = capture()
    b = capture()
    setattr(b, field, value)
    result = combine_spectra({'A': (a, 10), 'B': (b, 11)}, 11)
    assert result.contributors == ('B',) and 'A' in result.excluded


def test_clipping_exclusion_and_fallback():
    a = capture()
    a.iq[:100] = 1 + 1j
    b = capture()
    b.iq[:200] = 1 + 1j
    clean = capture()
    result = combine_spectra({'A': (a, 10), 'B': (clean, 10)}, 10)
    assert result.contributors == ('B',) and 'clipping' in result.excluded['A']
    result = combine_spectra({'A': (a, 10), 'B': (b, 10)}, 10)
    assert result.contributors == ('A',) and result.mode == 'least-clipped fallback'


def test_buffer_length_alignment_and_nonfinite():
    a = capture(n=256)
    b = capture(n=1024)
    result = combine_spectra({'A': (a, 10), 'B': (b, 10)}, 10)
    assert result.power_dbfs.size == 256
    a.iq[0] = np.nan
    result = combine_spectra({'A': (a, 10), 'B': (b, 10)}, 10)
    assert result.contributors == ('B',)
