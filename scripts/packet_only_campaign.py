"""Single-board finite packet-only prototype controls; dry-run unless --run.

Requires separately reviewed/flashed esp32-packet-only-bounded-v1finish. Never flashes.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from nrf_tx.rf_tx import Transmitter

from sdr_research.packet_only import INFO, collect, validate_plan
from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json

from .four_receiver_packets import calibration, check_calibration, configuration, saved_config


def add_exception_note(primary, note):
    """Best-effort diagnostics, never replace the primary failure (Python 3.10+)."""
    try:
        add_note = getattr(primary, 'add_note', None)
        if callable(add_note):
            add_note(note)
        else:
            # 3.10 lacks add_note; preserve diagnostics for callers without relying
            # on interpreter traceback rendering or an available exception method.
            notes = list(getattr(primary, '__notes__', ()))
            notes.append(note)
            primary.__notes__ = notes
    except BaseException:
        pass


def validate_source(start, final, config):
    for state in (start, final):
        if (
            state.get('version') != '0.2.2'
            or state.get('healthy') is not True
            or state.get('errors') != 0
            or state.get('timing_saturated') is not False
            or saved_config(state) != config
        ):
            raise ValueError('Unqualified source version/health/configuration')
    counters = ('attempted', 'completed', 'scheduled', 'missed_slots')
    if start.get('running') is not True or any(
        type(start.get(k)) is not int or start[k] != 0 for k in counters
    ):
        raise ValueError('Fresh source run not established')
    if final.get('running') is not False or final['uptime_ms'] < start['uptime_ms']:
        raise ValueError('Source still running or reset')
    if any(type(final.get(k)) is not int or final[k] < 0 for k in counters):
        raise ValueError('Invalid source counters')
    if (
        not final['completed']
        or final['completed'] != final['attempted']
        or final['scheduled'] != final['attempted'] + final['missed_slots']
    ):
        raise ValueError('Incomplete or inconsistent transmission denominator')
    times = [
        start.get('elapsed_us'),
        final.get('first_end_us'),
        final.get('last_end_us'),
        final.get('elapsed_us'),
    ]
    if (
        any(type(t) is not int or t < 0 for t in times)
        or not times[0] < times[1] <= times[2] <= times[3]
    ):
        raise ValueError('Invalid source run/completion ordering')
    return final['completed']


def packet_recovery(conditions, source_start, source_final, config):
    if [c['condition'] for c in conditions] != ['OFF', 'ON']:
        raise ValueError('Complete OFF then ON conditions required')
    off, on = conditions
    if any(c['stream']['status'] != 'verified' for c in conditions):
        raise ValueError('Unverified packet-only telemetry')
    if off['stream']['packets']:
        raise ValueError('Source-OFF accepted packets invalidate attribution')
    completed = validate_source(source_start, source_final, config)
    packets = on['stream']['packets']
    sequences = {p['source_sequence'] for p in packets}
    if any(seq >= completed for seq in sequences):
        raise ValueError('Packet outside completed source run')
    return dict(
        unique_packets=len(sequences),
        accepted_observations=len(packets),
        duplicate_observations=len(packets) - len(sequences),
        completed_transmissions=completed,
        attempted_transmissions=source_final['attempted'],
        recovery_percent=100 * len(sequences) / completed,
        source_off_packets=0,
        skipped_slots=on['stream']['end']['skipped'],
        busy_candidates=on['stream']['end']['busy'],
        incomplete_candidates=on['stream']['end']['incomplete'],
        output_drops=on['stream']['end']['output_drops'],
        note='Single-board delivered known RFTX16 packets / all completed source transmissions '
        'in this finite source run, including startup and slack. Not continuous capture, '
        'general packet support, or an equal-condition comparison to sparse raw controls. '
        'Candidate counters cannot identify how many unique RF packets were missed.',
    )


def complete_end_before_source_deadline(start_host_before_ns, end_host_ns, duration_ms):
    if any(type(v) is not int or v < 0 for v in (start_host_before_ns, end_host_ns, duration_ms)):
        raise ValueError('Invalid host/source timing evidence')
    return start_host_before_ns <= end_host_ns < start_host_before_ns + duration_ms * 1000000


def run(
    radio,
    tx,
    output,
    count=128,
    period_us=10000,
    cap=16,
    source_duration_ms=3000,
    power_dbm=0,
    off_only=False,
):
    validate_plan(count, period_us, cap)
    config = configuration(power_dbm)
    if (
        type(source_duration_ms) is not int
        or not 1000 <= source_duration_ms <= 16000
        or source_duration_ms * 1000 < count * period_us + 1000000
    ):
        raise ValueError('Source duration must be 1..16 s and include at least 1 s planned slack')
    report = dict(
        status='running',
        conditions=[],
        provenance=dict(
            host_sha256={
                str(p.name): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (Path(__file__), Path(__file__).parents[1] / 'sdr_research/packet_only.py')
            },
            expected_firmware_variant='esp32-packet-only-bounded-v1finish',
            firmware_app_hash='Not queried; integrator must retain independently verified flashed app hash',
            source_evidence='Aggregate completed counters only; no source event-level trace',
        ),
        plan=dict(
            count=count,
            period_us=period_us,
            cap=cap,
            source_duration_ms=source_duration_ms,
            expected_config=config,
            off_only=off_only,
            queue='none; synchronous acquisition/decode/output',
        ),
    )
    old = None
    provisional_analysis = None

    def save():
        atomic_write_json(output / 'results.json', report)

    try:
        tx.stop()
        report['source_before'] = tx.status()
        if (
            report['source_before']['running']
            or report['source_before']['healthy'] is not True
            or report['source_before'].get('version') != '0.2.2'
            or report['source_before'].get('errors') != 0
            or report['source_before'].get('timing_saturated') is not False
        ):
            raise ValueError('Source OFF/health not established')
        old = saved_config(report['source_before'])
        info = radio.connect()
        report['device'] = info
        version = json.loads(info['version'].removeprefix('VERSION '))
        if (
            version.get('firmware_variant') != 'esp32-packet-only-bounded-v1finish'
            or 'PKTONLY' not in info['caps']
        ):
            raise ValueError('Wrong packet-only candidate firmware')
        if radio.command('PKTONLY?') != INFO:
            raise ValueError('Unexpected packet-only contract')
        radio.configure(2440, 16000000, 12, 60, 10)
        report['calibration_before'] = calibration([radio], 'campaign-before')
        tx.configure(**config)
        for condition in ('OFF',) if off_only else ('OFF', 'ON'):
            row = dict(condition=condition, status='running')
            report['conditions'].append(row)
            row['calibration_before'] = calibration([radio], condition + '-before')
            if condition == 'ON':
                report['source_start_host_before_ns'] = time.monotonic_ns()
                report['source_start'] = tx.start(count=20000, duration_ms=source_duration_ms)
                report['source_start_host_after_ns'] = time.monotonic_ns()
            else:
                if tx.status()['running']:
                    raise ValueError('Source OFF control not stopped')
            save()
            with (output / f'{condition.lower()}.wire.txt').open('x') as wire:

                def retain(line):
                    wire.write(line + '\n')
                    wire.flush()

                row['host_collect_start_ns'] = time.monotonic_ns()
                row['stream'] = collect(radio, count, period_us, cap, on_line=retain)
                row['host_collect_end_ns'] = time.monotonic_ns()
            row['calibration_after'] = calibration([radio], condition + '-after')
            check_calibration(row['calibration_before'], row['calibration_after'])
            if condition == 'OFF' and row['stream']['packets']:
                raise ValueError('Source-OFF accepted packets invalidate attribution')
            if condition == 'ON':
                deadline = time.monotonic() + source_duration_ms / 1000 + 3
                while True:
                    final = tx.status()
                    if not final['running']:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Source finite stop not observed')
                    time.sleep(0.05)
                report['source_final'] = final
                if (
                    type(final.get('elapsed_us')) is not int
                    or final['elapsed_us'] < source_duration_ms * 1000
                ):
                    raise ValueError('Source ended before requested duration')
                report['source_stop_observed_host_ns'] = time.monotonic_ns()
                latest_duration_deadline = (
                    report['source_start_host_after_ns'] + source_duration_ms * 1000000
                )
                row['collector_finished_after_latest_source_duration_deadline'] = (
                    row['host_collect_end_ns'] > latest_duration_deadline
                )
                # Conservative bound: START can execute anytime after host send.
                # Complete END delivery, not firmware pre-send session_us, must fit.
                row['collector_finished_before_earliest_source_deadline'] = (
                    complete_end_before_source_deadline(
                        report['source_start_host_before_ns'],
                        row['host_collect_end_ns'],
                        source_duration_ms,
                    )
                )
                if not row['collector_finished_before_earliest_source_deadline']:
                    raise ValueError('Complete END delivery did not precede source duration bound')
            row['status'] = 'verified'
            save()
        report['calibration_after'] = calibration([radio], 'campaign-after')
        check_calibration(report['calibration_before'], report['calibration_after'])
        if not off_only:
            provisional_analysis = packet_recovery(
                report['conditions'], report['source_start'], report['source_final'], config
            )
        report['status'] = 'passed-source-off-control' if off_only else 'passed'
    except BaseException as exc:
        if report['conditions'] and report['conditions'][-1]['status'] == 'running':
            report['conditions'][-1].update(status='failed', error=repr(exc))
        report.update(status='failed', error=repr(exc))
        raise
    finally:
        primary = sys.exc_info()[1]
        failures = []
        try:
            report['source_stop'] = tx.stop()
            if report['source_stop']['running']:
                raise ValueError('Source STOP not confirmed')
            if old is not None:
                report['source_restored'] = tx.configure(**old)
                if saved_config(report['source_restored']) != old:
                    raise ValueError('Source restore mismatch')
        except BaseException as exc:
            failures.append(repr(exc))
        raw_serial = getattr(radio, 'serial', None)
        try:
            radio.close()
        except BaseException as exc:
            failures.append(repr(exc))
        finally:
            if raw_serial is not None:
                try:
                    raw_serial.close()
                except BaseException as exc:
                    failures.append(repr(exc))
        if failures:
            report.update(status='failed', cleanup_errors=failures)
        if report['status'] == 'passed' and provisional_analysis is not None:
            report['analysis'] = provisional_analysis
        try:
            save()
        except BaseException as exc:
            report.pop('analysis', None)
            report.update(status='failed', receipt_error=repr(exc))
            if primary is None:
                raise
            add_exception_note(primary, 'Final receipt save failed: ' + repr(exc))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--tx-serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--count', type=int, default=128)
    parser.add_argument('--period-us', type=int, default=10000)
    parser.add_argument('--cap', type=int, default=16)
    parser.add_argument('--source-duration-ms', type=int, default=3000)
    parser.add_argument('--power-dbm', type=int, choices=(-20, -16, -12, -8, -4, 0), default=0)
    parser.add_argument('--off-only', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    try:
        validate_plan(args.count, args.period_us, args.cap)
        if (
            not 1000 <= args.source_duration_ms <= 16000
            or args.source_duration_ms * 1000 < args.count * args.period_us + 1000000
        ):
            raise ValueError('Source duration needs 1 s planned slack and 16 s maximum')
    except ValueError as exc:
        parser.error(str(exc))
    if not args.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    count=args.count,
                    period_us=args.period_us,
                    cap=args.cap,
                    source_duration_ms=args.source_duration_ms,
                    off_only=args.off_only,
                    source_config=configuration(args.power_dbm),
                    note='One reviewed prototype board only. No serial opened or firmware flashed.',
                )
            )
        )
        return 0
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    with Transmitter(serial_number=args.tx_serial) as tx:
        report = run(
            Radio(args.port),
            tx,
            args.output,
            args.count,
            args.period_us,
            args.cap,
            args.source_duration_ms,
            args.power_dbm,
            args.off_only,
        )
    print(json.dumps(dict(status=report['status'], analysis=report.get('analysis'))))
    return 0 if report['status'] in ('passed', 'passed-source-off-control') else 1


if __name__ == '__main__':
    raise SystemExit(main())
