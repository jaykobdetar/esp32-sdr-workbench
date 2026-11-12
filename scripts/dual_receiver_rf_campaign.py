# ruff: noqa: E402
# Resolve project-local and transmitter modules before their imports.
"""Private RF-anchor-calibrated trace campaign. Bounded RX and controlled TX."""

import argparse
import json
import os
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

os.umask(0o077)
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'nrf52840-transmitter/host')]
from analyze_nrf_iq import decode
from rf_tx import Transmitter

from sdr_research.dual_timing import clock_probe, coverage, read_trace, trace_windows
from sdr_research.pipeline import run_pipeline
from sdr_research.protocol import Radio, decode_iq
from sdr_research.recording import atomic_write_json, save_capture

parser = argparse.ArgumentParser(
    description='Experimental bounded two-receiver RF-clock and yield-phase campaign. No flashing. Dry-run by default.'
)
parser.add_argument('--port', action='append', required=True)
parser.add_argument('--tx-serial', required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--run', action='store_true')
parser.add_argument(
    '--staggered',
    action='store_true',
    help='After eight yield-phase probes, run a fixed 30-second observation with staggered readouts',
)
args = parser.parse_args()
ports = args.port
if len(ports) != 2 or len({str(Path(p).resolve()) for p in ports}) != 2:
    parser.error('Two distinct verified receiver ports required')
if not args.run:
    print(
        json.dumps(
            dict(
                mode='dry-run',
                receiver_ports=ports,
                source='nRF52840 explicit serial',
                frequency_mhz=2440,
                power_dbm=0,
                mode_mbps=2,
                packet_bytes=16,
                maximum_anchor_attempts=145 if args.staggered else 130,
                paired_pipeline_runs=8 if args.staggered else 14,
                staggered_chunks=[6, 7] if args.staggered else None,
                requested_pipeline_ms_per_receiver=38000,
                output=str(args.output),
                note='--run opens both receivers and starts bounded known RF test packets; explicit experimental firmware required.',
            )
        )
    )
    raise SystemExit(0)
OUT = args.output
OUT.mkdir(mode=0o700, parents=True, exist_ok=False)
radios = [Radio(p) for p in ports]
report = dict(status='running', anchors=[], anchor_pairs=[], runs=[])
YIELD_PHASES = [0, 16]


def save():
    atomic_write_json(OUT / 'results.json', report)


def raw(r, deadline, path):
    line = r.command(f'TIMEDCAP {deadline}')
    assert line.startswith('TIMEDCAP '), line
    trigger = int(line.split()[1])
    header = r._line().split()
    assert header[0] == 'DATA' and int(header[1]) == 16380
    payload = r._read(40950)
    assert zlib.crc32(payload) == int(header[2], 16)
    iq = decode_iq(payload, 16380, 10)
    np.save(path, iq)
    return dict(trigger_device_us=trigger, transport_crc_valid=True, file=str(path) + '.npy'), iq


def offset_at(a):
    anchors = report['anchors']
    if not anchors:
        return None
    if len(anchors) < 3:
        return anchors[-1]['b_minus_a_us']
    x = np.array([v['a_us'] for v in anchors[-12:]])
    y = np.array([v['b_minus_a_us'] for v in anchors[-12:]])
    if np.ptp(x) < 1e6:
        return float(np.median(y))
    m, b = np.polyfit(x - x.mean(), y, 1)
    return float(b + m * (a - x.mean()))


def anchor_block(tx, pool, needed=3, attempts=20):
    initial = len(report['anchors'])
    for _ in range(attempts):
        i = len(report['anchor_pairs'])
        tx.stop()
        clocks = list(pool.map(clock_probe, radios))
        target = time.monotonic_ns() / 1000 + 150000 + (i * 137) % 1000
        a = round(target + clocks[0]['offset_us'])
        delta = offset_at(a)
        deadlines = [
            a,
            round(a + delta) if delta is not None else round(target + clocks[1]['offset_us']),
        ]
        tx.start(count=4000, duration_ms=2000)
        values = [
            f.result()
            for f in [
                pool.submit(raw, r, deadlines[k], OUT / f'anchor-{i:03d}-rx{k}')
                for k, r in enumerate(radios)
            ]
        ]
        tx.stop()
        ds = [decode(v[1], 16000000, 2, 16) for v in values]
        matches = [
            {
                h['sequence']: h
                for h in d['full_payload_matches']
                if h['crc_verified'] and h['address_verified']
            }
            for d in ds
        ]
        pair = dict(
            index=i,
            receivers=[v[0] for v in values],
            clock=clocks,
            decoders=ds,
            tx_after=tx.status(),
        )
        report['anchor_pairs'].append(pair)
        for seq in sorted(matches[0].keys() & matches[1].keys()):
            t = [
                values[k][0]['trigger_device_us'] + matches[k][seq]['payload_start_sample'] / 16
                for k in range(2)
            ]
            report['anchors'].append(
                dict(pair=i, sequence=seq, a_us=t[0], b_us=t[1], b_minus_a_us=t[1] - t[0])
            )
        save()
        print(
            'anchor pair',
            i,
            'matches',
            list(map(len, matches)),
            'total anchors',
            len(report['anchors']),
            flush=True,
        )
        if len(report['anchors']) - initial >= needed:
            return
    raise RuntimeError('Insufficient common CRC-valid RF packets to align clocks')


def pipe(k, deadline, period, duration, retain):
    r = radios[k]
    r.command('TRACECLEAR')
    r.command(f'TRACEARM {deadline} {period} {YIELD_PHASES[k]}')
    s, cap = run_pipeline(
        r,
        milliseconds=duration,
        kernel=3,
        optimized=True,
        copy_option=1,
        retain=retain,
        background_policy=1,
    )
    assert not any(s.get(x, 0) for x in ('status', 'errors', 'pack_failed'))
    trace = read_trace(r)
    assert trace['count'] == s['captures']
    row = dict(summary=s, trace=trace)
    if cap is not None:
        row['file'] = str(save_capture(cap, OUT / f'run-{len(report["runs"]):03d}-rx{k}'))
    r.command('TRACECLEAR')
    r.command('DETPIPECLEAR')
    row['heap'] = r.command('DETPIPEMEM?')
    return row


try:
    with Transmitter(serial_number=args.tx_serial) as tx, ThreadPoolExecutor(2) as pool:
        tx.stop()
        report['tx_initial'] = tx.status()
        report['devices'] = [r.connect() for r in radios]
        for r in radios:
            if 'DUALTIMING' not in r.info['caps']:
                raise RuntimeError('Experimental DUALTIMING firmware required; nothing flashed')
            r.command('TRACECLEAR')
            r.command('DETPIPECLEAR')
            r.configure(2440, 16000000, 12, 60, 10)
            r.command('ACQOPT 3')
            r.command('CLEAROPT 1')
        report['calibration_before'] = [r.command('CALHASH?') for r in radios]
        config = dict(
            frequency_mhz=2440,
            mode_mbps=2,
            power_dbm=0,
            payload_len=16,
            interval_us=1000,
            jitter_us=113,
            hop_list='off',
            hop_every=1,
            burst_count=0,
            burst_gap_us=0,
            payload_hex='off',
            seed=52840,
        )
        tx.configure(**config)
        report['tx_configuration'] = config
        save()
        anchor_block(tx, pool, needed=3, attempts=40)
        schedule = [(1875, 938, 1000, False) for _ in range(8)]
        if not args.staggered:
            schedule += [(1875, 938, 5000, False) for _ in range(6)]
        for index, (period, phase, duration, retain) in enumerate(schedule):
            if index and index % 5 == 0:
                anchor_block(tx, pool, needed=2, attempts=25)
            tx.stop()
            clock = clock_probe(radios[0], 30)
            target = time.monotonic_ns() / 1000 + 250000
            a = int(np.ceil((target + clock['offset_us']) / 1000) * 1000)
            delta = offset_at(a)
            if index >= 8:
                # Center the expected relative drift over the finite five-second window.
                recent = report['anchors']
                xx = np.array([v['a_us'] for v in recent])
                yy = np.array([v['b_minus_a_us'] for v in recent])
                drift = np.polyfit(xx - xx.mean(), yy, 1)[0]
                phase = round(period / 2 + drift * duration * 1000 / 2)
            b = round(a + delta + phase)
            if index < 8:
                YIELD_PHASES[:] = [index, index]
            else:
                for k, deadline in enumerate((a, b)):
                    best = min(
                        report['runs'][:8],
                        key=lambda q: q['receivers'][k]['trace']['max_schedule_late_us'],
                    )
                    old_deadline = best['scheduled_a_us'] if k == 0 else best['scheduled_b_us']
                    old_phase = best['yield_phases'][k]
                    wanted = (old_deadline + old_phase * period) % 1000
                    YIELD_PHASES[k] = min(
                        range(8),
                        key=lambda phase: abs(
                            ((deadline + phase * period - wanted + 500) % 1000) - 500
                        ),
                    )
            values = [
                f.result()
                for f in [
                    pool.submit(pipe, k, d, period, duration, retain) for k, d in enumerate((a, b))
                ]
            ]
            row = dict(
                yield_phases=list(YIELD_PHASES),
                index=index,
                period_us=period,
                phase_us=phase,
                duration_ms=duration,
                retain=retain,
                scheduled_a_us=a,
                scheduled_b_us=b,
                receivers=values,
                offset_estimate_us=delta,
            )
            windows = trace_windows(values[0]['trace']) + trace_windows(values[1]['trace'], delta)
            row['provisional_nominal_union'] = coverage(windows, a, a + duration * 1000)
            report['runs'].append(row)
            save()
            print(
                'run',
                index,
                period,
                phase,
                round(row['provisional_nominal_union']['coverage_percent'], 4),
                'maxgap',
                round(row['provisional_nominal_union']['max_gap_us'], 2),
                'yields',
                YIELD_PHASES,
                'late',
                [v['trace']['max_schedule_late_us'] for v in values],
                flush=True,
            )
        if args.staggered:
            # Establish an RF clock fit, then keep independent finite runs going with staggered readouts.
            anchor_block(tx, pool, needed=3, attempts=40)
            aa = report['anchors']
            xx = np.array([q['a_us'] for q in aa])
            yy = np.array([q['b_us'] for q in aa])
            x0 = xx.mean()
            y0 = yy.mean()
            slope = float(np.dot(xx - x0, yy - y0) / np.dot(xx - x0, xx - x0))
            anchor_now = int(radios[0].command('CLOCK?').split()[1])
            grid = int(np.ceil((anchor_now + 500000) / 1875) * 1875)
            bests = [
                min(
                    report['runs'][:8],
                    key=lambda q: q['receivers'][k]['trace']['max_schedule_late_us'],
                )
                for k in range(2)
            ]

            def stream(k):
                chunks = []
                r = radios[k]
                durations = [5000] * 6 if k == 0 else [2500] + [5000] * 5 + [2500]
                for j, duration in enumerate(durations):
                    if j == 0:
                        target_a = grid
                    else:
                        device_now = int(r.command('CLOCK?').split()[1])
                        now_a = device_now if k == 0 else x0 + (device_now - y0) / slope
                        target_a = grid + int(np.ceil((now_a + 100000 - grid) / 1875)) * 1875
                    phase = 1875 / 2 + (slope - 1) * duration * 1000 / 2
                    deadline = target_a if k == 0 else round(y0 + slope * (target_a - x0) + phase)
                    best = bests[k]
                    old = best['scheduled_a_us'] if k == 0 else best['scheduled_b_us']
                    wanted = (old + best['yield_phases'][k] * 1875) % 1000
                    yp = min(
                        range(8),
                        key=lambda q: abs(((deadline + q * 1875 - wanted + 500) % 1000) - 500),
                    )
                    r.command('TRACECLEAR')
                    r.command(f'TRACEARM {deadline} 1875 {yp}')
                    summary, cap = run_pipeline(
                        r,
                        milliseconds=duration,
                        kernel=3,
                        optimized=True,
                        copy_option=1,
                        retain=False,
                        background_policy=1,
                    )
                    assert not any(summary.get(q, 0) for q in ('status', 'errors', 'pack_failed'))
                    trace = read_trace(r)
                    assert trace['count'] == summary['captures']
                    r.command('TRACECLEAR')
                    r.command('DETPIPECLEAR')
                    row = dict(
                        receiver=k,
                        index=j,
                        duration_ms=duration,
                        deadline_us=deadline,
                        yield_phase=yp,
                        summary=summary,
                        trace=trace,
                    )
                    atomic_write_json(OUT / f'stream-rx{k}-{j}.json', row)
                    chunks.append(row)
                    print('stream', k, j, trace['count'], flush=True)
                return chunks

            report['stream_model'] = dict(
                a_origin_us=x0, b_origin_us=y0, slope=slope, grid_a_us=grid
            )
            report['stream_chunks'] = [
                f.result() for f in [pool.submit(stream, k) for k in range(2)]
            ]
            save()
            anchor_block(tx, pool, needed=3, attempts=40)
        if not args.staggered:
            anchor_block(tx, pool, needed=3, attempts=40)
        tx.stop()
        report['tx_final'] = tx.status()
        report['calibration_after'] = [r.command('CALHASH?') for r in radios]
        report['status'] = 'passed'
        save()
except BaseException as e:
    report.update(status='failed', error=repr(e))
    save()
    raise
finally:
    for r in radios:
        r.close()
