#!/usr/bin/env python3
"""Bounded matched hardware-AGC/manual-gain source ON/OFF trials; never flashes.

Run as ``python -m nrf_campaigns.nrf_gain_compare`` after installing the project.
Raw data and device identifiers belong in a private output directory.
"""

import argparse
import hashlib
import json
import random
import time
from pathlib import Path
from statistics import mean

from sdr_research.pipeline import run_pipeline
from sdr_research.protocol import Radio
from sdr_research.recording import save_capture

CAUTIONS = [
    'Candidate windows are not packets and this is not a packet-recall estimate.',
    'Hardware AGC changes gain within runs: detector energies are not comparable across gain steps.',
    'The installed legacy background rule can latch on positives; this tests that firmware only.',
    'A small number of temporal blocks at one unmeasured bench placement does not establish calibrated sensitivity.',
    'TX counters bracket host commands, not exact receiver RF windows; retained CRC is transport CRC.',
]
TX_KEYS = (
    'frequency_mhz',
    'mode_mbps',
    'power_dbm',
    'payload_len',
    'interval_us',
    'jitter_us',
    'hop_list',
    'hop_every',
    'burst_count',
    'burst_gap_us',
    'payload_hex',
    'seed',
)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rx-port', required=True)
    p.add_argument('--tx-port', required=True)
    p.add_argument('--tx-serial', required=True)
    p.add_argument('--rx-artifact', type=Path, required=True)
    p.add_argument('--output-directory', type=Path, required=True)
    p.add_argument('--pairs', type=int, default=4)
    p.add_argument('--manual-gains', type=int, nargs='+', default=[40, 60])
    p.add_argument('--seed', type=int, default=52840)
    p.add_argument('--power-dbm', type=int, choices=(-40, -20, -16, -12, -8, -4, 0), default=-20)
    p.add_argument('--milliseconds', type=int, default=1000)
    p.add_argument(
        '--geometry', default='Existing bench placement; distance and orientation unmeasured'
    )
    return p


def plan(args):
    if not 2 <= args.pairs <= 16 or args.pairs % 2:
        raise ValueError('Choose an even number of paired blocks from 2 through 16')
    if not args.manual_gains or len(set(args.manual_gains)) != len(args.manual_gains):
        raise ValueError('Manual gain list must be nonempty and unique')
    if any(type(g) is not int or not 0 <= g <= 79 for g in args.manual_gains):
        raise ValueError('Invalid manual gain index')
    blocks = list(range(args.pairs))
    random.Random(args.seed).shuffle(blocks)
    modes = [('hardware-agc', None)] + [(f'manual-{g}', g) for g in args.manual_gains]
    result = []
    for pair in blocks:
        order = modes[pair % len(modes) :] + modes[: pair % len(modes)]
        if pair % 2:
            order = order[::-1]
        states = [False, True] if pair % 2 == 0 else [True, False]
        for on in states:
            result.extend(dict(pair=pair, mode=mode, gain=gain, tx_on=on) for mode, gain in order)
    return result


def checked_status(tx, running):
    status = tx.status()
    if type(status.get('running')) is not bool or status['running'] != running:
        raise RuntimeError('Transmitter running-state mismatch')
    if any(
        type(status.get(k)) is not int or status[k] < 0
        for k in ('scheduled', 'attempted', 'completed')
    ):
        raise RuntimeError('Invalid transmitter counters')
    return status


def check_gain(reply, gain):
    fields = reply.split()
    expected = ['GAIN', 'HARDWARE', '-1'] if gain is None else ['GAIN', 'MANUAL', str(gain)]
    if len(fields) != 6 or fields[:3] != expected:
        raise RuntimeError(f'Gain readback mismatch: {reply!r}')
    return reply


