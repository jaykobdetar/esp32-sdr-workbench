#!/usr/bin/env python3
"""Finite controlled-source experiments. Candidate windows and IQ CRC are NOT packet recall."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import time

ROOT = Path(__file__).resolve().parents[1]
from sdr_research.protocol import Radio
from sdr_research.pipeline import run_pipeline, select_acquisition_policy
from sdr_research.detector import run_detection
from sdr_research.recording import save_capture

LIMITS = ('Candidate detections are windows, not packets. Retained CRC is UART IQ CRC32, '
          'not Nordic packet CRC. TX completed counters are local radio-END events, not '
          'proof of received packets. Counts bracket host commands, not exact RF windows. '
          'No packet recall, RF synchronization, or transmitter attribution is established.')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rx-port', required=True)
    p.add_argument('--tx-port', required=True)
    p.add_argument('--rx-artifact', required=True, help='Path to your independently verified installed receiver application binary; hashed for provenance, not flashed')
    p.add_argument('--output-directory', type=Path, required=True)
    p.add_argument('--pairs', type=int, default=8, help='ON/OFF pairs per receiver frequency and mode')
    p.add_argument('--seed', type=int, default=52840)
    p.add_argument('--frequency-mhz', type=int, default=2440, help='TX center')
    p.add_argument('--rx-frequencies', type=int, nargs='+', default=[2440], help='Include an offset control explicitly')
    p.add_argument('--mode-mbps', type=int, choices=(1, 2), default=2)
    p.add_argument('--power-dbm', type=int, default=-20)
    p.add_argument('--length', type=int, default=64)
    p.add_argument('--interval-us', type=int, default=2000)
    p.add_argument('--jitter-us', type=int, default=0)
    p.add_argument('--hop-list', default='off', help='Comma-separated MHz sequence, or off')
    p.add_argument('--hop-every', type=int, default=1)
    p.add_argument('--burst-count', type=int, default=0)
    p.add_argument('--burst-gap-us', type=int, default=0)
    p.add_argument('--payload-hex', default='off')
    p.add_argument('--tx-count', type=int, default=20000, help='Finite source packet ceiling')
    p.add_argument('--gain', type=int, default=40)
    p.add_argument('--ratio-milli', type=int, default=4000)
    p.add_argument('--bandwidth-mhz', type=int, default=12)
    p.add_argument('--samples', type=int, default=16380)
    p.add_argument('--rate-hz', type=int, choices=(16000000,40000000,80000000), default=16000000)
    p.add_argument('--milliseconds', type=int, default=2000)
    p.add_argument('--settle-seconds', type=float, default=.1)
    p.add_argument('--tx-duration-ms', type=int, default=10000, help='Finite safety bound for each observation')
    p.add_argument('--raw-pairs', type=int, default=2, help='Direct raw ON/OFF pairs per frequency')
    p.add_argument('--geometry', default='unspecified', help='Document separation, orientation and environment')
    return p


def plan(args):
    rng = random.Random(args.seed)
    result = []
    for frequency in args.rx_frequencies:
        for pair in range(args.raw_pairs):
            states = [False, True]
            rng.shuffle(states)
            result.extend(dict(frequency_mhz=frequency, pair=pair, mode='raw', tx_on=s) for s in states)
        # Balance initial ON/OFF order and receiver-mode order, then randomize blocks.
        blocks = list(range(args.pairs))
        rng.shuffle(blocks)
        for pair in blocks:
            states = [False, True] if pair % 2 == 0 else [True, False]
            modes = list(getattr(args, 'receiver_modes', ['baseline', 'optimized']))
            if (pair // 2) % 2: modes.reverse()
            for state in states:
                result.extend(dict(frequency_mhz=frequency, pair=pair, mode=m, tx_on=state) for m in modes)
    return result


def checked_status(tx, expected):
    s = tx.status()
    if type(s.get('running')) is not bool or s['running'] != expected:
        raise RuntimeError(f'TX running mismatch: expected {expected}, received {s!r}')
    for key in ('scheduled', 'attempted', 'completed'):
        if type(s.get(key)) is not int or s[key] < 0:
            raise RuntimeError(f'Invalid TX counter {key}: {s!r}')
    return s


def execute(args, radio, tx, *, sleep=time.sleep, clock=time.monotonic_ns,
            pipeline=run_pipeline, detector=run_detection, saver=save_capture):
    """Caller owns connections. Always requests STOP, including failed preflight."""
    out = args.output_directory
    report = {'status':'running', 'limits':LIMITS, 'settings':vars(args).copy(), 'runs':[]}
    report['settings']['output_directory'] = str(out)
    start = clock()
    created = False
    def save():
        if created:
            tmp = out / 'results.json.tmp'
            tmp.write_text(json.dumps(report, indent=2))
            tmp.replace(out / 'results.json')
    try:
        if not 1 <= args.milliseconds <= 5000 or not 256 <= args.samples <= 16380:
            raise ValueError('Receiver duration/samples outside finite limits')
        if not 1 <= args.tx_count <= 20000 or not 1 <= args.tx_duration_ms <= 60000:
            raise ValueError('TX count/duration outside finite firmware limits')
        if args.pairs < 1 or args.raw_pairs < 0 or args.settle_seconds < 0:
            raise ValueError('Invalid pairs or settle interval')
        if args.tx_duration_ms < args.milliseconds + args.settle_seconds*1000 + 3000:
            raise ValueError('TX timeout must cover settling, receiver run and transfer margin')
        out.mkdir(parents=True, exist_ok=False)
        created = True
        save()
        report['stop_initial'] = tx.stop()
        report['tx_initial'] = checked_status(tx, False)
        report['tx_configure'] = tx.configure(frequency_mhz=args.frequency_mhz,
            mode_mbps=args.mode_mbps, power_dbm=args.power_dbm, payload_len=args.length,
            interval_us=args.interval_us, jitter_us=args.jitter_us,
            hop_list=args.hop_list, hop_every=args.hop_every,
            burst_count=args.burst_count, burst_gap_us=args.burst_gap_us,
            payload_hex=args.payload_hex, seed=args.seed)
        report['tx_configured_status'] = checked_status(tx, False)
        expected = dict(frequency_mhz=args.frequency_mhz, mode_mbps=args.mode_mbps,
                        power_dbm=args.power_dbm, payload_len=args.length, interval_us=args.interval_us, jitter_us=args.jitter_us)
        for key, value in expected.items():
            if report['tx_configured_status'].get(key) != value:
                raise RuntimeError(f'TX configuration mismatch for {key}')
        report['device'] = radio.connect()
        expected_variant = getattr(args, 'expected_variant', 'esp32-pipeline-optimized-v2')
        if expected_variant and expected_variant not in report['device'].get('version',''):
            raise RuntimeError(f'Expected receiver variant {expected_variant}')
        artifact = Path(args.rx_artifact)
        report['local_rx_artifact_sha256'] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        report['plan'] = plan(args)
        save()
        for index, condition in enumerate(report['plan']):
            row = dict(condition, index=index, status='running')
            report['runs'].append(row)
            tx.stop()
            row['tx_stopped'] = checked_status(tx, False)
            radio.configure(condition['frequency_mhz'], args.rate_hz, args.bandwidth_mhz, args.gain, 10)
            if condition['tx_on']:
                row['tx_start'] = tx.start(count=args.tx_count, duration_ms=args.tx_duration_ms)
            sleep(args.settle_seconds)
            row['tx_before'] = checked_status(tx, condition['tx_on'])
            begin = clock()
            if condition['mode'] == 'raw':
                summary, capture = {}, radio.capture(args.samples)
            else:
                if condition['mode'] != 'historical':
                    radio.command('DETPIPECLEAR')
                if condition['mode'] in ('baseline', 'historical'):
                    if condition['mode'] == 'baseline':
                        select_acquisition_policy(radio, False)
                    summary, capture = detector(radio, args.milliseconds, args.samples, args.rate_hz, args.ratio_milli, True)
                else:
                    retention_policy = None
                    if condition['mode'] in ('strongest', 'reservoir'):
                        retention_policy = int(condition['mode'] == 'reservoir')
                        retention_seed = (args.seed + condition['pair'] * 104729) & 0xffffffff
                        if radio.command(f'PIPESEED {retention_seed}') != f'PIPESEED {retention_seed}':
                            raise RuntimeError('Retention seed acknowledgement mismatch')
                        expected_keep = f'PIPEKEEP {retention_policy} {retention_seed}'
                        if radio.command(f'PIPEKEEP {retention_policy}') != expected_keep or radio.command('PIPEKEEP?') != expected_keep:
                            raise RuntimeError('Retention policy readback mismatch')
                    summary, capture = pipeline(radio, args.milliseconds, args.samples, args.rate_hz,
                        args.ratio_milli, True, kernel=3, optimized=True, copy_option=1)
                    if retention_policy is not None and (summary.get('retention_policy') != retention_policy or summary.get('retention_seed') != retention_seed):
                        raise RuntimeError('Retention summary policy mismatch')
                if summary['status'] != 0 or summary.get('pack_failed',0):
                    raise RuntimeError(f'Receiver failed: {summary!r}')
            row['receiver_elapsed_ns'] = clock() - begin
            row['summary'] = summary
            row['tx_after'] = checked_status(tx, condition['tx_on'])
            row['tx_completed_delta'] = row['tx_after']['completed'] - row['tx_before']['completed']
            if row['tx_completed_delta'] < 0 or (condition['tx_on'] and row['tx_completed_delta'] == 0) or (not condition['tx_on'] and row['tx_completed_delta'] != 0):
                raise RuntimeError('Unexpected TX completed counter delta')
            row['tx_stop'] = tx.stop()
            row['tx_final'] = checked_status(tx, False)
            row['retained_crc_valid'] = bool(capture is not None and capture.crc_ok)
            if capture is not None:
                if not capture.crc_ok:
                    raise RuntimeError('Capture CRC invalid')
                capture.metadata['controlled_source'] = {**condition, 'tx_before':row['tx_before'],
                    'tx_after':row['tx_after'], 'limits':LIMITS, 'settings':report['settings']}
                import numpy as np
                row['iq_rms'] = float(np.sqrt(np.mean(abs(capture.iq)**2)))
                row['clipped_fraction'] = float(np.mean((abs(capture.iq.real)>=511/512)|(abs(capture.iq.imag)>=511/512)))
                row['sigmf'] = str(saver(capture, out / f'{index:04d}-{condition["mode"]}-{"on" if condition["tx_on"] else "off"}'))
            if summary:
                rf_seconds = summary['total_samples'] / args.rate_hz
                decision_seconds = max(0, summary['captures']-summary['warmup_captures'])*(args.samples//64)*64/args.rate_hz
                row['nominal_rf_seconds'] = rf_seconds
                row['nominal_decision_seconds'] = decision_seconds
                row['nominal_local_rf_duty_percent'] = 100*rf_seconds/(summary['wall_elapsed_us']/1e6)
                row['nominal_receiver_host_rf_duty_percent'] = 100*rf_seconds/(row['receiver_elapsed_ns']/1e9)
                row['nominal_receiver_host_decision_duty_percent'] = 100*decision_seconds/(row['receiver_elapsed_ns']/1e9)
                row['candidate_fraction_postwarmup'] = summary['detections']/max(1,summary['captures']-summary['warmup_captures'])
                row['candidate_windows_per_host_second'] = summary['detections']/(row['receiver_elapsed_ns']/1e9)
            row['status'] = 'passed'
            (out/f'{index:04d}-run.json').write_text(json.dumps(row, indent=2))
            save()
        report['status'] = 'passed'
    except BaseException as exc:
        report['status'] = 'failed'
        report['error'] = repr(exc)
        if report['runs'] and report['runs'][-1]['status'] == 'running':
            report['runs'][-1]['status'] = 'failed'
        raise
    finally:
        try:
            report['cleanup_stop'] = tx.stop()
            report['cleanup_status'] = checked_status(tx, False)
        except Exception as exc:
            report['cleanup_error'] = repr(exc)
            report['status'] = 'failed'
        report['session_elapsed_ns'] = clock() - start
        total_samples = sum(r.get('summary',{}).get('total_samples',0) for r in report['runs'] if r['status']=='passed')
        report['detector_nominal_rf_seconds'] = total_samples / args.rate_hz
        report['detector_rf_percent_of_complete_campaign'] = 100*report['detector_nominal_rf_seconds']/(report['session_elapsed_ns']/1e9)
        report['session_timing_note'] = 'Includes raw controls, settling, TX control, retrieval and saving; not comparable to local detector duty.'
        save()
        if created:
            fields=['index','frequency_mhz','pair','mode','tx_on','status','tx_completed_delta','retained_crc_valid','candidate_fraction_postwarmup','candidate_windows_per_host_second','receiver_elapsed_ns','nominal_rf_seconds','nominal_decision_seconds','nominal_local_rf_duty_percent','nominal_receiver_host_rf_duty_percent','nominal_receiver_host_decision_duty_percent','iq_rms','clipped_fraction','sigmf']
            with (out/'runs.csv').open('w', newline='') as f:
                w=csv.DictWriter(f, fieldnames=fields, extrasaction='ignore');w.writeheader();w.writerows(report['runs'])
    return report


def main():
    args = parser().parse_args()
    from nrf_tx.rf_tx import Transmitter
    radio = Radio(args.rx_port)
    try:
        with Transmitter(args.tx_port) as tx:
            report = execute(args, radio, tx)
        return 0 if report['status']=='passed' else 1
    finally:
        radio.close()

if __name__ == '__main__':
    raise SystemExit(main())
