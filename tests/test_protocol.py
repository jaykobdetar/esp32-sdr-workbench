"""Offline protocol framing tests. No serial devices are opened."""

import struct
import zlib
from collections import deque

import numpy as np
import pytest

from sdr_research import protocol
from sdr_research.protocol import ProtocolError, Radio


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        self.now += 0.001
        return self.now


class FakeSerial:
    """Serial byte stream which preserves boundaries and can return short reads."""

    def __init__(self, data=b'', chunk_size=7, clock=None):
        self.pending = deque(data[i : i + chunk_size] for i in range(0, len(data), chunk_size))
        self.writes = []
        self.closed = False
        self.clock = clock

    def read(self, size):
        if not self.pending:
            if self.clock:
                self.clock.now += 1
            return b''
        data = self.pending.popleft()
        result, rest = data[:size], data[size:]
        if rest:
            self.pending.appendleft(rest)
        return result

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def make_radio(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(protocol.time, 'monotonic', clock.monotonic)

    def make(data=b'', bits=8, chunk_size=7):
        transport = FakeSerial(data, chunk_size, clock)
        radio = Radio('FAKE-NO-HARDWARE', transport=transport)
        radio.info = {
            'family': 'ESP32SDR',
            'protocol': 6,
            'max_samples': 16380,
            'caps': ['SPEC', 'SPECSTAT'],
            'limits': {
                'rates': [16000000, 40000000, 80000000],
                'bits': [8, 10],
                'gain': [0, 79, 1],
                'bandwidth': [12, 67, 1, 0],
            },
            'spectrum': {'profiles': [[16000000, 6, 256, 1, 1, 0]]},
        }
        radio.settings = {
            'frequency_mhz': 2440,
            'rate_hz': 16000000,
            'bandwidth_mhz': 0,
            'gain': None,
            'bits': bits,
        }
        return radio, transport

    return make


def capture_bytes(payload, samples, crc=None):
    if crc is None:
        crc = zlib.crc32(payload)
    return f'DATA {samples} {crc:08x} 17\n'.encode() + payload


def spectrum_frame(*, seq=3, bins=256, multiplier=2, gain=40, corrupt_crc=False):
    body = b'SPC1' + struct.pack(
        '<IQIHBBHBB', seq, 123456, bins * 2, 2, 9, gain, 0, bins.bit_length() - 1, multiplier
    )
    body += bytes(range(256)) * (bins // 256)
    crc = zlib.crc32(body) ^ int(corrupt_crc)
    return body + struct.pack('<I', crc)


def stats_frame(*, corrupt_crc=False):
    values = (120, 0, 25, 0, 102400, 65536, 0, 1, 4, 10, 3200)
    body = b'SPS1' + struct.pack('<HHHHIIIIHHI', *values)
    return body + struct.pack('<I', zlib.crc32(body) ^ int(corrupt_crc))


START = b'SPEC 256 16000000 256 2440\n'
END = b'SPECEND 0 0 2 512 1000000 0 0 1 0 0 2 0\n'


def assert_poisoned(radio, transport):
    assert radio.failed
    writes = list(transport.writes)
    with pytest.raises(ProtocolError, match='reconnect required'):
        radio.command('INFO')
    assert transport.writes == writes


@pytest.mark.parametrize('chunk_size', [1, 3, 4096])
def test_fragmented_lines_and_binary_preserve_adjacent_response(make_radio, chunk_size):
    radio, transport = make_radio(b'OK\r\n\x00\n\xffABCINFO next\n', chunk_size=chunk_size)
    assert radio.command('TEST') == 'OK'
    assert radio._read(6) == b'\x00\n\xffABC'
    assert radio._line() == 'INFO next'
    assert transport.writes == [b'TEST\n']


@pytest.mark.parametrize('bits,n', [(8, 256), (8, 257), (10, 256), (10, 257)])
def test_capture_formats_sign_and_metadata(make_radio, bits, n):
    limit = 1 << (bits - 1)
    pairs = [(limit - 1, -limit), (-limit, limit - 1), (0, -1)]
    pairs = [pairs[k % len(pairs)] for k in range(n)]
    if bits == 8:
        payload = bytes(component & 255 for pair in pairs for component in pair)
    else:
        packed = sum(
            ((i & 1023) | ((q & 1023) << 10)) << (20 * k) for k, (i, q) in enumerate(pairs)
        )
        payload = packed.to_bytes((n * 20 + 7) // 8, 'little')
    radio, transport = make_radio(capture_bytes(payload, n), bits=bits, chunk_size=3)
    capture = radio.capture(n)
    expected = np.array([(i - 1j * q) / limit for i, q in pairs])
    np.testing.assert_allclose(capture.iq, expected)
    assert capture.bits == bits
    assert capture.crc_ok
    assert capture.firmware_capture_us == 17
    assert capture.sample_rate_hz == 16000000
    assert capture.frequency_hz == 2440000000
    assert capture.nominal_rf_seconds == n / 16000000
    assert transport.writes == [f'CAP{bits * 2} {n} 6\n'.encode()]
    assert not radio.failed


def test_capture_crc_mismatch_requires_reconnect(make_radio):
    payload = bytes(512)
    radio, transport = make_radio(capture_bytes(payload, 256, zlib.crc32(payload) ^ 1))
    with pytest.raises(ProtocolError, match='CRC mismatch'):
        radio.capture(256)
    assert_poisoned(radio, transport)


@pytest.mark.parametrize('header', [b'DATA 255 0 17\n', b'DATA 256 no-crc 17\n', b'HELLO\n'])
def test_capture_bad_header_requires_reconnect(make_radio, header):
    radio, transport = make_radio(header)
    with pytest.raises(ProtocolError, match='Invalid capture header'):
        radio.capture(256)
    assert_poisoned(radio, transport)


def test_truncated_capture_requires_reconnect(make_radio):
    radio, transport = make_radio(b'DATA 256 00000000 17\n\x00\x01')
    with pytest.raises(TimeoutError, match='Truncated binary payload'):
        radio.capture(256)
    assert_poisoned(radio, transport)


def test_command_error_is_explicit_and_clean_line_can_continue(make_radio):
    radio, transport = make_radio(b'ERR unsupported\nESP32SDR 6 burst 16380\n')
    with pytest.raises(ProtocolError, match='INFO: ERR unsupported'):
        radio.command('INFO')
    assert not radio.failed
    assert radio.command('INFO') == 'ESP32SDR 6 burst 16380'


@pytest.mark.parametrize('chunk_size', [1, 7, 1024])
def test_spectrum_frames_stats_and_end(make_radio, chunk_size):
    radio, transport = make_radio(
        START + spectrum_frame() + stats_frame() + END, chunk_size=chunk_size
    )
    result = radio.spectrum_run()
    frame = result['frames'][0]
    assert frame['sequence'] == 3
    assert frame['sample_index'] == 123456
    assert frame['span'] == 512
    assert frame['ffts'] == 2
    assert frame['flags'] == 9
    assert frame['gain'] == 40
    assert frame['power_codes'] == list(range(256))
    assert result['stats'][0]['coverage_permille'] == 25
    assert result['stats'][0]['ffts_per_second'] == 3200
    assert result['end']['status'] == 0
    assert result['end']['pairs'] == 512
    assert result['end']['ffts'] == 2
    assert transport.writes == [b'SPEC 1000 1 1 1 6 256 1\n']
    assert not radio.failed


@pytest.mark.parametrize(
    'frame,match',
    [
        (spectrum_frame(corrupt_crc=True), 'Spectrum CRC mismatch'),
        (stats_frame(corrupt_crc=True), 'Statistics CRC mismatch'),
        (b'BAD!', 'Unknown spectrum frame'),
        (b'SPECjunk\n', 'Invalid spectrum end'),
        (b'SPECEND 0 0\n', 'Failed spectrum run'),
        (b'SPECEND 7 0 2 512 1000000 0 0 1 0 0 2 0\n', 'Failed spectrum run'),
    ],
)
def test_malformed_spectrum_requires_reconnect(make_radio, frame, match):
    radio, transport = make_radio(START + frame)
    with pytest.raises(ProtocolError, match=match):
        radio.spectrum_run()
    assert_poisoned(radio, transport)


@pytest.mark.parametrize('body', [b'SPC1\x00', b'SPS1\x00', b'SP', b''])
def test_truncated_spectrum_requires_reconnect(make_radio, body):
    radio, transport = make_radio(START + body)
    with pytest.raises(TimeoutError):
        radio.spectrum_run()
    assert_poisoned(radio, transport)


def test_spectrum_fft_size_mismatch_requires_reconnect(make_radio):
    # Keep expected payload length but alter log2 field and recompute CRC.
    frame = bytearray(spectrum_frame())
    frame[26] = 9
    frame[-4:] = struct.pack('<I', zlib.crc32(frame[:-4]))
    radio, transport = make_radio(START + frame)
    with pytest.raises(ProtocolError, match='FFT size mismatch'):
        radio.spectrum_run()
    assert_poisoned(radio, transport)


def test_close_failed_stream_does_not_send_release_into_binary(make_radio):
    radio, transport = make_radio()
    radio.failed = True
    radio.close()
    assert transport.closed
    assert transport.writes == []
    assert radio.serial is None


def test_clean_close_releases_lease(make_radio):
    radio, transport = make_radio(b'OK\n')
    radio.close()
    assert transport.writes == [b'RELEASE\n']
    assert transport.closed


@pytest.mark.parametrize(
    'reply,exception,match',
    [
        (b'', TimeoutError, 'timed out'),
        (b'\xff\n', ProtocolError, 'Non-ASCII'),
    ],
)
def test_command_framing_failures_require_reconnect(make_radio, reply, exception, match):
    radio, transport = make_radio(reply)
    with pytest.raises(exception, match=match):
        radio.command('INFO')
    assert_poisoned(radio, transport)


def test_oversized_command_reply_requires_reconnect(make_radio, monkeypatch):
    radio, transport = make_radio(b'A' * 8193 + b'\n')
    # Avoid spending the simulated deadline while reading this intentionally long line.
    monkeypatch.setattr(protocol.time, 'monotonic', lambda: 100.0)
    with pytest.raises(ProtocolError, match='Oversized reply'):
        radio.command('INFO')
    assert_poisoned(radio, transport)


@pytest.mark.parametrize('operation', ['write', 'flush'])
def test_command_transport_failure_requires_reconnect(make_radio, operation, monkeypatch):
    radio, transport = make_radio()

    def broken(*args):
        raise OSError('simulated USB disconnect')

    monkeypatch.setattr(transport, operation, broken)
    with pytest.raises(OSError, match='USB disconnect'):
        radio.command('INFO')
    assert_poisoned(radio, transport)


@pytest.mark.parametrize(
    'start',
    [
        b'OK\n',
        b'SPEC \n',
        b'SPEC 512 16000000 256 2440\n',
        b'SPEC 256 40000000 256 2440\n',
        b'SPEC 256 16000000 512 2440\n',
        b'SPEC 256 16000000 256 2412\n',
        b'SPEC 256 16000000 256 2440 unexpected\n',
    ],
)
def test_spectrum_start_must_match_requested_settings(make_radio, start):
    radio, transport = make_radio(start + spectrum_frame() + END)
    with pytest.raises(ProtocolError, match='Invalid spectrum start'):
        radio.spectrum_run()
    assert_poisoned(radio, transport)


@pytest.mark.parametrize('multiplier', [0, 1, 3, 255])
def test_spectrum_unsupported_power_multiplier_requires_reconnect(make_radio, multiplier):
    radio, transport = make_radio(START + spectrum_frame(multiplier=multiplier) + END)
    with pytest.raises(ProtocolError, match='Unsupported spectrum power multiplier'):
        radio.spectrum_run()
    assert_poisoned(radio, transport)


def test_spectrum_retains_power_multiplier(make_radio):
    radio, _ = make_radio(START + spectrum_frame(multiplier=2) + END)
    assert radio.spectrum_run()['frames'][0]['multiplier'] == 2


@pytest.mark.parametrize(
    'name,expected_stem',
    [
        ('capture', 'capture'),
        ('capture.v1', 'capture.v1'),
        ('2026.11.10.sample.v2', '2026.11.10.sample.v2'),
        ('capture.v1.sigmf-meta', 'capture.v1'),
        ('capture.v1.sigmf-data', 'capture.v1'),
    ],
)
def test_sigmf_dotted_filename_and_known_suffix_roundtrip(tmp_path, name, expected_stem):
    from sdr_research.protocol import Capture
    from sdr_research.recording import load_capture, save_capture

    capture = Capture(
        np.array([0.125 + 0.25j, -0.5 - 0.75j], dtype=np.complex64),
        16000000,
        2440000000,
        '2026-11-10T21:00:00+00:00',
        100,
        200,
        7,
        bits=10,
        metadata={'test': 'dotted path'},
    )
    meta = save_capture(capture, tmp_path / name)
    assert meta.name == expected_stem + '.sigmf-meta'
    assert (tmp_path / (expected_stem + '.sigmf-data')).is_file()
    restored = load_capture(meta)
    np.testing.assert_array_equal(restored.iq, capture.iq)
    assert restored.sample_rate_hz == capture.sample_rate_hz
    assert restored.frequency_hz == capture.frequency_hz
    assert restored.bits == 10
    assert restored.metadata == capture.metadata
    assert restored.monotonic_start_ns == 100
    assert restored.firmware_capture_us == 7


@pytest.mark.parametrize('datatype', ['ci16_le', 'cf64_le', 'cf32_be', 'rf32_le', 'not-a-datatype'])
def test_sigmf_rejects_unsupported_datatype_before_reading_payload(tmp_path, datatype):
    import json

    from sdr_research.recording import load_capture

    path = tmp_path / 'capture.v1.sigmf-meta'
    path.write_text(json.dumps({'global': {'core:datatype': datatype}, 'captures': [{}]}))
    # There is intentionally no data file: unsupported data must not be interpreted.
    with pytest.raises(ValueError, match='cf32_le'):
        load_capture(path)


@pytest.mark.parametrize('gain', [0, 40, 79, 255])
def test_spectrum_preserves_wire_gain_independent_of_requested_settings(make_radio, gain):
    radio, _ = make_radio(START + spectrum_frame(gain=gain) + END)
    radio.settings['gain'] = 12
    assert radio.spectrum_run()['frames'][0]['gain'] == gain