def summarize(rows):
    complete = [r for r in rows if r['status'] == 'passed']
    result = {}
    for mode in sorted({r['mode'] for r in complete}):
        group = [r for r in complete if r['mode'] == mode]
        states = {}
        for on in (False, True):
            rr = [r for r in group if r['tx_on'] is on]
            if rr:
                states['on' if on else 'off'] = {
                    'runs': len(rr),
                    'candidate_rate_per_local_second': mean(
                        r['candidate_rate_per_local_second'] for r in rr
                    ),
                    'candidate_fraction_postwarmup': mean(
                        r['candidate_fraction_postwarmup'] for r in rr
                    ),
                    'local_rf_duty_percent': mean(r['local_rf_duty_percent'] for r in rr),
                }
        by_pair = {(r['pair'], r['tx_on']): r for r in group}
        deltas = [
            by_pair[(p, True)]['candidate_rate_per_local_second']
            - by_pair[(p, False)]['candidate_rate_per_local_second']
            for p in sorted({r['pair'] for r in group})
            if (p, True) in by_pair and (p, False) in by_pair
        ]
        result[mode] = {
            'states': states,
            'paired_excess_per_second': deltas,
            'mean_paired_excess_per_second': mean(deltas) if deltas else None,
        }
    return result


def execute(args, radio, tx, *, pipeline=run_pipeline, saver=save_capture, sleep=time.sleep):
    conditions = plan(args)
    if not 100 <= args.milliseconds <= 2000:
        raise ValueError('Receiver duration must be 100..2000 ms')
    artifact_hash = hashlib.sha256(args.rx_artifact.read_bytes()).hexdigest()
    out = args.output_directory
    out.mkdir(parents=True, exist_ok=False)
    report = {
        'status': 'running',
        'cautions': CAUTIONS,
        'geometry': args.geometry,
        'geometry_measured': False,
        'local_receiver_artifact_sha256': artifact_hash,
        'artifact_note': 'Local reference artifact only; installed flash is not reread or modified.',
        'settings': {
            'frequency_mhz': 2440,
            'rate_hz': 16000000,
            'bandwidth_mhz': 12,
            'samples': 16380,
            'ratio_milli': 4000,
            'power_dbm': args.power_dbm,
            'milliseconds': args.milliseconds,
            'seed': args.seed,
        },
        'plan': conditions,
        'runs': [],
    }
    initial_gain = None

    def persist():
        tmp = out / 'results.json.tmp'
        tmp.write_text(json.dumps(report, indent=2))
        tmp.replace(out / 'results.json')

    try:
        report['tx_stop_initial'] = tx.stop()
        report['tx_initial'] = checked_status(tx, False)
        report['device'] = radio.connect()
        if 'esp32-pipeline-optimized-v2' not in report['device'].get('version', ''):
            raise RuntimeError(
                'Expected unchanged optimized-v2 receiver firmware; no flash attempted'
            )
        initial_gain = radio.command('GAIN?')
        report['gain_initial'] = initial_gain
        cfg = dict(
            frequency_mhz=2440,
            mode_mbps=2,
            power_dbm=args.power_dbm,
            payload_len=64,
            interval_us=2000,
            jitter_us=150,
            hop_list='off',
            hop_every=1,
            burst_count=0,
            burst_gap_us=0,
            payload_hex='off',
            seed=args.seed,
        )
        report['tx_configure'] = tx.configure(**cfg)
        configured = checked_status(tx, False)
        for key in (
            'frequency_mhz',
            'mode_mbps',
            'power_dbm',
            'payload_len',
            'interval_us',
            'jitter_us',
        ):
            if configured.get(key) != cfg[key]:
                raise RuntimeError(f'Transmitter configuration mismatch: {key}')
        persist()
        for index, condition in enumerate(conditions):
            row = dict(condition, index=index, status='running')
            report['runs'].append(row)
            tx.stop()
            checked_status(tx, False)
            radio.configure(2440, 16000000, 12, condition['gain'], 10)
            row['gain_before'] = check_gain(radio.command('GAIN?'), condition['gain'])
            radio.command('DETPIPECLEAR')
            if condition['tx_on']:
                # Independent finite duration and packet-count ceilings; no continuous mode.
                row['tx_start'] = tx.start(count=5000, duration_ms=6000)
            sleep(0.1)
            row['tx_before'] = checked_status(tx, condition['tx_on'])
            summary, capture = pipeline(
                radio,
                args.milliseconds,
                16380,
                16000000,
                4000,
                True,
                kernel=3,
                optimized=True,
                copy_option=1,
            )
            row['summary'] = summary
            row['gain_after'] = check_gain(radio.command('GAIN?'), condition['gain'])
            row['tx_after'] = checked_status(tx, condition['tx_on'])
            delta = row['tx_after']['completed'] - row['tx_before']['completed']
            row['tx_completed_delta'] = delta
            if (
                delta < 0
                or (condition['tx_on'] and delta == 0)
                or (not condition['tx_on'] and delta != 0)
            ):
                raise RuntimeError('Unexpected transmitter completed-counter delta')
            tx.stop()
            row['tx_stopped'] = checked_status(tx, False)
            if summary['status'] or summary.get('pack_failed', 0) or summary.get('errors', 0):
                raise RuntimeError('Receiver failed its bounded run')
            row['retained_transport_crc_valid'] = capture.crc_ok if capture is not None else None
            if capture is not None:
                if not capture.crc_ok:
                    raise RuntimeError('Retained transport CRC mismatch')
                capture.metadata['gain_comparison'] = {
                    **condition,
                    'gain_readback': row['gain_after'],
                    'geometry': args.geometry,
                    'cautions': CAUTIONS,
                }
                prefix = (
                    out / f'{index:04d}-{condition["mode"]}-{"on" if condition["tx_on"] else "off"}'
                )
                row['sigmf'] = str(saver(capture, prefix))
            row['candidate_rate_per_local_second'] = (
                summary['detections'] * 1e6 / summary['wall_elapsed_us']
            )
            decisions = summary['captures'] - summary['warmup_captures']
            row['candidate_fraction_postwarmup'] = (
                summary['detections'] / decisions if decisions else 0.0
            )
            row['local_rf_duty_percent'] = (
                100 * summary['total_samples'] / 16000000 * 1e6 / summary['wall_elapsed_us']
            )
            row['status'] = 'passed'
            report['comparison'] = summarize(report['runs'])
            persist()
        report['status'] = 'passed'
    except BaseException as exc:
        report['status'] = 'failed'
        report['error'] = repr(exc)
        raise
    finally:
        try:
            report['tx_stop_final'] = tx.stop()
            report['tx_final'] = checked_status(tx, False)
            original = report.get('tx_initial', {})
            restore = {k: original[k] for k in TX_KEYS if k in original}
            if restore:
                if isinstance(restore.get('hop_list'), list):
                    restore['hop_list'] = ','.join(map(str, restore['hop_list'])) or 'off'
                restore['payload_hex'] = restore.get('payload_hex') or 'off'
                report['tx_restore_configure'] = tx.configure(**restore)
                report['tx_restored'] = checked_status(tx, False)
                for key in (
                    'frequency_mhz',
                    'mode_mbps',
                    'power_dbm',
                    'payload_len',
                    'interval_us',
                    'jitter_us',
                ):
                    if key in original and report['tx_restored'].get(key) != original[key]:
                        raise RuntimeError(f'Transmitter restoration mismatch: {key}')
        except Exception as exc:
            report['tx_cleanup_error'] = repr(exc)
            report['status'] = 'failed'
        if initial_gain and not getattr(radio, 'failed', False):
            try:
                fields = initial_gain.split()
                command = (
                    'GAIN HARDWARE' if fields[1] == 'HARDWARE' else f'GAIN MANUAL {int(fields[2])}'
                )
                radio.command(command)
                report['gain_restored'] = radio.command('GAIN?')
                if report['gain_restored'] != initial_gain:
                    raise RuntimeError('Initial gain readback was not restored')
                report['receiver_final_version'] = radio.command('VERSION?')
            except Exception as exc:
                report['receiver_cleanup_error'] = repr(exc)
                report['status'] = 'failed'
        report['comparison'] = summarize(report['runs'])
        persist()
    return report


def main():
    from nrf_tx.rf_tx import Transmitter

    args = parser().parse_args()
    radio = Radio(args.rx_port)
    try:
        with Transmitter(args.tx_port, serial_number=args.tx_serial) as tx:
            report = execute(args, radio, tx)
        print(
            json.dumps({'status': report['status'], 'comparison': report['comparison']}, indent=2)
        )
        return 0 if report['status'] == 'passed' else 1
    finally:
        radio.close()


if __name__ == '__main__':
    raise SystemExit(main())
