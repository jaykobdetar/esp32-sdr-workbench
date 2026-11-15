"""Bounded acquisition-free CAPS integrity control. Dry-run unless --run.

Private output contains device identity, calibration hashes and raw failed bytes.
Exact-response validation is not RF coverage or proof of a hardware fault.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import serial
from nrf_tx.rf_tx import Transmitter

from sdr_research.protocol import Radio

LIMIT = 4096


class RawReplyError(RuntimeError):
    def __init__(self, message, raw):
        super().__init__(message)
        self.raw = bytes(raw[:LIMIT])


def read_line(port, deadline):
    """Retain exact failed bytes, bounded; no normalization or resynchronization."""
    raw = bytearray()
    while time.monotonic() < deadline and len(raw) < LIMIT:
        try:
            b = port.read(1)
        except Exception as error:
            raise RawReplyError(f'Read error: {type(error).__name__}', raw) from error
        raw.extend(b)
        if b == b'\n':
            return bytes(raw)
    raise RawReplyError('Reply length limit' if len(raw) >= LIMIT else 'Reply timeout', raw)


def command_raw(port, command, timeout=2.0):
    data = command.encode('ascii') + b'\n'
    sent = port.write(data)
    if sent != len(data):
        raise RawReplyError('Incomplete command write', b'')
    port.flush()
    return read_line(port, time.monotonic() + timeout)


def clock_observation(r):
    before = time.monotonic_ns()
    line = r.command('CLOCK?')
    after = time.monotonic_ns()
    fields = line.split()
    if len(fields) != 2 or fields[0] != 'CLOCK' or not fields[1].isdigit():
        raise ValueError('Invalid CLOCK reply')
    return dict(device_us=int(fields[1]), host_before_ns=before, host_after_ns=after)


def compare_clocks(before, after):
    delta = after['device_us'] - before['device_us']
    lo = (after['host_before_ns'] - before['host_after_ns']) / 1000
    hi = (after['host_after_ns'] - before['host_before_ns']) / 1000
    return dict(
        device_elapsed_us=delta,
        host_elapsed_range_us=[lo, hi],
        clock_regressed=delta < 0,
        elapsed_inconsistent=not lo - 2_000_000 <= delta <= hi + 2_000_000,
        note='Same serial descriptor; regression or large elapsed mismatch indicates reset/clock discontinuity. Consistency alone does not prove no reset.',
    )


def diagnose_same_fd(port, row):
    """Never reopen or change DTR/RTS; save tail before synchronization discards it."""
    d = {'same_serial_descriptor': True, 'fd': port.fileno()}
    row['failure_recovery'] = d
    tail = bytearray()
    until = time.monotonic() + 0.25
    try:
        while len(tail) < LIMIT and time.monotonic() < until:
            tail.extend(port.read(min(max(port.in_waiting, 1), LIMIT - len(tail))))
    except Exception as error:
        d['tail_error'] = repr(error)
    d['tail_hex'] = tail.hex()
    d['tail_bytes'] = len(tail)
    fresh = Radio(row['port'], transport=port)
    try:
        fresh.synchronize()
        d['synchronized'] = True
        d['clock_after'] = clock_observation(fresh)
        if row.get('clock_before'):
            d['clock_comparison'] = compare_clocks(row['clock_before'], d['clock_after'])
        d['calhash_after'] = fresh.command('CALHASH?')
        if row.get('calhash_before'):
            before = json.loads(row['calhash_before'].removeprefix('CALHASH '))
            after = json.loads(d['calhash_after'].removeprefix('CALHASH '))
            d['calibration_hash_unchanged'] = before['sha256'] == after['sha256']
    except Exception as error:
        d['diagnostic_error'] = repr(error)


def trial(port_name, seconds=60.0, target=25600.0):
    validate_limits(seconds, target)
    row = dict(
        port=port_name,
        requested_seconds=seconds,
        target_response_bytes_per_second=target,
        status='started',
        attempts=0,
        complete_responses=0,
        validated_response_bytes=0,
    )
    port = serial.Serial(port=None, baudrate=1000000, timeout=0.05, write_timeout=2, exclusive=True)
    port.dtr = False
    port.rts = False
    port.port = row['port']
    started = None
    try:
        port.open()
        row['opened_fd'] = port.fileno()
        r = Radio(row['port'], transport=port)
        row['info'] = r.connect()
        row['calhash_before'] = r.command('CALHASH?')
        expected = command_raw(port, 'CAPS')
        if expected.decode('ascii', errors='replace').strip().split() != ['CAPS', *r.info['caps']]:
            raise RawReplyError('Learned CAPS differs from connected capabilities', expected)
        row.update(expected_reply_hex=expected.hex(), expected_reply_bytes=len(expected))
        row['clock_before'] = clock_observation(r)
        started = time.monotonic()
        finish = started + seconds
        while time.monotonic() < finish:
            target_start = started + row['validated_response_bytes'] / target
            delay = min(target_start, finish) - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if time.monotonic() >= finish:
                break
            row['attempts'] += 1
            raw = command_raw(port, 'CAPS', timeout=min(2, max(0.1, finish - time.monotonic())))
            row['complete_responses'] += 1
            if raw != expected:
                raise RawReplyError('CAPS exact-response mismatch', raw)
            row['validated_response_bytes'] += len(raw)
        row['elapsed_seconds'] = time.monotonic() - started
        row['actual_validated_bytes_per_second'] = (
            row['validated_response_bytes'] / row['elapsed_seconds']
        )
        row['clock_after'] = clock_observation(r)
        row['clock_comparison'] = compare_clocks(row['clock_before'], row['clock_after'])
        row['calhash_after'] = r.command('CALHASH?')
        row['status'] = 'passed-exact-response-control'
    except BaseException as error:
        row.update(
            status='failed', error=repr(error), failure_host_monotonic_ns=time.monotonic_ns()
        )
        raw = getattr(error, 'raw', b'')
        row['failed_raw_hex'] = bytes(raw[:LIMIT]).hex()
        row['failed_raw_bytes'] = len(raw)
        if started is not None:
            row['elapsed_seconds'] = time.monotonic() - started
            row['actual_validated_bytes_per_second'] = (
                row['validated_response_bytes'] / row['elapsed_seconds']
            )
        if port.is_open:
            diagnose_same_fd(port, row)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            row['cancelled'] = True
    finally:
        port.close()  # Only after same-descriptor diagnostics have completed.
    return row


def validate_limits(seconds, target):
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not 1 <= seconds <= 120
    ):
        raise ValueError('Seconds must be finite and within 1..120')
    if isinstance(target, bool) or not isinstance(target, (int, float)) or not 1 <= target <= 50000:
        raise ValueError('Target bytes per second must be finite and within 1..50000')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', action='append', required=True)
    p.add_argument('--tx-serial', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=60)
    p.add_argument('--target-bytes-per-second', type=float, default=25600)
    p.add_argument('--run', action='store_true')
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        validate_limits(args.seconds, args.target_bytes_per_second)
    except ValueError as error:
        p.error(str(error))
    if not 1 <= len(args.port) <= 4 or len({str(Path(x).resolve()) for x in args.port}) != len(
        args.port
    ):
        p.error('One to four distinct verified receiver ports required')
    if not args.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    receiver_count=len(args.port),
                    seconds_per_receiver=args.seconds,
                    target_response_bytes_per_second=args.target_bytes_per_second,
                    note='Explicit --run required. No acquisition or source transmission. Private output includes device and raw transport diagnostics.',
                )
            )
        )
        return
    os.umask(0o077)
    out = args.output
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = dict(
        status='running',
        note='Acquisition-free CAPS integrity control, not DSTREAM equivalence, RF coverage, or packet recall. Actual response throughput is measured; target throughput is not assumed.',
        source_sha256={
            'scripts/serial_integrity_control.py': hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest()
        },
        trials=[],
    )

    def save():
        tmp = out / 'results.tmp'
        with tmp.open('w') as f:
            json.dump(report, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out / 'results.json')

    try:
        with Transmitter(serial_number=args.tx_serial) as tx:
            report['source_initial_stop'] = tx.stop()
            report['source_initial'] = tx.status()
            if report['source_initial'].get('running') is not False:
                raise RuntimeError('Transmitter did not report stopped')
        save()
        for port_name in args.port:
            row = trial(port_name, args.seconds, args.target_bytes_per_second)
            report['trials'].append(row)
            save()
            print(
                port_name, row['status'], row.get('actual_validated_bytes_per_second'), flush=True
            )
            if row.get('cancelled'):
                break
        report['status'] = (
            'passed'
            if all(r['status'] == 'passed-exact-response-control' for r in report['trials'])
            else 'failed'
        )
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = repr(error)
        raise
    finally:
        try:
            with Transmitter(serial_number=args.tx_serial) as tx:
                report['source_final_stop'] = tx.stop()
                report['source_final'] = tx.status()
                if report['source_final'].get('running') is not False:
                    raise RuntimeError('Final transmitter STOP not verified')
        except Exception as error:
            report['source_final_error'] = repr(error)
            report['status'] = 'failed'
        save()
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
