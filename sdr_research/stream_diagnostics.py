"""Private, bounded post-failure diagnostics. Never validate a rejected stream."""

import json
import math
import re
import time

from .protocol import ProtocolError, Radio


def serial_error_counts(port):
    """Read Linux TIOCGICOUNT if exposed; unsupported is not a zero-error result."""
    try:
        import array
        import fcntl
        import termios

        request = getattr(termios, 'TIOCGICOUNT', None)
        if request is None:
            return dict(status='unsupported', reason='TIOCGICOUNT unavailable')
        fd = port.fileno()
        if type(fd) is not int or fd < 0:
            return dict(status='unsupported', reason='No real open file descriptor')
        counters = array.array('i', [0] * 20)
        fcntl.ioctl(fd, request, counters, True)
        names = (
            'cts',
            'dsr',
            'rng',
            'dcd',
            'rx',
            'tx',
            'frame',
            'overrun',
            'parity',
            'brk',
            'buf_overrun',
        )
        return dict(
            status='observed',
            host_monotonic_ns=time.monotonic_ns(),
            counters=dict(zip(names, counters[: len(names)], strict=True)),
        )
    except (ImportError, AttributeError, OSError, TypeError, ValueError) as error:
        return dict(
            status='unsupported', reason=type(error).__name__, errno=getattr(error, 'errno', None)
        )


def diagnose_failed_stream(radio, *, previous_record=None, calibration_before=None):
    """After worker completion only: same fd, finite timeouts, no reopen/reset.

    Best effort tail + exact nonce synchronization + read-only CLOCK/CALHASH.
    The original Radio remains failed even if this separate diagnostic succeeds.
    No .flush() is used here: tcdrain has no portable deadline.
    """
    result = dict(status='skipped', note='Diagnostic only; failed stream remains rejected.')
    port = getattr(radio, 'serial', None)
    if port is None or getattr(port, 'is_open', False) is not True:
        result['reason'] = 'No verified open serial descriptor'
        return result
    for name, maximum in (('timeout', 0.25), ('write_timeout', 3.0)):
        value = getattr(port, name, None)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
            result['reason'] = f'{name} does not meet bounded diagnostic requirement'
            return result
    # Five-second logical budget, plus at most one in-flight write (<=3s)
    # or read (<=.25s). Never alter live port timeout or modem-control settings.
    try:
        fd = port.fileno()
        if type(fd) is not int or fd < 0:
            raise ValueError('Invalid descriptor')
        result.update(
            status='attempted',
            fd=fd,
            same_serial_descriptor=True,
            started_host_monotonic_ns=time.monotonic_ns(),
        )
        result['serial_counts'] = serial_error_counts(port)
        deadline = time.monotonic() + 5
        tail_deadline = time.monotonic() + 0.25
        tail = bytearray()
        try:
            while len(tail) < 4096 and time.monotonic() < tail_deadline:
                waiting = port.in_waiting
                if type(waiting) is not int or waiting < 0:
                    raise ValueError('Invalid serial queue length')
                tail.extend(port.read(min(max(waiting, 1), 4096 - len(tail))))
        except Exception as error:
            result['tail_error'] = type(error).__name__
        result.update(tail_hex=tail.hex(), tail_bytes=len(tail))
        fresh = Radio(radio.port, baud=radio.baud, transport=port)

        def write(data):
            if time.monotonic() >= deadline:
                raise TimeoutError('Diagnostic deadline')
            if port.fileno() != fd or port.is_open is not True:
                raise RuntimeError('Original descriptor no longer open')
            if port.write(data) != len(data):
                raise ProtocolError('Incomplete diagnostic command write')

        marker = f'SYNC {time.monotonic_ns()}'
        write(('\nSTOP\nRELEASE\n' + marker + '\n').encode('ascii'))
        synchronized = False
        while time.monotonic() < deadline:
            try:
                if fresh._line(deadline) == marker:
                    synchronized = True
                    break
            except ProtocolError:
                continue
        if not synchronized:
            raise TimeoutError('Diagnostic nonce synchronization failed')
        result['synchronized'] = True
        write(b'CLOCK?\n')
        fields = fresh._line(deadline).split()
        if len(fields) != 2 or fields[0] != 'CLOCK' or not fields[1].isdigit():
            raise ProtocolError('Invalid diagnostic clock')
        result['clock_after_us'] = int(fields[1])
        result['clock_host_monotonic_ns'] = time.monotonic_ns()
        if previous_record is not None:
            result['last_valid_trigger_us'] = previous_record['trigger_us']
            result['clock_regressed_from_last_valid_trigger'] = (
                int(fields[1]) < previous_record['trigger_us']
            )
        write(b'CALHASH?\n')
        line = fresh._line(deadline)
        if not line.startswith('CALHASH '):
            raise ProtocolError('Invalid diagnostic calibration reply')
        value = json.loads(line[8:])
        if (
            not isinstance(value, dict)
            or value.get('version') != 1
            or value.get('algorithm') != 'sha256'
            or value.get('bytes') != 1904
            or type(value.get('device_us')) is not int
            or value['device_us'] < 0
            or not isinstance(value.get('sha256'), str)
            or re.fullmatch('[0-9a-f]{64}', value['sha256']) is None
        ):
            raise ProtocolError('Invalid diagnostic calibration fields')
        result['calibration_after'] = {key: value[key] for key in ('bytes', 'device_us', 'sha256')}
        if calibration_before is not None:
            result['calibration_hash_unchanged'] = value['sha256'] == calibration_before['sha256']
        result['status'] = 'diagnosed-rejected-stream'
    except Exception as error:
        result.update(status='diagnostic-failed', error_type=type(error).__name__)
    finally:
        result['finished_host_monotonic_ns'] = time.monotonic_ns()
    return result
