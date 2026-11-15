"""Finite 2–4 receiver packet-only controls. Dry-run unless --run; never flashes."""

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nrf_tx.rf_tx import Transmitter

from sdr_research.packet_only import INFO, air_crc, collect, known_payload, validate_plan
from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json

from .four_receiver_packets import calibration, check_calibration, configuration, saved_config
from .packet_only_campaign import complete_end_before_source_deadline, validate_source


def plan_check(receivers, count, period_us, cap, duration_ms, stagger_ms):
    validate_plan(count, period_us, cap)
    if type(receivers) is not int or not 2 <= receivers <= 4:
        raise ValueError('Two to four distinct receivers required')
    if type(stagger_ms) is not int or not 0 <= stagger_ms <= 250:
        raise ValueError('Host-only stagger must be 0..250 ms')
    if (
        type(duration_ms) is not int
        or not 1000 <= duration_ms <= 16000
        or duration_ms * 1000 < count * period_us + (receivers - 1) * stagger_ms * 1000 + 1000000
    ):
        raise ValueError(
            'Finite source duration must include admission, host stagger and 1 s slack'
        )


def summarize(rows, start, final, config, count):
    if any(type(r.get('receiver')) is not int or not 0 <= r['receiver'] < count for r in rows):
        raise ValueError('Invalid receiver index')
    if len(rows) != count * 2:
        raise ValueError('Missing receiver condition')
    completed = validate_source(start, final, config)
    union, observations, per_board = {}, 0, []
    for receiver in range(count):
        selected = [r for r in rows if r['receiver'] == receiver]
        if [r['condition'] for r in selected] != ['OFF', 'ON']:
            raise ValueError('Every receiver needs OFF then ON')
        if any(
            r.get('status') != 'verified' or r['stream']['status'] != 'verified' for r in selected
        ):
            raise ValueError('Unverified receiver invalidates entire campaign')
        if selected[0]['stream']['packets']:
            raise ValueError('Source-OFF packets invalidate attribution')
        if any(r['stream']['end']['output_drops'] for r in selected):
            raise ValueError('Output losses invalidate campaign')
        packets = selected[1]['stream']['packets']
        unique = set()
        for packet in packets:
            sequence, payload = packet['source_sequence'], packet['payload']
            if type(sequence) is not int or not 0 <= sequence < completed:
                raise ValueError('Packet outside common completed source run')
            expected = known_payload(sequence)
            if (
                payload != expected.hex()
                or packet['address'] != 'efcdab89c3'
                or packet['air_crc'] != f'{air_crc(expected):04x}'
            ):
                raise ValueError('Invalid known packet contents')
            if sequence in union and union[sequence] != payload:
                raise ValueError('Conflicting payload for source sequence')
            union[sequence] = payload
            unique.add((sequence, payload))
        observations += len(packets)
        per_board.append(
            dict(
                receiver=receiver,
                unique_packets=len(unique),
                observations=len(packets),
                duplicates=len(packets) - len(unique),
                skipped_slots=selected[1]['stream']['end']['skipped'],
                output_drops=selected[1]['stream']['end']['output_drops'],
                incomplete_candidates=selected[1]['stream']['end']['incomplete'],
                busy_candidates=selected[1]['stream']['end']['busy'],
            )
        )
    return dict(
        unique_packets=len(union),
        accepted_observations=observations,
        duplicate_observations=observations - len(union),
        completed_transmissions=completed,
        attempted_transmissions=final['attempted'],
        recovery_percent=100 * len(union) / completed,
        source_off_packets=0,
        per_board=per_board,
        note='Union of exact known sequence/payload observations over all completed transmissions '
        'in one shared finite source run. Aggregate source counters, no source event trace. '
        'Host start delay is not RF synchronization. Not continuous capture or general protocol support.',
    )


