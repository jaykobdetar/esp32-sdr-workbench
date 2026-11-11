import numpy as np
import pytest

from sdr_research.analysis import detect_event, endpoint_counts, spectrum
from sdr_research.protocol import Capture, ProtocolError, decode_iq
from sdr_research.recording import load_capture, save_capture


def test_iq8_q_sign_and_min():
    a = decode_iq(bytes([127, 128, 128, 127]), 2, 8)
    np.testing.assert_allclose(a, [127 / 128 + 1j, -1 - 127j / 128])


def test_iq10_odd_and_even():
    for n in (1, 2, 3, 257):
        rng = np.random.default_rng(n)
        pairs = rng.integers(-512, 512, (n, 2))
        bits = 0
        for k, (i, q) in enumerate(pairs):
            bits |= ((int(i) & 1023) | ((int(q) & 1023) << 10)) << (20 * k)
        data = bits.to_bytes((20 * n + 7) // 8, 'little')
        np.testing.assert_allclose(decode_iq(data, n, 10), (pairs[:, 0] - 1j * pairs[:, 1]) / 512)


def test_bad_length():
    with pytest.raises(ProtocolError):
        decode_iq(b'', 5, 8)


def test_spectrum_tone_direction():
    n = 4096
    x = 0.5 * np.exp(2j * np.pi * np.arange(n) / 16)
    f, p = spectrum(x, 16_000_000)
    assert f[p.argmax()] == 1_000_000
    assert abs(p.max() + 6.02) < 0.02


def test_energy_detector_dc_robust():
    rng = np.random.default_rng(5)
    x = 0.02 * (rng.normal(size=4096) + 1j * rng.normal(size=4096))
    assert not detect_event(x + (0.8 + 0.5j), 16_000_000)['detected']
    x[1500:2000] += 0.3 * np.exp(2j * np.pi * np.arange(500) / 8)
    assert detect_event(x, 16_000_000)['detected']


def test_sigmf_roundtrip(tmp_path):
    c = Capture(
        np.array([0.1 + 0.2j, -0.7 - 0.4j], np.complex64),
        16_000_000,
        2440000000,
        '2026-11-10T21:00:00+00:00',
        100,
        200,
        3,
    )
    p = save_capture(c, tmp_path / 'example')
    r = load_capture(p)
    np.testing.assert_equal(c.iq, r.iq)
    assert r.frequency_hz == c.frequency_hz
    with pytest.raises(FileExistsError):
        save_capture(c, tmp_path / 'example')


def test_sigmf_reject_partial_sample(tmp_path):
    c = Capture(
        np.array([0.1j], np.complex64),
        16_000_000,
        2440000000,
        '2026-11-10T21:00:00+00:00',
        100,
        200,
        3,
    )
    p = save_capture(c, tmp_path / 'partial')
    with p.with_suffix('.sigmf-data').open('ab') as f:
        f.write(b'x')
    with pytest.raises(ValueError, match='Truncated'):
        load_capture(p)


@pytest.mark.parametrize('bits', [8, 10])
def test_endpoint_counts_match_offline_script_convention(bits):
    scale = 1 << (bits - 1)
    # (I, wire Q) codes; the stored complex value negates wire Q.
    codes = [(-scale, 0), (0, scale - 1), (scale - 1, -scale), (2, -3), (0, -(scale - 1))]
    iq = np.array([(i - 1j * q) / scale for i, q in codes], np.complex64)
    assert endpoint_counts(iq, bits) == dict(
        samples=5,
        i_endpoint_samples=2,
        wire_q_endpoint_samples=2,
        either_component_endpoint_samples=3,
        either_component_endpoint_percent=60.0,
    )


def test_endpoint_counts_edge_cases():
    assert endpoint_counts(np.zeros(0, np.complex64), 10)['either_component_endpoint_percent'] == 0
    # Replay data beyond full scale counts as saturated rather than being ignored.
    assert endpoint_counts(np.array([1.5 + 0j, 0.1j]), 10)['i_endpoint_samples'] == 1
    with pytest.raises(ValueError):
        endpoint_counts(np.zeros(4, np.complex64), 12)
