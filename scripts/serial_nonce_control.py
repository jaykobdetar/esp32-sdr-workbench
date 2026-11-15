"""Concurrent acquisition-free unique SYNC controls. Dry run unless --run."""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import serial
from nrf_campaigns.serial_integrity_control import (
    RawReplyError,
    clock_observation,
    parser,
    read_line,
    validate_limits,
)
from nrf_tx.rf_tx import Transmitter

from sdr_research.protocol import Radio
from sdr_research.stream_diagnostics import diagnose_failed_stream


def exchange(port, nonce, deadline, count=16):
    if type(nonce) is not int or not 0 <= nonce < 2**64:
        raise ValueError('Nonce outside uint64')
    if type(count) is not int or not 1 <= count <= 16 or nonce + 4 * (count - 1) >= 2**64:
        raise ValueError('Invalid bounded batch')
    replies = [f'SYNC {nonce + 4 * i}\n'.encode('ascii') for i in range(count)]
    expected = b''.join(replies)
    # No flush/tcdrain: finite write_timeout bounds the write itself.
    if port.write(expected) != len(expected):
        raise RawReplyError('Incomplete nonce write', b'')
    for reply in replies:
        raw = read_line(port, deadline)
        if raw != reply:
            raise RawReplyError('Unique nonce exact-response mismatch', raw)
    return len(expected)


def trial(port_name, seconds, target, index=0):
    validate_limits(seconds, target)
    row = dict(
        port=port_name,
        status='started',
        attempts=0,
        validated_response_bytes=0,
        requested_seconds=seconds,
        target_response_bytes_per_second=target,
        batch_size=16,
    )
    port = serial.Serial(port=None, baudrate=1000000, timeout=0.05, write_timeout=2, exclusive=True)
    port.dtr = False
    port.rts = False
    port.port = port_name
    radio = None
    start = None
    try:
        port.open()
        radio = Radio(port_name, transport=port)
        row['info'] = radio.connect()
        row['clock_before'] = clock_observation(radio)
        calibration = json.loads(radio.command('CALHASH?').removeprefix('CALHASH '))
        row['calibration_before'] = calibration
        # Distinct lanes for ports and monotonically increasing within each lane.
        nonce = time.monotonic_ns() * 4 + index
        row['first_nonce'] = nonce
        row['workload_started_host_ns'] = time.monotonic_ns()
        start = time.monotonic()
        finish = start + seconds
        while time.monotonic() < finish:
            due = min(finish, start + row['validated_response_bytes'] / target)
            if due > time.monotonic():
                time.sleep(max(0, due - time.monotonic()))
            if time.monotonic() >= finish:
                break
            row['attempts'] += 1
            row['expected_nonce'] = nonce
            row['last_write_started_host_ns'] = time.monotonic_ns()
            size = exchange(port, nonce, time.monotonic() + 2)
            row['last_response_host_ns'] = time.monotonic_ns()
            row['validated_response_bytes'] += size
            nonce += 64
        row['status'] = 'passed'
    except Exception as error:
        row.update(
            status='failed',
            error_type=type(error).__name__,
            error=str(error),
            failure_host_monotonic_ns=time.monotonic_ns(),
            failed_raw_hex=bytes(getattr(error, 'raw', b'')[:4096]).hex(),
        )
        # Measure workload elapsed before potentially slow failure diagnosis.
        if start is not None:
            row['elapsed_seconds'] = time.monotonic() - start
        if radio is not None and port.is_open:
            radio.failed = True
            try:
                row['same_descriptor_diagnostics'] = diagnose_failed_stream(
                    radio,
                    previous_record={'trigger_us': row['clock_before']['device_us']}
                    if 'clock_before' in row
                    else None,
                    calibration_before=row.get('calibration_before'),
                )
            except Exception as diagnostic_error:
                row['same_descriptor_diagnostics'] = dict(
                    status='diagnostic-failed', error_type=type(diagnostic_error).__name__
                )
    finally:
        if start is not None:
            row.setdefault('elapsed_seconds', time.monotonic() - start)
            row['actual_validated_bytes_per_second'] = (
                row['validated_response_bytes'] / row['elapsed_seconds']
            )
        port.close()
    return row


def main(argv=None):
    p = parser()
    p.description = __doc__
    args = p.parse_args(argv)
    try:
        validate_limits(args.seconds, args.target_bytes_per_second)
    except ValueError as error:
        p.error(str(error))
    if not 1 <= len(args.port) <= 4 or len({str(Path(x).resolve()) for x in args.port}) != len(
        args.port
    ):
        p.error('One to four distinct receiver ports required')
    if not args.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    concurrent_receivers=len(args.port),
                    seconds=args.seconds,
                    target_bytes_per_second=args.target_bytes_per_second,
                )
            )
        )
        return 0
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = dict(
        status='running',
        trials=[],
        note='Changing-response acquisition-free control, not RF coverage. Target throughput is not guaranteed.',
        source_sha256={
            str(Path(__file__).name): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        },
    )

    def save():
        temporary = args.output / 'results.tmp'
        with temporary.open('w') as handle:
            json.dump(report, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.output / 'results.json')

    def stop_source(label):
        with Transmitter(serial_number=args.tx_serial) as tx:
            report[label + '_stop'] = tx.stop()
            report[label] = tx.status()
            if report[label].get('running') is not False:
                raise RuntimeError('Transmitter STOP not verified')

    try:
        stop_source('source_initial')
        save()
        with ThreadPoolExecutor(max_workers=len(args.port)) as pool:
            futures = [
                pool.submit(trial, name, args.seconds, args.target_bytes_per_second, i)
                for i, name in enumerate(args.port)
            ]
            for future in futures:
                report['trials'].append(future.result())
                save()
        report['status'] = (
            'passed' if all(r['status'] == 'passed' for r in report['trials']) else 'failed'
        )
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        try:
            stop_source('source_final')
        except Exception as error:
            report.update(status='failed', source_final_error_type=type(error).__name__)
        save()
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
