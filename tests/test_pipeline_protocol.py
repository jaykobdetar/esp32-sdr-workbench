import json
import zlib

import numpy as np
import pytest

from sdr_research.pipeline import run_pipeline
from sdr_research.protocol import ProtocolError, Radio


class Fake:
    def __init__(self, data):
        self.data = bytearray(data)
        self.writes = []

    def read(self, n):
        n = min(n, 3)
        v = bytes(self.data[:n])
        del self.data[:n]
        return v

    def write(self, b):
        self.writes.append(b)
        return len(b)

    def flush(self):
        pass


def create(changes=None, bad_crc=False, errors=b'', kernel=0):
    s = dict(
        version=1,
        kernel=kernel,
        status=0,
        captures=17,
        processed_captures=17,
        detections=1,
        background_adc2=2,
        best_ratio_milli=100000,
        wall_elapsed_us=2000,
        completion_observed_us=1700,
        acquire_call_us_includes_overlap=1900,
        energy_compute_us=1000,
        copy_us=50,
        decision_us=10,
        retention_copy_us=5,
        retained_samples=257,
        frequency_mhz=2440,
        total_samples=17 * 257,
        analyzed_samples=17 * 256,
        sample_rate_hz=16000000,
        errors=0,
        warmup_captures=16,
    )
    if changes:
        s.update(changes)
    words = [((k & 1023) | (((-k) & 1023) << 10)) for k in range(257)]
    packed = sum(w << (20 * k) for k, w in enumerate(words)).to_bytes((257 * 20 + 7) // 8, 'little')
    data = (
        f'PIPEKERNEL {kernel}\n'.encode()
        + b'DETPIPEINFO 1 5000 16 64\nDETPIPE1 BEGIN 2 257 6 4000 1 2440\n'
        + errors
    )
    data += b'DETPIPE1 END ' + json.dumps(s).encode() + b'\n'
    data += f'DATA 257 {zlib.crc32(packed) ^ int(bad_crc):08x} 1050\n'.encode() + packed
    f = Fake(data)
    r = Radio('FAKE', transport=f)
    r.settings = {'frequency_mhz': 2440}
    return r, f


def test_retention_and_odd_length():
    r, f = create()
    s, c = run_pipeline(r, 2, 257)
    assert s['retained_crc_valid']
    np.testing.assert_allclose(c.iq, np.arange(257) * (1 + 1j) / 512)
    assert f.writes[-1] == b'DETPIPEGET\n'
    assert c.firmware_capture_us == 1050
    assert 'not RF duration' in c.metadata['firmware_capture_us_semantics']


@pytest.mark.parametrize(
    'changes',
    [
        {'kernel': 3},
        {'captures': True},
        {'wall_elapsed_us': float('nan')},
        {'processed_captures': 16},
        {'warmup_captures': 15},
        {'retained_samples': 999999},
        {'sample_rate_hz': 80000000},
        {'total_samples': 10},
        {'analyzed_samples': 10},
        {'detections': 2},
        {'status': 7},
        {'errors': 1},
        {'frequency_mhz': 2412},
    ],
)
def test_reject_bad_summary(changes):
    r, f = create(changes)
    with pytest.raises(ProtocolError):
        run_pipeline(r, 2, 257)
    assert r.failed
    assert b'DETPIPEGET\n' not in f.writes


def test_retained_crc_failure():
    r, _ = create(bad_crc=True)
    with pytest.raises(ProtocolError, match='CRC'):
        run_pipeline(r, 2, 257)
    assert r.failed


def test_error_end_consumed_without_retrieval():
    r, f = create({'status': 1, 'errors': 1}, errors=b'ERR capture_memory 0\n')
    s, c = run_pipeline(r, 2, 257)
    assert s['status'] == 1 and c is None and not r.failed
    assert b'DETPIPEGET\n' not in f.writes


def test_candidate3_selected_and_reported():
    r, f = create(kernel=3)
    s, c = run_pipeline(r, 2, 257, kernel=3)
    assert s['kernel'] == 3 and c is not None
    assert f.writes[0] == b'PIPEKERNEL 3\n'


def test_bad_kernel_never_writes():
    r, f = create()
    with pytest.raises(ValueError):
        run_pipeline(r, 2, 257, kernel=2)
    assert not f.writes


@pytest.mark.parametrize('readback', ['PIPEKERNEL 3', 'PIPEKERNEL 0'])
def test_optimized_selectors_and_kernel_readback(readback):
    r, f = create({'acquisition_option': 3, 'clear_option': 1}, kernel=3)
    r.info = {'caps': ['ACQOPT', 'CLEAROPT', 'PIPEKERNEL']}
    old = bytes(f.data)
    prefix = b'OK\nACQOPT 3\nOK\nCLEAROPT 1\nPIPEKERNEL 3\n'
    f.data = bytearray(prefix + readback.encode() + b'\n' + old[len(b'PIPEKERNEL 3\n') :])
    if readback != 'PIPEKERNEL 3':
        with pytest.raises(ProtocolError, match='readback'):
            run_pipeline(r, 2, 257, kernel=3, optimized=True)
        assert not any(b'DETPIPE1 ' in x for x in f.writes)
    else:
        s, c = run_pipeline(r, 2, 257, kernel=3, optimized=True)
        assert s['acquisition_policies']['CLEAROPT']['returned'] == 1
        assert s['kernel_requested'] == s['kernel_returned'] == 3
        assert s['nominal_analyzed_duty_percent'] > s['nominal_decision_duty_percent']
        assert c.crc_ok


@pytest.mark.parametrize('field', ['acquisition_option', 'clear_option'])
@pytest.mark.parametrize('bad', [None, 0, True, '3'])
def test_optimized_summary_policy_must_match(field, bad):
    changes = {'acquisition_option': 3, 'clear_option': 1}
    changes[field] = bad
    r, f = create(changes, kernel=3)
    r.info = {'caps': ['ACQOPT', 'CLEAROPT']}
    old = bytes(f.data)
    f.data = bytearray(
        b'OK\nACQOPT 3\nOK\nCLEAROPT 1\nPIPEKERNEL 3\nPIPEKERNEL 3\n'
        + old[len(b'PIPEKERNEL 3\n') :]
    )
    if bad is None:
        f.data = bytearray(bytes(f.data).replace(f', "{field}": null'.encode(), b''))
    with pytest.raises(ProtocolError, match=field):
        run_pipeline(r, 2, 257, kernel=3, optimized=True)
    assert r.failed
    assert b'DETPIPEGET\n' not in f.writes


def test_supported_baseline_summary_must_match_restored_policy():
    r, f = create({'acquisition_option': 3, 'clear_option': 0})
    r.info = {'caps': ['ACQOPT', 'CLEAROPT']}
    f.data = bytearray(b'OK\nACQOPT 0\nOK\nCLEAROPT 0\n' + f.data)
    with pytest.raises(ProtocolError, match='acquisition_option'):
        run_pipeline(r, 2, 257)
    assert r.failed
    assert b'DETPIPEGET\n' not in f.writes


@pytest.mark.parametrize('option,n', [(0, 257), (1, 257), (0, 16380), (1, 16380)])
def test_copy_policy_and_fused_summary(option, n):
    changes = dict(
        copy_option=option,
        fused_active=int(option == 1 and n == 16380),
        retained_samples=0,
        total_samples=17 * n,
        analyzed_samples=17 * (n // 64) * 64,
    )
    r, f = create(changes)
    r.info = {'caps': ['PIPECOPY']}
    f.data = bytearray(
        f'PIPECOPY {option}\nPIPECOPY {option}\n'.encode()
        + bytes(f.data).replace(b'BEGIN 2 257 ', f'BEGIN 2 {n} '.encode())
    )
    s, c = run_pipeline(r, 2, n, copy_option=option)
    assert c is None and s['copy_policy']['returned'] == option
    assert s['fused_active'] == int(option == 1 and n == 16380)


@pytest.mark.parametrize(
    'changes',
    [
        {},
        {'copy_option': 0, 'fused_active': 0},
        {'copy_option': 1, 'fused_active': 1},
        {'copy_option': True, 'fused_active': 0},
        {'copy_option': 1, 'fused_active': False},
    ],
)
def test_reject_copy_summary_mismatch(changes):
    r, f = create(changes)
    r.info = {'caps': ['PIPECOPY']}
    f.data = bytearray(b'PIPECOPY 1\nPIPECOPY 1\n' + f.data)
    with pytest.raises(ProtocolError, match='copy_option/fused_active'):
        run_pipeline(r, 2, 257, copy_option=1)
    assert r.failed and b'DETPIPEGET\n' not in f.writes


@pytest.mark.parametrize('reply', [b'ERR unsupported\n', b'PIPECOPY 1\nPIPECOPY 0\n'])
def test_reject_copy_selector(reply):
    r, f = create()
    r.info = {'caps': ['PIPECOPY']}
    f.data = bytearray(reply + f.data)
    with pytest.raises(ProtocolError, match='PIPECOPY'):
        run_pipeline(r, 2, 257, copy_option=1)
    assert r.failed and not any(b'DETPIPE1 ' in x for x in f.writes)


def test_copy_requires_cap_and_none_never_probes():
    r, f = create()
    with pytest.raises(ProtocolError, match='capability'):
        run_pipeline(r, 2, 257, copy_option=1)
    assert not f.writes
    run_pipeline(r, 2, 257, copy_option=None)
    assert not any(b'PIPECOPY' in x for x in f.writes)


@pytest.mark.parametrize('bad', [True, 2, '1'])
def test_copy_argument_rejected_before_commands(bad):
    r, f = create()
    with pytest.raises(ValueError):
        run_pipeline(r, 2, 257, copy_option=bad)
    assert not f.writes
