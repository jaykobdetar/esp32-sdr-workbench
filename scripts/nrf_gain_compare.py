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

from sdr_research.calibration import ADAPTIVE_VARIANTS, CALIBRATION_VARIANTS, record_calibration
from sdr_research.pipeline import run_pipeline, run_pipeline_candidates
from sdr_research.protocol import Radio
from sdr_research.recording import save_capture

CAUTIONS = [
    'Candidate windows are not packets and this is not a packet-recall estimate.',
    'Hardware AGC changes gain within runs: detector energies are not comparable across gain steps.',
    'Legacy v2 can latch on positives; v3 uses adaptive background. Compare only explicitly identified images.',
    'Selectors/gain are restored; frequency/rate/bandwidth remain at the trial configuration.',
    'A small number of temporal blocks at one unmeasured bench placement does not establish calibrated sensitivity.',
    'TX counters bracket host commands, not exact receiver RF windows; retained CRC is transport CRC.',
]
VARIANTS = ('esp32-pipeline-optimized-v2', *ADAPTIVE_VARIANTS)
SELECTORS = ('PIPEKERNEL', 'ACQOPT', 'CLEAROPT', 'PIPECOPY')

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
    p.add_argument('--rx-serial', help='Required by hardware entry point; exact USB serial')
    p.add_argument('--expected-variant', choices=VARIANTS, default=VARIANTS[0])
    p.add_argument('--expected-revision')
    p.add_argument('--candidate-count', type=int, choices=(1, 3), default=1)
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


def heap(radio):
    fields = radio.command('DETPIPEMEM?').split()
    if len(fields) != 3 or fields[0] != 'DETPIPEMEM':
        raise RuntimeError('Invalid heap reply')
    free, largest = map(int, fields[1:])
    if not 0 <= largest <= free:
        raise RuntimeError('Invalid heap values')
    return dict(free_bytes=free, largest_bytes=largest)


def selectors(radio, names):
    result = {}
    for name in names:
        reply = radio.command(name + '?')
        fields = reply.split()
        if len(fields) != 2 or fields[0] != name or not fields[1].isdigit():
            raise RuntimeError(f'Invalid selector readback: {name}')
        result[name] = reply
    return result


def usb_identity(port, serial, ports):
    resolved_port = Path(port).resolve()
    matches = [
        p for p in ports if Path(p.device).resolve() == resolved_port and p.serial_number == serial
    ]
    if not serial or len(matches) != 1 or matches[0].vid is None or matches[0].pid is None:
        raise RuntimeError(f'Exact USB identity not found for {port}')
    p = matches[0]
    return dict(
        device=p.device,
        serial_number=p.serial_number,
        vid=p.vid,
        pid=p.pid,
        location=p.location,
        manufacturer=p.manufacturer,
        product=p.product,
    )


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


