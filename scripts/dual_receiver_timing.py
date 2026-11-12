#!/usr/bin/env python3
"""Bounded two-board experimental timing run; no flashing and no RF transmitter."""

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdr_research.dual_timing import clock_probe, coverage, read_trace, trace_windows
from sdr_research.pipeline import run_pipeline
from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json, save_capture


def one_receiver(port, start_state, barrier, period, phase, yield_phase, duration, retain, output):
    radio = Radio(port)
    report = dict(port=port, status='running')
    try:
        report['device'] = radio.connect()
        if 'DUALTIMING' not in report['device']['caps']:
            raise ValueError('Experimental DUALTIMING firmware required; nothing flashed')
        radio.configure(2440, 16000000, 12, 40, 10)
        radio.command('TRACECLEAR')
        report['clock_before'] = clock_probe(radio, 50)
        # Schedule only after BOTH devices finish configuration and clock probes.
        barrier.wait(timeout=15)
        target = start_state['target']
        deadline = round(target + report['clock_before']['offset_us'] + phase)
        if time.monotonic_ns() / 1000 > target - 50000:
            raise ValueError('Shared start deadline too close; refusing a partial schedule')
        radio.command(f'TRACEARM {deadline} {period} {yield_phase}')
        summary, cap = run_pipeline(
            radio,
            milliseconds=duration,
            kernel=3,
            optimized=True,
            copy_option=1,
            retain=retain,
            background_policy=1,
        )
        if any(summary.get(k, 0) for k in ('status', 'errors', 'pack_failed')):
            raise ValueError('Pipeline failed')
        report['summary'] = summary
        report['trace'] = read_trace(radio)
        if report['trace']['count'] != summary['captures']:
            raise ValueError('Trace count mismatch')
        report['clock_after'] = clock_probe(radio, 50)
        if cap is not None:
            report['capture'] = str(save_capture(cap, output))
        radio.command('TRACECLEAR')
        radio.command('DETPIPECLEAR')
        report['final_heap'] = radio.command('DETPIPEMEM?')
        report['status'] = 'passed'
    except BaseException as error:
        barrier.abort()
        report.update(status='failed', error=repr(error))
    finally:
        radio.close()
    return report


def run(ports, out, period=0, phase=0, duration=1000, retain=False):
    if len(set(str(Path(p).resolve()) for p in ports)) != 2:
        raise ValueError('Two distinct resolved ports required')
    if period != 0 and not 1600 <= period <= 10000:
        raise ValueError('Period must be 0 or 1600..10000 us')
    if not 0 <= phase <= 10000 or not 100 <= duration <= 5000:
        raise ValueError('Invalid bounded schedule')
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    start_state = {}
    barrier = threading.Barrier(
        2, action=lambda: start_state.update(target=time.monotonic_ns() / 1000 + 500_000)
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                one_receiver,
                p,
                start_state,
                barrier,
                period,
                phase if i else 0,
                16 if i else 0,
                duration,
                retain,
                out / f'rx{i}',
            )
            for i, p in enumerate(ports)
        ]
        receivers = [f.result() for f in futures]
    result = dict(
        status='passed' if all(r['status'] == 'passed' for r in receivers) else 'failed',
        target_host_us=start_state.get('target'),
        period_us=period,
        phase_us=phase,
        duration_ms=duration,
        retain=retain,
        receivers=receivers,
        timing_note='Trigger timestamps plus nominal N/fs. Serial-clock midpoint estimates, not measured RF union or packet recall. Scheduler and transfer gaps remain.',
    )
    if result['status'] == 'passed':
        target = start_state['target']
        intervals = []
        for receiver in receivers:
            offset = receiver['clock_before']['offset_us']
            windows = trace_windows(receiver['trace'], offset)
            receiver['mapped_nominal_coverage'] = coverage(
                windows, target, target + duration * 1000
            )
            intervals.extend(windows)
        result['mapped_nominal_union'] = coverage(intervals, target, target + duration * 1000)
        result['summed_nominal_duty_percent'] = sum(
            r['mapped_nominal_coverage']['coverage_percent'] for r in receivers
        )
    atomic_write_json(out / 'results.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--period-us', type=int, default=0)
    parser.add_argument('--phase-us', type=int, default=0)
    parser.add_argument('--duration-ms', type=int, default=1000)
    parser.add_argument('--retain', action='store_true')
    args = parser.parse_args()
    if len(args.port) != 2:
        parser.error('Exactly two --port arguments required')
    result = run(
        args.port, args.output, args.period_us, args.phase_us, args.duration_ms, args.retain
    )
    print(json.dumps({k: v for k, v in result.items() if k != 'receivers'}, indent=2))
    if result['status'] != 'passed':
        print(json.dumps(result['receivers'], indent=2))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
