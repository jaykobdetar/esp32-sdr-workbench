import json
from unittest.mock import Mock

import pytest
from nrf_campaigns import serial_nonce_control as control


class Port:
    def __init__(self, replay=False):
        self.pending = bytearray()
        self.replay = replay
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        lines = data.splitlines(keepends=True)
        self.pending.extend(b''.join([lines[0]] * len(lines)) if self.replay else data)
        return len(data)

    def read(self, n):
        result = self.pending[:n]
        del self.pending[:n]
        return bytes(result)


def test_exact_batch():
    port = Port()
    size = control.exchange(port, 123, control.time.monotonic() + 2)
    assert size == len(port.writes[0])
    assert len(port.writes[0].splitlines()) == 16
    assert port.writes[0].splitlines()[-1] == b'SYNC 183'
    assert not port.pending


def test_replay_rejected():
    with pytest.raises(control.RawReplyError, match='mismatch') as error:
        control.exchange(Port(True), 123, control.time.monotonic() + 2)
    assert error.value.raw == b'SYNC 123\n' * 16
    assert error.value.first_mismatch_offset == 16


@pytest.mark.parametrize('nonce,count', [(-1, 1), (2**64, 1), (2**64 - 1, 2), (1, 17), (1, 0)])
def test_limits(nonce, count):
    with pytest.raises(ValueError):
        control.exchange(Port(), nonce, control.time.monotonic() + 2, count)


def test_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(control.serial, 'Serial', Mock(side_effect=AssertionError('hardware')))
    assert (
        control.main(['--port', 'fake', '--tx-serial', 'fake', '--output', str(tmp_path / 'out')])
        == 0
    )
    assert not (tmp_path / 'out').exists()


def test_failure_same_fd_then_close(monkeypatch):
    port = Port(True)
    port.open = lambda: setattr(port, 'is_open', True)
    port.close = Mock()
    monkeypatch.setattr(control.serial, 'Serial', lambda **kwargs: port)
    radio = Mock()
    radio.connect.return_value = {}
    radio.command.return_value = 'CALHASH ' + json.dumps({'sha256': 'a' * 64})
    monkeypatch.setattr(control, 'Radio', lambda *args, **kwargs: radio)
    monkeypatch.setattr(control, 'clock_observation', lambda r: {'device_us': 1})

    def diagnose(r, **kwargs):
        assert r is radio and r.failed is True
        port.close.assert_not_called()
        return {'status': 'diagnosed-rejected-stream'}

    monkeypatch.setattr(control, 'diagnose_failed_stream', diagnose)
    row = control.trial('fake', 1, 25600)
    assert row['status'] == 'failed'
    assert row['validated_response_bytes'] == 0
    assert row['elapsed_seconds'] > 0
    port.close.assert_called_once()


def test_concurrent_and_source_cleanup(tmp_path, monkeypatch):
    import threading

    barrier = threading.Barrier(4, timeout=3)

    def trial(*args):
        barrier.wait()
        return {'status': 'passed'}

    monkeypatch.setattr(control, 'trial', trial)
    tx = Mock()
    tx.status.return_value = {'running': False}
    tx.stop.return_value = {'running': False}
    wrapper = Mock()
    wrapper.__enter__ = Mock(return_value=tx)
    wrapper.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(control, 'Transmitter', lambda **kw: wrapper)
    args = ['--tx-serial', 'fake', '--output', str(tmp_path / 'out'), '--run']
    for i in range(4):
        args += ['--port', f'fake{i}']
    assert control.main(args) == 0
    assert tx.stop.call_count == 2
    assert len(json.loads((tmp_path / 'out/results.json').read_text())['trials']) == 4


@pytest.mark.parametrize('chunk_size', [1, 7, 48, 64, 256])
def test_partial_reads_and_chunk_bound(chunk_size):
    port = Port()
    original = port.read
    requests = []

    def read(n):
        requests.append(n)
        return original(min(n, chunk_size))

    port.read = read
    assert control.exchange(port, 12345678901234567890, control.time.monotonic() + 2) == 416
    assert max(requests) <= 256
    assert len(requests) == 2 if chunk_size == 256 else len(requests) > 2


def test_timeout_retains_partial_block(monkeypatch):
    port = Port()
    original = port.read
    calls = 0

    def read(n):
        nonlocal calls
        calls += 1
        return original(13) if calls == 1 else b''

    port.read = read
    ticks = iter([0, 0.1, 1.1])
    monkeypatch.setattr(control.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(control.RawReplyError, match='timeout') as caught:
        control.exchange(port, 123, 1)
    assert caught.value.raw == b'SYNC 123\nSYNC'
    assert caught.value.first_mismatch_offset == 13


def test_corruption_across_newline_preserves_entire_block():
    port = Port()
    original = port.write

    def write(data):
        n = original(data)
        port.pending[8:12] = b'XXXX'
        return n

    port.write = write
    with pytest.raises(control.RawReplyError, match='mismatch') as caught:
        control.exchange(port, 123, control.time.monotonic() + 2)
    assert len(caught.value.raw) == 144
    assert caught.value.first_mismatch_offset == 8
    assert caught.value.raw[8:12] == b'XXXX'


def test_read_error_retains_prior_chunk():
    port = Port()
    original = port.read
    calls = 0

    def read(n):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError('fake')
        return original(64)

    port.read = read
    with pytest.raises(control.RawReplyError, match='read error') as caught:
        control.exchange(port, 123, control.time.monotonic() + 2)
    assert len(caught.value.raw) == 64
