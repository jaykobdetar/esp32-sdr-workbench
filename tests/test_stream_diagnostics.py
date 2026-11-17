"""No-hardware failure diagnostics and bounded same-descriptor recovery."""

import errno
import json
from types import SimpleNamespace

import pytest

from sdr_research import stream_diagnostics as m


class Clock:
    now = 100.0

    def monotonic(self):
        return self.now

    def monotonic_ns(self):
        return int(self.now * 1e9)


class Port:
    is_open = True
    timeout = 0.1
    write_timeout = 3
    dtr = False
    rts = False

    def __init__(self, clock):
        self.clock = clock
        self.data = bytearray(b'private tail\n')
        self.writes = []

    def fileno(self):
        return 42

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, n):
        self.clock.now += 0.01
        raw = bytes(self.data[:n])
        del self.data[:n]
        return raw

    def write(self, raw):
        self.writes.append(raw)
        if b'SYNC ' in raw:
            marker = raw.split(b'SYNC ')[1].split(b'\n')[0]
            self.data.extend(b'SYNC ' + marker + b'\n')
        elif raw == b'CLOCK?\n':
            self.data.extend(b'CLOCK 9000000\n')
        elif raw == b'CALHASH?\n':
            self.data.extend(
                (
                    'CALHASH '
                    + json.dumps(
                        dict(
                            version=1,
                            algorithm='sha256',
                            bytes=1904,
                            device_us=9000001,
                            sha256='a' * 64,
                        )
                    )
                    + '\n'
                ).encode()
            )
        return len(raw)

    def close(self):
        pytest.fail('Diagnostic closed descriptor')

    def open(self):
        pytest.fail('Diagnostic reopened descriptor')

    def flush(self):
        pytest.fail('Diagnostic used unbounded tcdrain')


def test_same_fd_success_does_not_clear_failure(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(m, 'time', clock)
    monkeypatch.setattr(m, 'serial_error_counts', lambda p: {'status': 'unsupported'})

    # Protocol's _line shares the time module separately; use a deterministic fake.
    def line(self, deadline):
        raw = bytearray()
        while clock.now < deadline:
            b = self.serial.read(1)
            if b == b'\n':
                return raw.decode()
            raw.extend(b)
        raise TimeoutError('deadline')

    monkeypatch.setattr(m.Radio, '_line', line)
    port = Port(clock)
    r = SimpleNamespace(port='/dev/mock', baud=1000000, serial=port, failed=True)
    result = m.diagnose_failed_stream(
        r, previous_record={'trigger_us': 8000000}, calibration_before={'sha256': 'a' * 64}
    )
    assert result['status'] == 'diagnosed-rejected-stream'
    assert result['tail_hex'] == b'private tail\n'.hex()
    assert result['same_serial_descriptor'] and result['fd'] == 42
    assert result['calibration_hash_unchanged']
    assert not result['clock_regressed_from_last_valid_trigger']
    assert r.failed and port.is_open and not port.dtr and not port.rts


@pytest.mark.parametrize(
    'field,value',
    [
        ('is_open', False),
        ('timeout', None),
        ('timeout', 1),
        ('write_timeout', None),
        ('write_timeout', 4),
    ],
)
def test_unsafe_transport_skipped_without_io(field, value):
    port = SimpleNamespace(is_open=True, timeout=0.1, write_timeout=3)
    setattr(port, field, value)
    assert m.diagnose_failed_stream(SimpleNamespace(serial=port))['status'] == 'skipped'


def test_unsupported_ioctl_is_not_zero_errors(monkeypatch):
    import fcntl
    import termios

    monkeypatch.setattr(termios, 'TIOCGICOUNT', 123, raising=False)

    def unsupported(*a):
        raise OSError(errno.ENOTTY, 'unsupported')

    monkeypatch.setattr(fcntl, 'ioctl', unsupported)
    result = m.serial_error_counts(SimpleNamespace(fileno=lambda: 42))
    assert result['status'] == 'unsupported' and 'counters' not in result


def test_observed_ioctl_preserves_all_named_counters(monkeypatch):
    import fcntl
    import termios

    monkeypatch.setattr(termios, 'TIOCGICOUNT', 123, raising=False)

    def ioctl(fd, request, data, mutate):
        assert fd == 42 and request == 123 and mutate
        for i in range(20):
            data[i] = i

    monkeypatch.setattr(fcntl, 'ioctl', ioctl)
    result = m.serial_error_counts(SimpleNamespace(fileno=lambda: 42))
    assert result['status'] == 'observed'
    assert result['counters']['frame'] == 6 and result['counters']['buf_overrun'] == 10


def test_tail_and_sync_deadlines_bounded_on_silent_port(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(m, 'time', clock)
    monkeypatch.setattr(m, 'serial_error_counts', lambda p: {'status': 'unsupported'})
    port = Port(clock)
    port.data = bytearray(b'\xff' * 6000)

    def silent_write(raw):
        port.writes.append(raw)
        return len(raw)

    port.write = silent_write

    def line(self, deadline):
        clock.now = deadline
        raise TimeoutError('silent')

    monkeypatch.setattr(m.Radio, '_line', line)
    result = m.diagnose_failed_stream(
        SimpleNamespace(port='/dev/mock', baud=1000000, serial=port, failed=True)
    )
    assert result['tail_bytes'] <= 4096 and len(result['tail_hex']) <= 8192
    assert result['status'] == 'diagnostic-failed' and clock.now <= 105.25
