"""Private passive board acceptance/soak runner. Never flashes or starts RF.

Use only after the device identity, recovery, layout and installation gates pass.
The exact local artifact hash is not proof of installed-flash identity. Hardware
requires the validation-only DETPIPE_HEALTH build. No interactive desktop needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.nrf_gain_compare import check_gain, checked_status
from sdr_research.calibration import CURRENT_VARIANT, record_calibration
from sdr_research.pipeline import run_pipeline, run_pipeline_candidates
from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json, save_capture

VARIANT = CURRENT_VARIANT
SELECTORS = ('PIPEKEEP', 'PIPEKERNEL', 'ACQOPT', 'CLEAROPT', 'PIPECOPY')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rx-port', required=True)
    p.add_argument('--tx-port', required=True)
    p.add_argument('--tx-serial', required=True)
    p.add_argument('--rx-artifact', type=Path, required=True)
    p.add_argument('--expected-revision', required=True)
    p.add_argument('--output-directory', type=Path, required=True)
    p.add_argument('--stage', choices=('short', 'boundary', 'medium', 'soak'), required=True)
    p.add_argument('--min-stack-bytes', type=int, default=2048)
    p.add_argument('--min-heap-bytes', type=int, default=8192)
    p.add_argument('--plan-only', action='store_true')
    return p


def plan(stage):
    def row(n=16380, keep=1, ms=1000, rate=16000000, kernel=3, copy=1):
        return dict(
            samples=n,
            candidate_count=keep,
            milliseconds=ms,
            rate_hz=rate,
            kernel=kernel,
            optimized=kernel == 3,
            copy_option=copy,
        )

    if stage == 'short':
        return [row(keep=k) for _ in range(5) for k in (1, 3)]
    if stage == 'boundary':
        return [
            row(n, k, 1000, rate, kernel, copy)
            for n in (256, 257, 2048, 5119, 5120, 5121, 8192, 16379, 16380)
            for rate in (16000000, 40000000, 80000000)
            for kernel in (0, 3)
            for copy in (0, 1)
            for k in (1, 3)
        ]
    if stage in ('medium', 'soak'):
        count = 40 if stage == 'medium' else 360
        return [row(keep=1 if i % 2 == 0 else 3, ms=5000) for i in range(count)]
    raise ValueError('Unknown stage')


def heap(radio):
    text = radio.command('DETPIPEMEM?').split()
    if len(text) != 3 or text[0] != 'DETPIPEMEM':
        raise RuntimeError('Invalid heap reply')
    values = [int(v) for v in text[1:]]
    if not 0 <= values[1] <= values[0]:
        raise RuntimeError('Invalid heap values')
    return dict(free_bytes=values[0], largest_bytes=values[1])


def health(radio):
    line = radio.command('DETPIPEHEALTH?')
    if not line.startswith('DETPIPEHEALTH '):
        raise RuntimeError('Missing validation telemetry')
    value = json.loads(line[len('DETPIPEHEALTH ') :])
    if not isinstance(value, dict) or value.get('version') != 1 or value.get('enabled') is not True:
        raise RuntimeError('Validation telemetry is not enabled')
    return value


def check_health(value, args, previous_run):
    if value.get('run_valid') is not True:
        raise RuntimeError('Incomplete run telemetry')
    for field in (
        'run_id',
        'monitor_start_error',
        'monitor_stop_error',
        'run_min_bytes',
        'stack_after_bytes',
    ):
        if type(value.get(field)) is not int or value[field] < 0:
            raise RuntimeError(f'Invalid health field: {field}')
    if value['run_id'] != previous_run + 1:
        raise RuntimeError('Stale/nonconsecutive run telemetry')
    if value['monitor_start_error'] or value['monitor_stop_error']:
        raise RuntimeError('Heap minimum monitor failed')
    if value['run_min_bytes'] < args.min_heap_bytes:
        raise RuntimeError('Conservative heap minimum below declared margin')
    if value['stack_after_bytes'] < args.min_stack_bytes:
        raise RuntimeError('Task stack lifetime margin below declared margin')


def execute(
    args, radio, tx, *, single=run_pipeline, multiple=run_pipeline_candidates, saver=save_capture
):
    conditions = plan(args.stage)
    if args.min_stack_bytes < 2048 or args.min_heap_bytes < 8192:
        raise ValueError('Do not reduce the declared conservative evaluation margins')
    artifact_hash = hashlib.sha256(args.rx_artifact.read_bytes()).hexdigest()
    out = args.output_directory
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = dict(
        status='running',
        stage=args.stage,
        plan=conditions,
        runs=[],
        raw_captures=[],
        local_artifact_sha256=artifact_hash,
        expected_revision=args.expected_revision,
        thresholds=dict(stack_bytes=args.min_stack_bytes, heap_bytes=args.min_heap_bytes),
        limitations=[
            'Passive test only; no controlled source ON or packet-recall claim.',
            'Local artifact hash and VERSION are not installed-flash readback proof.',
            'Heap local minimum is conservative sum of per-region lows, not necessarily simultaneous.',
            'Stack high-water is command-task lifetime minimum free bytes, not per-run delta.',
            'Receiver gain/selectors restored; frequency/bandwidth left at 2440 MHz/12 MHz.',
            'No fresh boot is performed; repeat the stages after a verified operator reboot.',
        ],
    )
    initial_gain = None
    selectors = {}
    error = None

    def persist():
        atomic_write_json(out / 'results.json', report)

    def fingerprint(boundary):
        record_calibration(report, radio, report['device'], boundary, required=True)
        persist()

    def stopped():
        tx.stop()
        return checked_status(tx, False)

    try:
        report['tx_initial'] = stopped()
        info = report['device'] = radio.connect()
        version = json.loads(info['version'].removeprefix('VERSION '))
        if (
            version.get('firmware_variant') != VARIANT
            or version.get('revision') != args.expected_revision
        ):
            raise RuntimeError('Unexpected receiver image variant/revision')
        if 'PIPEKEEP' not in info.get('caps', []) or '1000000' not in info.get('transport', ''):
            raise RuntimeError('Required pipeline or UART transport missing')
        fingerprint('stage_start')
        initial_gain = radio.command('GAIN?')
        report['gain_initial'] = initial_gain
        for name in SELECTORS:
            reply = radio.command(name + '?')
            if reply.split()[:1] != [name] or len(reply.split()) != 2:
                raise RuntimeError(f'Invalid selector readback: {name}')
            selectors[name] = reply
        report['selectors_initial'] = selectors.copy()
        if selectors['PIPEKEEP'] != 'PIPEKEEP 1':
            raise RuntimeError('Pending external crop selection; refusing to consume it')
        radio.command('DETPIPECLEAR')
        previous_run = health(radio)['run_id']
        radio.configure(2440, 16000000, 12, 40, 10)
        check_gain(radio.command('GAIN?'), 40)
        if args.stage == 'short':
            for i in range(5):
                capture = radio.capture(16380)
                if not capture.crc_ok or len(capture.iq) != 16380:
                    raise RuntimeError('Raw capture CRC/length mismatch')
                report['raw_captures'].append(str(saver(capture, out / f'raw-{i:03}')))
                persist()
        radio.command('DETPIPECLEAR')
        baseline = report['heap_baseline'] = heap(radio)
        for index, condition in enumerate(conditions):
            row = dict(index=index, status='running', condition=condition)
            report['runs'].append(row)
            row['tx_before'] = checked_status(tx, False)
            radio.configure(2440, condition['rate_hz'], 12, 40, 10)
            row['gain_before'] = check_gain(radio.command('GAIN?'), 40)
            if radio.command('PIPEKEEP?') != 'PIPEKEEP 1':
                raise RuntimeError('One-shot retention selection did not reset')
            radio.command('DETPIPECLEAR')
            row['heap_before'] = heap(radio)
            if row['heap_before'] != baseline:
                raise RuntimeError('Post-clear heap drift or fragmentation')
            fingerprint(f'run_{index}_before')
            kwargs = dict(condition, ratio_milli=4000, retain=True)
            keep = kwargs.pop('candidate_count')
            summary, captures = (multiple if keep == 3 else single)(radio, **kwargs)
            if keep == 1:
                captures = [] if captures is None else [captures]
            row['summary'] = summary
            row['health'] = health(radio)
            check_health(row['health'], args, previous_run)
            previous_run = row['health']['run_id']
            if summary.get('background_policy') != 2 or any(
                summary.get(k, 0) for k in ('status', 'errors', 'pack_failed')
            ):
                raise RuntimeError('Detector policy/run error')
            row['gain_after'] = check_gain(radio.command('GAIN?'), 40)
            row['heap_retained'] = heap(radio)
            if radio.command('PIPEKEEP?') != 'PIPEKEEP 1':
                raise RuntimeError('One-shot retention selection did not reset')
            row['sigmf'] = []
            for candidate, capture in enumerate(captures):
                if not capture.crc_ok:
                    raise RuntimeError('Retained CRC failure')
                row['sigmf'].append(str(saver(capture, out / f'run-{index:04}-crop-{candidate}')))
            radio.command('DETPIPECLEAR')
            row['heap_cleared'] = heap(radio)
            if row['heap_cleared'] != baseline:
                raise RuntimeError('Heap leak/fragmentation after clear')
            fingerprint(f'run_{index}_after')
            row['tx_after'] = checked_status(tx, False)
            if row['tx_after']['completed'] != row['tx_before']['completed']:
                raise RuntimeError('Transmitter completed RF while expected stopped')
            row['status'] = 'passed'
            persist()
        report['status'] = 'passed'
    except BaseException as exc:
        error = exc
        report['status'] = 'failed'
        report['error'] = repr(exc)
        if report['runs'] and report['runs'][-1]['status'] == 'running':
            report['runs'][-1]['status'] = 'failed'
            report['runs'][-1]['error'] = repr(exc)
    finally:
        try:
            report['tx_final'] = stopped()
        except BaseException as exc:
            report['tx_cleanup_error'] = repr(exc)
            report['status'] = 'failed'
        if initial_gain and not getattr(radio, 'failed', False):
            try:
                radio.command('DETPIPECLEAR')
                for name, value in selectors.items():
                    radio.command(value)
                    if radio.command(name + '?') != value:
                        raise RuntimeError(f'Failed selector restoration: {name}')
                fields = initial_gain.split()
                radio.command(
                    'GAIN HARDWARE' if fields[1] == 'HARDWARE' else f'GAIN MANUAL {int(fields[2])}'
                )
                report['gain_restored'] = radio.command('GAIN?')
                if report['gain_restored'] != initial_gain:
                    raise RuntimeError('Failed gain restoration')
                report['receiver_final_version'] = radio.command('VERSION?')
            except BaseException as exc:
                report['receiver_cleanup_error'] = repr(exc)
                report['status'] = 'failed'
        elif getattr(radio, 'failed', False):
            report['receiver_cleanup_error'] = (
                'Framing uncertain; no further receiver commands attempted'
            )
            report['status'] = 'failed'
        if 'device' in report:
            try:
                fingerprint('stage_end')
            except Exception as exc:
                report['calibration_cleanup_error'] = type(exc).__name__
                report['status'] = 'failed'
        report['completed_runs'] = sum(row['status'] == 'passed' for row in report['runs'])
        report['planned_runs'] = len(conditions)
        persist()
    if error is not None:
        raise error
    return report


def main():
    args = parser().parse_args()
    if args.plan_only:
        conditions = plan(args.stage)
        print(
            json.dumps(
                dict(
                    plan=conditions,
                    planned_runs=len(conditions),
                    nominal_command_seconds=sum(r['milliseconds'] for r in conditions) / 1000,
                ),
                indent=2,
            )
        )
        return 0
    from nrf_tx.rf_tx import Transmitter

    radio = Radio(args.rx_port)
    try:
        with Transmitter(args.tx_port, serial_number=args.tx_serial) as tx:
            report = execute(args, radio, tx)
        print(
            json.dumps(
                dict(
                    status=report['status'],
                    completed_runs=report['completed_runs'],
                    planned_runs=report['planned_runs'],
                )
            )
        )
        return int(report['status'] != 'passed')
    finally:
        radio.close()


if __name__ == '__main__':
    raise SystemExit(main())