def execute(
    args,
    radio,
    tx,
    *,
    pipeline=run_pipeline,
    multiple=run_pipeline_candidates,
    saver=save_capture,
    sleep=time.sleep,
):
    conditions = plan(args)
    if args.candidate_count == 3 and args.expected_variant not in ADAPTIVE_VARIANTS:
        raise ValueError('Three-crop trials require explicit adaptive variant')
    if not 100 <= args.milliseconds <= 2000:
        raise ValueError('Receiver duration must be 100..2000 ms')
    artifact_hash = hashlib.sha256(args.rx_artifact.read_bytes()).hexdigest()
    out = args.output_directory
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = {
        'status': 'running',
        'expected_variant': args.expected_variant,
        'expected_revision': args.expected_revision,
        'candidate_count': args.candidate_count,
        'usb_identity': getattr(args, 'usb_identity', None),
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
    initial_selectors = {}
    baseline = None

    def persist():
        tmp = out / 'results.json.tmp'
        tmp.write_text(json.dumps(report, indent=2))
        tmp.replace(out / 'results.json')

    def fingerprint(boundary):
        record_calibration(
            report,
            radio,
            report['device'],
            boundary,
            required=args.expected_variant in CALIBRATION_VARIANTS,
        )
        persist()

    try:
        report['tx_stop_initial'] = tx.stop()
        report['tx_initial'] = checked_status(tx, False)
        report['device'] = radio.connect()
        version_text = report['device'].get('version', '').removeprefix('VERSION ')
        try:
            version = json.loads(version_text)
        except json.JSONDecodeError:
            version = {'firmware_variant': version_text}
        if (
            not isinstance(version, dict)
            or version.get('firmware_variant') != args.expected_variant
        ):
            raise RuntimeError(
                'Expected unchanged explicitly selected receiver firmware; no flash attempted'
            )
        if args.expected_revision and version.get('revision') != args.expected_revision:
            raise RuntimeError('Receiver revision mismatch; no flash attempted')
        fingerprint('stage_start')
        names = SELECTORS + (('PIPEKEEP',) if args.expected_variant in ADAPTIVE_VARIANTS else ())
        observed_selectors = selectors(radio, names)
        report['selectors_initial'] = observed_selectors.copy()
        if observed_selectors.get('PIPEKEEP', 'PIPEKEEP 1') != 'PIPEKEEP 1':
            raise RuntimeError('Pending external crop selection')
        initial_selectors = observed_selectors
        radio.command('DETPIPECLEAR')
        baseline = report['heap_baseline'] = heap(radio)
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
            for setting in ('PIPEKERNEL 3', 'ACQOPT 3', 'CLEAROPT 1', 'PIPECOPY 1'):
                radio.command(setting)
            row['selectors_before'] = selectors(radio, names)
            expected_selectors = dict(
                PIPEKERNEL='PIPEKERNEL 3',
                ACQOPT='ACQOPT 3',
                CLEAROPT='CLEAROPT 1',
                PIPECOPY='PIPECOPY 1',
            )
            if any(row['selectors_before'][k] != v for k, v in expected_selectors.items()):
                raise RuntimeError('Trial selector mismatch')
            if row['selectors_before'].get('PIPEKEEP', 'PIPEKEEP 1') != 'PIPEKEEP 1':
                raise RuntimeError('One-shot retention selection did not reset')
            radio.command('DETPIPECLEAR')
            row['heap_before'] = heap(radio)
            if row['heap_before'] != baseline:
                raise RuntimeError('Cleared heap drift before run')
            fingerprint(f'run_{index}_before')
            if condition['tx_on']:
                # Independent finite duration and packet-count ceilings; no continuous mode.
                row['tx_start'] = tx.start(count=5000, duration_ms=6000)
            sleep(0.1)
            row['tx_before'] = checked_status(tx, condition['tx_on'])
            summary, retained = (multiple if args.candidate_count == 3 else pipeline)(
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
            captures = (
                retained if args.candidate_count == 3 else ([] if retained is None else [retained])
            )
            row['summary'] = summary
            row['heap_retained'] = heap(radio)
            row['selectors_after'] = selectors(radio, names)
            if row['selectors_after'] != row['selectors_before']:
                raise RuntimeError('Pipeline selectors were not restored')
            if args.expected_variant in ADAPTIVE_VARIANTS and summary.get('background_policy') != 2:
                raise RuntimeError('Adaptive background policy mismatch')
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
            fingerprint(f'run_{index}_after')
            if summary['status'] or summary.get('pack_failed', 0) or summary.get('errors', 0):
                raise RuntimeError('Receiver failed its bounded run')
            row['retained_count'] = len(captures)
            row['retained_transport_crc_valid'] = (
                all(c.crc_ok for c in captures) if captures else None
            )
            row['crops'] = []
            if len(captures) > args.candidate_count:
                raise RuntimeError('Too many retained crops')
            if summary.get('retained_event_count', len(captures)) != len(captures):
                raise RuntimeError('Retained crop count mismatch')
            if bool(summary.get('retained_samples', bool(captures))) != bool(captures):
                raise RuntimeError('Retained crop presence mismatch')
            for candidate, capture in enumerate(captures):
                if not capture.crc_ok:
                    raise RuntimeError('Retained transport CRC mismatch')
                capture.metadata['gain_comparison'] = {
                    **condition,
                    'gain_readback': row['gain_after'],
                    'geometry': args.geometry,
                    'cautions': CAUTIONS,
                }
                prefix = (
                    out
                    / f'{index:04d}-{condition["mode"]}-{"on" if condition["tx_on"] else "off"}-crop-{candidate}'
                )
                crop = dict(
                    index=candidate,
                    crc_ok=capture.crc_ok,
                    metadata=capture.metadata.copy(),
                    sigmf=str(saver(capture, prefix)),
                )
                row['crops'].append(crop)
                if candidate == 0:
                    row['sigmf'] = crop['sigmf']
                persist()
            radio.command('DETPIPECLEAR')
            row['heap_cleared'] = heap(radio)
            if row['heap_cleared'] != baseline:
                raise RuntimeError('Cleared heap drift after run')
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
        if report['runs'] and report['runs'][-1]['status'] == 'running':
            report['runs'][-1].update(status='failed', error=repr(exc))
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
        if getattr(radio, 'failed', False):
            report['receiver_cleanup_error'] = (
                'Transport failed; receiver clear/restoration unverified'
            )
            report['status'] = 'failed'
        if initial_selectors and not getattr(radio, 'failed', False):
            try:
                radio.command('DETPIPECLEAR')
                report['heap_final'] = heap(radio)
                if baseline is not None and report['heap_final'] != baseline:
                    raise RuntimeError('Final cleared heap drift')
                for reply in initial_selectors.values():
                    radio.command(reply)
                report['selectors_restored'] = selectors(radio, initial_selectors)
                if report['selectors_restored'] != initial_selectors:
                    raise RuntimeError('Selector restoration mismatch')
            except Exception as exc:
                report['receiver_cleanup_error'] = repr(exc)
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
        if 'device' in report:
            try:
                fingerprint('stage_end')
            except Exception as exc:
                report['calibration_cleanup_error'] = type(exc).__name__
                report['status'] = 'failed'
        report['comparison'] = summarize(report['runs'])
        persist()
    return report


def main():
    from nrf_tx.rf_tx import Transmitter

    args = parser().parse_args()
    from serial.tools import list_ports

    if not args.rx_serial:
        raise ValueError('--rx-serial is required for hardware execution')
    if Path(args.rx_port).resolve() == Path(args.tx_port).resolve():
        raise ValueError('Receiver and source must be distinct USB devices')
    ports = list(list_ports.comports())
    args.usb_identity = {
        'rx': usb_identity(args.rx_port, args.rx_serial, ports),
        'tx': usb_identity(args.tx_port, args.tx_serial, ports),
    }
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