def acquire(radios, output, condition, rows, count, period_us, cap, stagger_ms):
    """Join every bounded worker before returning or propagating cancellation."""
    errors = []
    executor = ThreadPoolExecutor(max_workers=len(radios))
    futures = []

    def worker(index, radio, row):
        try:
            time.sleep(index * stagger_ms / 1000)
            row['host_collect_start_ns'] = time.monotonic_ns()
            with (output / f'{condition.lower()}-{index}.wire.txt').open('x') as wire:

                def retain(line):
                    wire.write(line + '\n')
                    wire.flush()

                row['stream'] = collect(radio, count, period_us, cap, on_line=retain)
            row['host_collect_end_ns'] = time.monotonic_ns()
            row['status'] = 'collected'
        except BaseException as exc:
            row.update(status='failed', error=repr(exc))
            raise

    primary = None
    try:
        for index, radio in enumerate(radios):
            row = dict(
                receiver=index,
                condition=condition,
                status='pending',
                host_only_planned_delay_ms=index * stagger_ms,
            )
            rows.append(row)
            futures.append(executor.submit(worker, index, radio, row))
        for future in futures:
            try:
                future.result()
            except BaseException as exc:
                errors.append(repr(exc))
                if primary is None:
                    primary = exc
    except BaseException as exc:
        primary = primary or exc
    finally:
        # Interrupted joins cannot authorize source restoration / receiver close.
        while any(not f.done() for f in futures):
            try:
                for future in futures:
                    if not future.done():
                        future.result()
            except BaseException as exc:
                errors.append(repr(exc))
                primary = primary or exc
        while True:
            try:
                executor.shutdown(wait=True)
                break
            except BaseException as exc:
                errors.append(repr(exc))
                primary = primary or exc
    # Retrieve every sibling's exception even after the first failure.
    for future in futures:
        try:
            future.result()
        except BaseException as exc:
            primary = primary or exc
    if primary is not None:
        primary.add_note('All packet-only receiver workers joined before cleanup')
        raise primary


