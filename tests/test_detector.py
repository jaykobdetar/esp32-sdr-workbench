import json

import pytest

from sdr_research.detector import run_detection
from sdr_research.protocol import ProtocolError


class Radio:
    def __init__(self, updates=None):
        self.settings = {'frequency_mhz': 2440}
        self.failed = False
        self.summary = {
            'version': 1,
            'status': 0,
            'captures': 20,
            'detections': 0,
            'warmup_captures': 16,
            'errors': 0,
            'sample_rate_hz': 16000000,
            'frequency_mhz': 2440,
            'retained_samples': 0,
            'wall_elapsed_us': 2000000,
            'total_samples': 327600,
            'analyzed_samples': 326400,
        }
        self.summary.update(updates or {})

    def command(self, s):
        if s == 'DETINFO?':
            return 'DETINFO 1 5000 16 64'
        return 'DET1 BEGIN 2000 16380 6 4000 0 2440'

    def _line(self, d):
        return 'DET1 END ' + json.dumps(self.summary)


def test_finite_summary():
    s, c = run_detection(Radio(), retain=False)
    assert c is None and s['nominal_rf_duty_percent'] == pytest.approx(1.02375)


@pytest.mark.parametrize(
    'updates',
    [
        {'frequency_mhz': 2402},
        {'sample_rate_hz': 1},
        {'retained_samples': 500},
        {'wall_elapsed_us': 0},
        {'total_samples': 1},
        {'analyzed_samples': 1},
    ],
)
def test_reject_malformed_counters(updates):
    r = Radio(updates)
    with pytest.raises(ProtocolError):
        run_detection(r, retain=False)
    assert r.failed


def test_host_total_includes_query_and_run(monkeypatch):
    from sdr_research import detector

    ticks = iter([0, 1_000_000, 2_001_000_000, 2_002_000_000])
    monkeypatch.setattr(detector.time, 'monotonic_ns', lambda: next(ticks))
    s, _ = run_detection(Radio(), retain=False)
    assert s['host_elapsed_us'] == 2_000_000
    assert s['host_total_elapsed_us'] == 2_002_000
    assert s['nominal_host_duty_percent'] == pytest.approx(100 * (327600 / 16000000) / 2.002)
    assert not s['retained_crc_valid']
    assert s['retained_event_count'] == 0


class RetainedRadio(Radio):
    def __init__(self, bad_crc=False):
        super().__init__({'retained_samples': 16380, 'detections': 1})
        self.info = {'family': 'FAKE'}
        self.bad_crc = bad_crc
        self.payload = bytes((16380 * 20 + 7) // 8)

    def command(self, s):
        import zlib

        if s == 'DETGET':
            return f'DATA 16380 {zlib.crc32(self.payload) ^ int(self.bad_crc):08x} 1025'
        return super().command(s).replace('4000 0 2440', '4000 1 2440')

    def _read(self, n):
        assert n == len(self.payload)
        return self.payload


def test_retained_metadata_and_summary_are_serializable():
    s, c = run_detection(RetainedRadio())
    assert c.crc_ok and s['retained_crc_valid'] and s['retained_event_count'] == 1
    assert len(c.iq) == 16380
    assert s['host_total_elapsed_us'] >= s['host_elapsed_us']
    json.dumps(c.metadata)  # no recursive metadata references
    assert 'run start' in s['timing_note']


def test_retained_crc_failure_poisoned():
    r = RetainedRadio(True)
    with pytest.raises(ProtocolError, match='CRC mismatch'):
        run_detection(r)
    assert r.failed


@pytest.mark.parametrize(
    'updates',
    [
        {'wall_elapsed_us': float('nan')},
        {'wall_elapsed_us': float('inf')},
        {'wall_elapsed_us': True},
        {'warmup_captures': -1},
        {'warmup_captures': 15},
        {'detections': 5},
        {'detections': 1.0},
        {'status': 2},
        {'errors': 1},
    ],
)
def test_malformed_duty_fields_rejected(updates):
    r = Radio(updates)
    with pytest.raises(ProtocolError):
        run_detection(r, retain=False)
    assert r.failed
