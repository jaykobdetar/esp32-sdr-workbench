"""Bounded raw-snapshot recovery control; NOT continuous reception or timing coverage.

Run with python -m nrf_campaigns.four_receiver_packets. Output is private.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from nrf_tx.rf_tx import Transmitter

from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json

from .analyze_nrf_iq import decode

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
            if hit.get('observed_payload_hex') != hit.get('expected_payload_hex'):
                raise ValueError('Inconsistent known-payload evidence')
            seq = hit['sequence']
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
                raise ValueError('Invalid packet sequence')
            values.append(seq)
    return values


def summarize(rows, start, final, receiver_count):
    """Conservative denominator: v0.2.2 sequences count attempted TX from zero."""
    for state in (start, final):
        if (
            state.get('version') != '0.2.2'
            or state.get('healthy') is not True
            or state.get('errors') != 0
            or state.get('timing_saturated') is not False
        ):
            raise ValueError('Unsupported or unhealthy transmitter accounting')
        if saved_config(state) != CONFIG:
            raise ValueError('Source configuration changed')
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
    for row in rows:
        if row['transport_crc_valid'] is not True:
            raise ValueError('Invalid raw transport')
        seqs = accepted(row['decoder'])
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


def capture(radio, receiver, index, condition, output):
    c = radio.capture(16380)
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
    )


def run(radios, tx, output, captures=8, duration_ms=8000):
    report = dict(status='running', captures=[], note=NOTE)
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
        report['calibration_before'] = [r.command('CALHASH?') for r in radios]
        for r in radios:
            r.configure(2440, 16000000, 12, 60, 10)
        tx.configure(**CONFIG)
        with ThreadPoolExecutor(len(radios)) as pool:
            for condition in ('OFF', 'ON'):
                if condition == 'ON':
                    report['tx_start'] = tx.start(count=20000, duration_ms=duration_ms)
                for index in range(captures):
                    futures = [
                        pool.submit(capture, r, k, index, condition, output)
                        for k, r in enumerate(radios)
                    ]
                    # Collect every worker before propagating an exception.
                    values, errors = [], []
                    for future in futures:
                        try:
                            values.append(future.result())
                        except Exception as exc:
                            errors.append(exc)
                    report['captures'].extend(values)
                    save()
                    if errors:
                        raise errors[0]
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
        report['calibration_after'] = [r.command('CALHASH?') for r in radios]
        if report['calibration_before'] != report['calibration_after']:
            raise ValueError('Calibration fingerprint changed')
        # Decode after RF stops; CPU time must not consume the sampling interval.
        for row in report['captures']:
            row['decoder'] = decode(np.load(output / row['file']), 16000000, 2, 16)
            save()
        report['analysis'] = summarize(
            report['captures'], report['tx_start'], report['tx_final_run'], len(radios)
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
    p.add_argument('--run', action='store_true')
    a = p.parse_args()
    if not 2 <= len(a.port) <= 4 or len({str(Path(v).resolve()) for v in a.port}) != len(a.port):
        p.error('Two to four distinct verified ports required')
    if not 1 <= a.captures <= 32 or not 1000 <= a.duration_ms <= 30000:
        p.error('Captures 1..32 and duration 1000..30000 ms required')
    if not a.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    receivers=len(a.port),
                    config=CONFIG,
                    captures=a.captures,
                    duration_ms=a.duration_ms,
                    note=NOTE,
                )
            )
        )
        return 0
    os.umask(0o077)
    a.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    with Transmitter(serial_number=a.tx_serial) as tx:
        report = run([Radio(port) for port in a.port], tx, a.output, a.captures, a.duration_ms)
    print(json.dumps(dict(status=report['status'], analysis=report.get('analysis'))))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