def run(
    radios,
    tx,
    output,
    count=128,
    period_us=20000,
    cap=16,
    source_duration_ms=5000,
    power_dbm=0,
    stagger_ms=0,
    off_only=False,
):
    plan_check(len(radios), count, period_us, cap, source_duration_ms, stagger_ms)
    if len({id(r) for r in radios}) != len(radios):
        raise ValueError('Duplicate receiver objects')
    ports = [str(Path(r.port).resolve()) for r in radios if getattr(r, 'port', None)]
    if len(set(ports)) != len(ports):
        raise ValueError('Duplicate receiver paths')
    config = configuration(power_dbm)
    report = dict(
        status='running',
        conditions=[],
        devices=[],
        plan=dict(
            receivers=len(radios),
            count=count,
            period_us=period_us,
            cap=cap,
            source_duration_ms=source_duration_ms,
            expected_config=config,
            stagger_ms=stagger_ms,
            off_only=off_only,
        ),
        provenance=dict(
            host_sha256={
                str(path.name): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (
                    Path(__file__),
                    Path(__file__).with_name('packet_only_campaign.py'),
                    Path(__file__).with_name('four_receiver_packets.py'),
                    Path(__file__).parents[1] / 'sdr_research/packet_only.py',
                )
            },
            source_evidence='Aggregate completed counters only; no event-level source trace',
            firmware_app_hash='Integrator independently verifies each image; VERSION is not app hash',
        ),
    )
    old = None
    provisional_analysis = None

    def save():
        atomic_write_json(output / 'results.json', report)

    try:
        tx.stop()
        before = report['source_before'] = tx.status()
        if (
            before.get('running') is not False
            or before.get('version') != '0.2.2'
            or before.get('healthy') is not True
            or before.get('errors') != 0
            or before.get('timing_saturated') is not False
        ):
            raise ValueError('Unqualified or running source')
        old = saved_config(before)
        for radio in radios:
            info = radio.connect()
            report['devices'].append(dict(info, port=getattr(radio, 'port', None)))
            version = json.loads(info['version'].removeprefix('VERSION '))
            if (
                version.get('firmware_variant') != 'esp32-packet-only-bounded-v1finish'
                or 'PKTONLY' not in info['caps']
            ):
                raise ValueError('Unqualified receiver firmware')
            if radio.command('PKTONLY?') != INFO:
                raise ValueError('Unexpected receiver protocol')
            radio.configure(2440, 16000000, 12, 60, 10)
        report['calibration_before'] = calibration(radios, 'campaign-before')
        tx.configure(**config)
        for condition in ('OFF',) if off_only else ('OFF', 'ON'):
            before_cal = calibration(radios, condition + '-before')
            if condition == 'ON':
                report['source_start_host_before_ns'] = time.monotonic_ns()
                report['source_start'] = tx.start(count=20000, duration_ms=source_duration_ms)
                report['source_start_host_after_ns'] = time.monotonic_ns()
            elif tx.status()['running']:
                raise ValueError('Source OFF not stopped')
            save()
            acquire(
                radios, output, condition, report['conditions'], count, period_us, cap, stagger_ms
            )
            after_cal = calibration(radios, condition + '-after')
            check_calibration(before_cal, after_cal)
            for row in [r for r in report['conditions'] if r['condition'] == condition]:
                index = row['receiver']
                row.update(calibration_before=before_cal[index], calibration_after=after_cal[index])
                if condition == 'OFF' and row['stream']['packets']:
                    raise ValueError('Source-OFF packet invalidates campaign')
                if condition == 'ON':
                    row['complete_end_before_source_deadline'] = (
                        complete_end_before_source_deadline(
                            report['source_start_host_before_ns'],
                            row['host_collect_end_ns'],
                            source_duration_ms,
                        )
                    )
                    if not row['complete_end_before_source_deadline']:
                        raise ValueError('Receiver END beyond conservative source deadline')
                row['status'] = 'verified'
            save()
        if not off_only:
            deadline = time.monotonic() + source_duration_ms / 1000 + 3
            while True:
                final = tx.status()
                if not final['running']:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Finite source stop not observed')
                time.sleep(0.05)
            report['source_final'] = final
            report['source_stop_observed_host_ns'] = time.monotonic_ns()
            if (
                type(final.get('elapsed_us')) is not int
                or final['elapsed_us'] < source_duration_ms * 1000
            ):
                raise ValueError('Source stopped early')
            provisional_analysis = summarize(
                report['conditions'], report['source_start'], final, config, len(radios)
            )
        report['calibration_after'] = calibration(radios, 'campaign-after')
        check_calibration(report['calibration_before'], report['calibration_after'])
        report['status'] = 'passed-source-off-control' if off_only else 'passed'
    except BaseException as exc:
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
        for radio in radios:
            raw = getattr(radio, 'serial', None)
            try:
                radio.close()
            except BaseException as exc:
                failures.append(repr(exc))
            finally:
                if raw is not None:
                    try:
                        raw.close()
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
            primary.add_note('Final receipt save failed: ' + repr(exc))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', action='append', required=True)
    p.add_argument('--tx-serial', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--count', type=int, default=128)
    p.add_argument('--period-us', type=int, default=20000)
    p.add_argument('--cap', type=int, default=16)
    p.add_argument('--source-duration-ms', type=int, default=5000)
    p.add_argument('--power-dbm', type=int, choices=(-20, -16, -12, -8, -4, 0), default=0)
    p.add_argument('--stagger-ms', type=int, default=0)
    p.add_argument('--off-only', action='store_true')
    p.add_argument('--run', action='store_true')
    a = p.parse_args()
    try:
        plan_check(len(a.port), a.count, a.period_us, a.cap, a.source_duration_ms, a.stagger_ms)
        if len({str(Path(port).resolve()) for port in a.port}) != len(a.port):
            raise ValueError('Duplicate receiver path')
    except ValueError as exc:
        p.error(str(exc))
    if not a.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    receivers=len(a.port),
                    count=a.count,
                    period_us=a.period_us,
                    cap=a.cap,
                    source_duration_ms=a.source_duration_ms,
                    stagger_ms=a.stagger_ms,
                    off_only=a.off_only,
                    note='No serial opened. Host delay is not RF synchronization.',
                )
            )
        )
        return 0
    os.umask(0o077)
    a.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    with Transmitter(serial_number=a.tx_serial) as tx:
        report = run(
            [Radio(port) for port in a.port],
            tx,
            a.output,
            a.count,
            a.period_us,
            a.cap,
            a.source_duration_ms,
            a.power_dbm,
            a.stagger_ms,
            a.off_only,
        )
    print(json.dumps(dict(status=report['status'], analysis=report.get('analysis'))))
    return 0 if report['status'] in ('passed', 'passed-source-off-control') else 1


if __name__ == '__main__':
    raise SystemExit(main())
