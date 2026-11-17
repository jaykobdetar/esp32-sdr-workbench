"""Offline acquisition-free control tests; no serial ports opened."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'serial_integrity_control_test',
    Path(__file__).resolve().parents[1] / 'scripts/serial_integrity_control.py',
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Clock:
    now = 100.0

    def monotonic(self):
        return self.now

    def monotonic_ns(self):
        return round(self.now * 1e9)

    def sleep(self, seconds):
        self.now += seconds


class Port:
    def __init__(self, clock, data=b''):
        self.clock, self.data = clock, bytearray(data)
        self.is_open = False
        self.open_calls = self.close_calls = 0
        self.writes = []

    def open(self):
        self.open_calls += 1
        self.is_open = True

    def close(self):
        self.close_calls += 1
        self.is_open = False

    def fileno(self):
        return 42

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, n):
        self.clock.now += 0.01
        result = bytes(self.data[:n])
        del self.data[:n]
        return result

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass


@pytest.mark.parametrize(
    'seconds,target',
    [(0, 25600), (121, 25600), (float('nan'), 1), (1, float('inf')), (1, 0), (1, 50001), (True, 1)],
)
def test_bounds(seconds, target):
    with pytest.raises(ValueError):
        m.validate_limits(seconds, target)


def test_dry_run_has_no_side_effects(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(m, 'Transmitter', lambda **kw: pytest.fail('Opened transmitter'))
    monkeypatch.setattr(m.serial, 'Serial', lambda **kw: pytest.fail('Opened serial'))
    output = tmp_path / 'not-created'
    m.main(['--port', '/dev/mock', '--tx-serial', '0123456789ABCDEF', '--output', str(output)])
    assert not output.exists()
    assert json.loads(capsys.readouterr().out)['mode'] == 'dry-run'


def test_duplicate_port_rejected(tmp_path):
    with pytest.raises(SystemExit):
        m.main(
            [
                '--port',
                '/dev/mock',
                '--port',
                '/dev/mock',
                '--tx-serial',
                '0123456789ABCDEF',
                '--output',
                str(tmp_path / 'out'),
            ]
        )


def test_reader_preserves_exact_bytes_and_bounded_failure(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(m, 'time', clock)
    assert m.read_line(Port(clock, b'CAPS \xff\r\n'), clock.now + 1) == b'CAPS \xff\r\n'
    with pytest.raises(m.RawReplyError) as e:
        m.read_line(Port(clock, b'\xff' * 5000), clock.now + 100)
    assert e.value.raw == b'\xff' * 4096
    with pytest.raises(m.RawReplyError) as e:
        m.read_line(Port(clock, b'partial'), clock.now + 0.2)
    assert e.value.raw == b'partial'


def fake_trial(monkeypatch, fail=False):
    clock = Clock()
    monkeypatch.setattr(m, 'time', clock)
    port = Port(clock)
    monkeypatch.setattr(m.serial, 'Serial', lambda **kw: port)
    radios = []

    class Radio:
        def __init__(self, name, transport):
            assert transport is port
            self.port = name
            self.serial = transport
            self.info = {'caps': ['A', 'B']}
            radios.append(self)

        def connect(self):
            return self.info

        def synchronize(self):
            assert port.is_open and port.open_calls == 1 and port.close_calls == 0
            assert port.dtr is False and port.rts is False
            self.synchronized = True

        def command(self, command):
            assert port.is_open
            if command == 'CLOCK?':
                return f'CLOCK {round(clock.now * 1e6)}'
            assert command == 'CALHASH?'
            return 'CALHASH {"sha256":"same","bytes":1904}'

    monkeypatch.setattr(m, 'Radio', Radio)
    expected = b'CAPS A B\n'
    calls = []

    def raw(p, command, timeout=2):
        assert p is port and command == 'CAPS'
        calls.append(command)
        clock.now += 0.4
        if fail and len(calls) == 2:
            return b'CAPS ' + b'\xff' * 64 + b'\n'
        return expected

    monkeypatch.setattr(m, 'command_raw', raw)
    return port, radios, expected


def test_actual_elapsed_not_requested_denominator(monkeypatch):
    port, radios, expected = fake_trial(monkeypatch)
    row = m.trial('/dev/mock', seconds=1, target=25600)
    assert row['status'] == 'passed-exact-response-control'
    assert row['elapsed_seconds'] == pytest.approx(1.2)
    assert row['validated_response_bytes'] == 3 * len(expected)
    assert row['actual_validated_bytes_per_second'] == pytest.approx(3 * len(expected) / 1.2)
    assert port.open_calls == port.close_calls == 1 and len(radios) == 1


def test_mismatch_keeps_same_descriptor_until_recovery_done(monkeypatch):
    port, radios, expected = fake_trial(monkeypatch, fail=True)
    row = m.trial('/dev/mock', seconds=1, target=25600)
    assert row['status'] == 'failed' and row['validated_response_bytes'] == 0
    assert bytes.fromhex(row['failed_raw_hex']) == b'CAPS ' + b'\xff' * 64 + b'\n'
    assert row['failure_recovery']['same_serial_descriptor']
    assert row['failure_recovery']['calibration_hash_unchanged']
    assert not row['failure_recovery']['clock_comparison']['clock_regressed']
    assert len(radios) == 2 and radios[1].synchronized
    assert port.open_calls == port.close_calls == 1


def test_clock_regression_and_elapsed_discontinuity():
    before = dict(device_us=100000000, host_before_ns=0, host_after_ns=1000)
    after = dict(device_us=1000000, host_before_ns=60000000000, host_after_ns=60000001000)
    assert m.compare_clocks(before, after)['clock_regressed']
    assert m.compare_clocks(before, after)['elapsed_inconsistent']


@pytest.mark.parametrize('where', ['initial', 'trial', 'final'])
def test_source_stop_final_attempt_and_receipt_on_failure(monkeypatch, tmp_path, where):
    calls = []

    class Tx:
        def __init__(self, **kw):
            self.number = len(calls)
            calls.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def stop(self):
            self.stopped = True
            if (where == 'initial' and self.number == 0) or (where == 'final' and self.number == 1):
                raise RuntimeError('injected stop failure')
            return {'running': False}

        def status(self):
            return {'running': False}

    monkeypatch.setattr(m, 'Transmitter', Tx)

    def trial(*a):
        if where == 'trial':
            raise RuntimeError('injected trial failure')
        return {'status': 'passed-exact-response-control'}

    monkeypatch.setattr(m, 'trial', trial)
    out = tmp_path / 'out'
    argv = [
        '--port',
        '/dev/mock',
        '--tx-serial',
        '0123456789ABCDEF',
        '--output',
        str(out),
        '--run',
        '--seconds',
        '1',
    ]
    if where == 'final':
        m.main(argv)
    else:
        with pytest.raises(RuntimeError):
            m.main(argv)
    assert len(calls) == 2 and all(tx.stopped for tx in calls)
    assert json.loads((out / 'results.json').read_text())['status'] == 'failed'
