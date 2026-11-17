"""Bounded raw-snapshot recovery control; NOT continuous reception or timing coverage.

Run with python -m nrf_campaigns.four_receiver_packets. Output is private.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from nrf_tx.rf_tx import Transmitter

from sdr_research.calibration import record_calibration
from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json

from .analyze_nrf_iq import decode, payload

CONFIG = dict(
    frequency_mhz=2440,
    mode_mbps=2,
    power_dbm=-20,
    payload_len=16,
    interval_us=1000,
    jitter_us=113,
    seed=52840,
    burst_count=0,
    burst_gap_us=0,
    hop_every=1,
    hop_list='off',
    payload_hex='off',
)
NOTE = (
    'Unique CRC/address/full-known-payload packets divided by completed source '
    'transmissions during the entire finite ON run. Sparse raw snapshots include '
    'large transfer gaps. This is not nominal RF coverage, continuous reception, '
    'an instantaneous capture-window recall estimate, or Quest compatibility.'
)


POWERS_DBM = (-20, -16, -12, -8, -4, 0)


def configuration(power_dbm=-20):
    if type(power_dbm) is not int or power_dbm not in POWERS_DBM:
        raise ValueError('Unsupported controlled source power')
    return dict(CONFIG, power_dbm=power_dbm)


def saved_config(status):
    result = {key: status[key] for key in CONFIG if key not in ('hop_list', 'payload_hex')}
    result['hop_list'] = ','.join(map(str, status['hop_list'])) or 'off'
    result['payload_hex'] = status['payload_hex'] or 'off'
    return result


def accepted(decoder):
    values = []
    for hit in decoder['full_payload_matches']:
        if all(
            hit.get(k) is True
            for k in ('crc_verified', 'address_verified', 'full_known_payload_match')
        ):
            seq = hit['sequence']
            if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**32:
                raise ValueError('Invalid packet sequence')
            expected = payload(seq, 16)
            for field in ('observed_payload_hex', 'expected_payload_hex'):
                value = hit.get(field)
                if (
                    not isinstance(value, str)
                    or re.fullmatch(r'[0-9a-fA-F]{32}', value) is None
                    or bytes.fromhex(value) != expected
                ):
                    raise ValueError('Inconsistent known-payload evidence')
            values.append(seq)
    return values


def summarize(rows, start, final, receiver_count, expected_config=None, capture_bits=10):
    """Conservative denominator: v0.2.2 sequences count attempted TX from zero."""
    expected_format = capture_format(capture_bits)
    expected_config = configuration() if expected_config is None else expected_config
    if (
        not isinstance(expected_config, dict)
        or configuration(expected_config.get('power_dbm')) != expected_config
    ):
        raise ValueError('Unsupported expected source configuration')
    if type(receiver_count) is not int or not 2 <= receiver_count <= 4:
        raise ValueError('Two to four expected receivers required')
    for state in (start, final):
        if (
            state.get('version') != '0.2.2'
            or state.get('healthy') is not True
            or state.get('errors') != 0
            or state.get('timing_saturated') is not False
        ):
            raise ValueError('Unsupported or unhealthy transmitter accounting')
        if saved_config(state) != expected_config:
            raise ValueError('Source configuration changed')
    if start.get('running') is not True or any(
        type(start.get(key)) is not int or start[key] != 0
        for key in ('attempted', 'completed', 'scheduled', 'missed_slots')
    ):
        raise ValueError('Fresh running source with reset counters required')
    # START calls status() synchronously before returning to radio_task(), but
    # status() computes now_us() - start_us, not the reset elapsed_us variable.
    # Thus elapsed can be nonzero. Bound it by the observed first completion,
    # not an arbitrary interval: the scheduler's initial deadline is start_us.
    times = [
        start.get('elapsed_us'),
        final.get('first_end_us'),
        final.get('last_end_us'),
        final.get('elapsed_us'),
    ]
    if (
        any(type(value) is not int or value < 0 for value in times)
        or not times[0] < times[1] <= times[2] <= times[3]
    ):
        raise ValueError('Inconsistent START and transmission completion times')
    if final.get('running') is not False or final['uptime_ms'] < start['uptime_ms']:
        raise ValueError('Source still running or reset')
    counts = [final[k] for k in ('attempted', 'completed', 'scheduled', 'missed_slots')]
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts):
        raise ValueError('Invalid source counters')
    attempted, completed, scheduled, missed = counts
    if not completed or completed != attempted or scheduled != attempted + missed:
        raise ValueError('Incomplete or inconsistent transmission denominator')
    if any(final[k] < start[k] for k in ('attempted', 'completed', 'scheduled', 'elapsed_us')):
        raise ValueError('Transmitter counters reset')
    per_board = [[] for _ in range(receiver_count)]
    off = []
    observed = {condition: set() for condition in ('OFF', 'ON')}
    for row in rows:
        observed_format = row.get('capture_format')
        settings = row.get('metadata', {}).get('settings')
        if settings is not None and (
            settings.get('bits') != capture_bits or settings.get('rate_hz') != 16000000
        ):
            raise ValueError('Capture format conflicts with stored receiver settings')
        if observed_format is None:
            # Older campaign source fixed 16380 samples; its stored settings
            # still establish component precision and sample rate.
            settings = row.get('metadata', {}).get('settings', {})
            observed_format = capture_format(settings.get('bits'))
            if settings.get('rate_hz') != 16000000:
                raise ValueError('Invalid legacy capture sample rate')
        if observed_format != expected_format:
            raise ValueError('Capture format differs across ON/OFF or from requested format')
        receiver = row.get('receiver')
        if type(receiver) is not int or not 0 <= receiver < receiver_count:
            raise ValueError('Invalid receiver index')
        if row['transport_crc_valid'] is not True:
            raise ValueError('Invalid raw transport')
        seqs = accepted(row['decoder'])
        if row['condition'] not in observed:
            raise ValueError('Unknown source condition')
        observed[row['condition']].add(receiver)
        if row['condition'] == 'OFF':
            off.extend(seqs)
        elif row['condition'] == 'ON':
            if any(seq >= completed for seq in seqs):
                raise ValueError('Packet sequence outside completed source run')
            per_board[row['receiver']].extend(seqs)
        else:
            raise ValueError('Unknown source condition')
    if off:
        raise ValueError('Source-OFF accepted packets invalidate attribution')
    if any(receivers != set(range(receiver_count)) for receivers in observed.values()):
        raise ValueError('Nonempty ON and OFF captures required for every receiver')
    union = set().union(*(set(values) for values in per_board))
    return dict(
        unique_packets=len(union),
        completed_transmissions=completed,
        attempted_transmissions=attempted,
        scheduled_slots=scheduled,
        missed_slots=missed,
        recovery_percent=100 * len(union) / completed,
        per_receiver_unique=[len(set(v)) for v in per_board],
        accepted_observations=sum(map(len, per_board)),
        duplicate_observations=sum(map(len, per_board)) - len(union),
        source_off_packets=0,
        note=NOTE,
    )


def calibration(radios, boundary):
    return [record_calibration({}, r, r.info, boundary, required=True) for r in radios]


def check_calibration(before, after):
    for a, b in zip(before, after, strict=True):
        if a['sha256'] != b['sha256'] or a['bytes'] != b['bytes']:
            raise ValueError('Calibration fingerprint changed')
        if b['device_us'] < a['device_us']:
            raise ValueError('Receiver reset during trial')


def capture_format(bits=10):
    if type(bits) is not int or bits not in (8, 10):
        raise ValueError('Capture bits must be 8 or 10 per component')
    return dict(
        bits_per_component=bits,
        complex_samples=16380,
        sample_rate_hz=16000000,
        packed_payload_bytes=16380 * bits * 2 // 8,
        command=f'CAP{bits * 2}',
        nominal_aperture_us=16380 / 16,
    )


def capture(radio, receiver, index, condition, output):
    c = radio.capture(16380)
    actual_format = capture_format(c.bits)
    if len(c.iq) != 16380 or c.sample_rate_hz != 16000000:
        raise ValueError('Unexpected actual capture length or sample rate')
    if not c.crc_ok:
        raise ValueError('Capture transport CRC failed')
    filename = f'{condition.lower()}-rx{receiver}-{index:03d}.npy'
    np.save(output / filename, c.iq)
    return dict(
        receiver=receiver,
        index=index,
        condition=condition,
        file=filename,
        transport_crc_valid=True,
        host_start_ns=c.monotonic_start_ns,
        host_end_ns=c.monotonic_end_ns,
        firmware_capture_us=c.firmware_capture_us,
        metadata=c.metadata,
        capture_format=actual_format,
        actual_capture_call_us=(c.monotonic_end_ns - c.monotonic_start_ns) / 1000,
    )


def stagger_plan(
    receiver_count, captures, duration_ms, stagger_ms=0, capture_bits=10, acquisition_budget_ms=None
):
    if type(receiver_count) is not int or not 2 <= receiver_count <= 4:
        raise ValueError('Two to four receivers required')
    if type(stagger_ms) is not int or not 0 <= stagger_ms <= 250:
        raise ValueError('Host stagger must be an integer in 0..250 ms')
    if type(captures) is not int or not 1 <= captures <= 32:
        raise ValueError('Captures must be 1..32')
    if type(duration_ms) is not int or not 1000 <= duration_ms <= 30000:
        raise ValueError('Duration must be 1000..30000 ms')
    format_info = capture_format(capture_bits)
    delays = [k * stagger_ms for k in range(receiver_count)]
    # Each completed round must move the raw payload at 1 Mbaud, 8N1,
    # before the next round. Ignore framing/processing overhead: LOWER bound.
    wire_ms = format_info['packed_payload_bytes'] / 100
    last_start_lower_bound = captures * max(delays) + (captures - 1) * wire_ms
    if acquisition_budget_ms is None:
        if last_start_lower_bound >= duration_ms:
            raise ValueError('Even the lower-bound last capture start exceeds source duration')
    elif (
        type(acquisition_budget_ms) is not int
        or not max(delays) < acquisition_budget_ms <= duration_ms
    ):
        raise ValueError(
            'Acquisition budget must exceed all planned delays and not source duration'
        )
    return dict(
        acquisition_budget_ms=acquisition_budget_ms,
        capture_mode='fixed-count' if acquisition_budget_ms is None else 'host-time-budget',
        capture_format=format_info,
        raw_wire_lower_bound_ms=wire_ms,
        stagger_ms=stagger_ms,
        per_receiver_delay_ms=delays,
        captures_per_condition=captures,
        source_duration_ms=duration_ms,
        last_capture_start_lower_bound_ms=last_start_lower_bound,
        note='Host sleep per receiver before each concurrent round, NOT RF synchronization. '
        'UART-based lower bound is not a runtime guarantee. Actual capture calls '
        'may extend beyond the finite source run.',
    )


def delayed_capture(
    radio,
    receiver,
    index,
    condition,
    output,
    delay_ms,
    deadline_bounds=None,
    acquisition_deadline_ns=None,
):
    queued_ns = time.monotonic_ns()
    if delay_ms:
        time.sleep(delay_ms / 1000)
    started_ns = time.monotonic_ns()
    if acquisition_deadline_ns is not None and started_ns >= acquisition_deadline_ns:
        return dict(
            skipped=True,
            receiver=receiver,
            index=index,
            condition=condition,
            reason='Host acquisition budget expired before capture call',
            planned_host_delay_ms=delay_ms,
            host_worker_start_ns=queued_ns,
            host_capture_call_start_ns=started_ns,
        )
    row = capture(radio, receiver, index, condition, output)
    ended_ns = time.monotonic_ns()
    row.update(
        planned_host_delay_ms=delay_ms,
        host_worker_start_ns=queued_ns,
        host_capture_call_start_ns=started_ns,
        host_capture_call_end_ns=ended_ns,
    )
    if deadline_bounds is not None:
        earliest, latest = deadline_bounds
        row['host_duration_deadline_observation'] = dict(
            capture_call_started_after_latest_deadline=started_ns >= latest,
            capture_call_ended_after_latest_deadline=ended_ns >= latest,
            capture_call_start_in_deadline_uncertainty=earliest <= started_ns < latest,
            note='Host duration bounds only, not calibrated RF timestamps; source count limit '
            'or errors may stop it earlier. A pre-deadline call does not prove RF overlap.',
        )
    return row


def run(
    radios,
    tx,
    output,
    captures=8,
    duration_ms=8000,
    *,
    power_dbm=-20,
    stagger_ms=0,
    capture_bits=10,
    acquisition_budget_ms=None,
):
    expected_config = configuration(power_dbm)
    plan = stagger_plan(
        len(radios), captures, duration_ms, stagger_ms, capture_bits, acquisition_budget_ms
    )
    report = dict(
        status='running', captures=[], note=NOTE, expected_config=expected_config, capture_plan=plan
    )
    old = None

    def save():
        atomic_write_json(output / 'results.json', report)

    try:
        tx.stop()
        report['tx_before'] = tx.status()
        if report['tx_before']['running']:
            raise RuntimeError('Source-OFF state not confirmed')
        old = saved_config(report['tx_before'])
        report['devices'] = [r.connect() for r in radios]
        report['calibration_before'] = calibration(radios, 'campaign-before')
        for r in radios:
            r.configure(2440, 16000000, 12, 60, capture_bits)
        tx.configure(**expected_config)
        with ThreadPoolExecutor(len(radios)) as pool:
            for condition in ('OFF', 'ON'):
                boundary = dict(
                    condition=condition, before=calibration(radios, condition + '-before')
                )
                report.setdefault('calibration_boundaries', []).append(boundary)
                deadline_bounds = None
                budget_start_ns = time.monotonic_ns()
                if condition == 'ON':
                    start_call_ns = time.monotonic_ns()
                    budget_start_ns = start_call_ns
                    report['tx_start'] = tx.start(count=20000, duration_ms=duration_ms)
                    start_reply_ns = time.monotonic_ns()
                    deadline_bounds = [
                        start_call_ns + duration_ms * 1000000,
                        start_reply_ns + duration_ms * 1000000,
                    ]
                    report['source_duration_deadline_host_bounds_ns'] = deadline_bounds
                acquisition_deadline_ns = (
                    None
                    if acquisition_budget_ms is None
                    else budget_start_ns + acquisition_budget_ms * 1000000
                )
                rounds_started = 0
                for index in range(captures):
                    if (
                        acquisition_deadline_ns is not None
                        and time.monotonic_ns() >= acquisition_deadline_ns
                    ):
                        break
                    rounds_started += 1
                    futures = [
                        pool.submit(
                            delayed_capture,
                            r,
                            k,
                            index,
                            condition,
                            output,
                            plan['per_receiver_delay_ms'][k],
                            deadline_bounds,
                            acquisition_deadline_ns,
                        )
                        for k, r in enumerate(radios)
                    ]
                    # Collect every worker before propagating an exception.
                    values, errors = [], []
                    for future in futures:
                        try:
                            values.append(future.result())
                        except Exception as exc:
                            errors.append(exc)
                    report['captures'].extend(v for v in values if not v.get('skipped'))
                    report.setdefault('skipped_captures', []).extend(
                        v for v in values if v.get('skipped')
                    )
                    save()
                    if errors:
                        raise errors[0]
                boundary['acquisition_budget'] = dict(
                    requested_ms=acquisition_budget_ms,
                    start_host_ns=budget_start_ns,
                    deadline_host_ns=acquisition_deadline_ns,
                    end_host_ns=time.monotonic_ns(),
                    rounds_started=rounds_started,
                    round_cap=captures,
                    round_cap_reached=rounds_started == captures,
                    per_receiver_captures=[
                        sum(
                            r['condition'] == condition and r['receiver'] == k
                            for r in report['captures']
                        )
                        for k in range(len(radios))
                    ],
                    note='Host call-start budget; in-flight UART transfer may finish after deadline. '
                    'Not synchronized RF coverage. A reached round cap may limit throughput.',
                )
                if condition == 'ON':
                    deadline = time.monotonic() + duration_ms / 1000 + 3
                    while True:
                        state = tx.status()
                        if not state['running']:
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError('Source failed to stop within finite duration')
                        time.sleep(0.05)
                    report['tx_final_run'] = state
                boundary['after'] = calibration(radios, condition + '-after')
                check_calibration(boundary['before'], boundary['after'])
        report['calibration_after'] = calibration(radios, 'campaign-after')
        check_calibration(report['calibration_before'], report['calibration_after'])
        # Decode after RF stops; CPU time must not consume the sampling interval.
        for row in report['captures']:
            row['decoder'] = decode(np.load(output / row['file']), 16000000, 2, 16)
            save()
        report['analysis'] = summarize(
            report['captures'],
            report['tx_start'],
            report['tx_final_run'],
            len(radios),
            expected_config,
            capture_bits,
        )
        report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error=repr(exc))
        raise
    finally:
        cleanup = []
        try:
            report['tx_stop'] = tx.stop()
            if report['tx_stop']['running']:
                raise RuntimeError('Transmitter STOP not confirmed')
            if old is not None:
                report['tx_restored'] = tx.configure(**old)
                if saved_config(report['tx_restored']) != old:
                    raise RuntimeError('Source configuration restoration mismatch')
        except Exception as exc:
            cleanup.append(repr(exc))
        for r in radios:
            try:
                r.close()
            except Exception as exc:
                cleanup.append(repr(exc))
        if cleanup:
            report.update(status='failed', cleanup_errors=cleanup)
        save()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', action='append', required=True)
    p.add_argument('--tx-serial', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--captures', type=int, default=8)
    p.add_argument('--duration-ms', type=int, default=8000)
    p.add_argument('--power-dbm', type=int, choices=POWERS_DBM, default=-20)
    p.add_argument('--stagger-ms', type=int, default=0)
    p.add_argument('--capture-bits', type=int, choices=(8, 10), default=10)
    p.add_argument(
        '--acquisition-budget-ms',
        type=int,
        help='Equal host call-start budget per ON/OFF condition; --captures is a round cap',
    )
    p.add_argument('--run', action='store_true')
    a = p.parse_args()
    if not 2 <= len(a.port) <= 4 or len({str(Path(v).resolve()) for v in a.port}) != len(a.port):
        p.error('Two to four distinct verified ports required')
    if not 1 <= a.captures <= 32 or not 1000 <= a.duration_ms <= 30000:
        p.error('Captures 1..32 and duration 1000..30000 ms required')
    try:
        plan = stagger_plan(
            len(a.port),
            a.captures,
            a.duration_ms,
            a.stagger_ms,
            a.capture_bits,
            a.acquisition_budget_ms,
        )
    except ValueError as exc:
        p.error(str(exc))
    if not a.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    receivers=len(a.port),
                    config=configuration(a.power_dbm),
                    captures=a.captures,
                    duration_ms=a.duration_ms,
                    note=NOTE,
                    capture_plan=plan,
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
            a.captures,
            a.duration_ms,
            power_dbm=a.power_dbm,
            stagger_ms=a.stagger_ms,
            capture_bits=a.capture_bits,
            acquisition_budget_ms=a.acquisition_budget_ms,
        )
    print(json.dumps(dict(status=report['status'], analysis=report.get('analysis'))))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
