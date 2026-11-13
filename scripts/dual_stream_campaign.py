"""Private RF-clock anchored persistent dual-receiver campaign; no flashing.
Run as python -m nrf_campaigns.dual_stream_campaign. Dry-run unless --run.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event

import numpy as np
from nrf_tx.rf_tx import Transmitter

from sdr_research.detector_stream import APERTURE_US, END, run_stream, validate_saved_record
from sdr_research.dual_timing import clock_probe, coverage
from sdr_research.protocol import Radio, decode_iq
from sdr_research.recording import atomic_write_json

from .analyze_nrf_iq import decode


def fit_clock(anchors):
    if len(anchors) < 3:
        raise ValueError('Three shared CRC-valid anchors required')
    a = np.asarray([v['a_us'] for v in anchors], dtype=float)
    b = np.asarray([v['b_us'] for v in anchors], dtype=float)
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError('Non-finite clock anchor')
    if np.ptp(a) < 1:
        raise ValueError('Clock anchors lack time span')
    origin = float(a.mean())
    slope, offset = np.polyfit(a - origin, b - a, 1)
    residual = b - a - (offset + slope * (a - origin))
    if not np.isfinite(slope) or abs(slope) > 0.01:
        raise ValueError('Implausible relative clock drift')
    return dict(
        origin_a_us=origin,
        offset_b_minus_a_us=float(offset),
        relative_drift=float(slope),
        anchor_count=len(a),
        span_us=float(np.ptp(a)),
        max_residual_us=float(np.max(np.abs(residual))),
        rms_residual_us=float(np.sqrt(np.mean(residual**2))),
    )


def to_a(t, model):
    return (t - model['offset_b_minus_a_us'] + model['relative_drift'] * model['origin_a_us']) / (
        1 + model['relative_drift']
    )


def delta_at(a, model):
    return model['offset_b_minus_a_us'] + model['relative_drift'] * (a - model['origin_a_us'])


def _validate_stream_result(result):
    """Recheck saved evidence rather than trust a cached validity label."""
    summary = result['summary']
    records = result['records']
    if result['transport_crc_valid'] is not True or summary['status'] != 0 or summary['overflow']:
        raise ValueError('Incomplete streaming measurement')
    count = len(records)
    if not count or summary['captures'] != count or summary['processed'] != count:
        raise ValueError('Missing streaming records')
    events = 0
    last = 0
    for i, record in enumerate(records, 1):
        validate_saved_record(record)
        t = record['trigger_us']
        flags = record['flags']
        if not np.isfinite(t) or t <= last or record['sequence'] != i:
            raise ValueError('Non-contiguous or non-monotonic streaming records')
        if flags not in (0, 2, 3) or bool(flags & 2) != (i > 16):
            raise ValueError('Invalid decision flags')
        events += bool(flags & 1)
        if record['events_total'] != events:
            raise ValueError('Invalid event counters')
        last = t
    terminal = result['terminal']
    validate_saved_record(terminal)
    if (
        terminal['flags'] != END
        or terminal['sequence'] != count
        or terminal['events_total'] != events
        or terminal['mean_adc2'] != summary['status']
        or terminal['trigger_us'] != summary['end_us']
        or terminal['background_adc2'] != summary['skipped']
        or terminal['peak_adc2'] != summary['max_late_us']
    ):
        raise ValueError('Terminal record disagrees with summary')
    if (
        summary['events'] != events
        or summary['first_trigger_us'] != records[0]['trigger_us']
        or summary['last_trigger_us'] != last
        or not np.isfinite(summary['end_us'])
        or summary['end_us'] < last
        or summary['skipped'] < 0
        or summary['max_late_us'] < 0
    ):
        raise ValueError('Invalid final stream accounting')


def analyze_run(row, anchors):
    try:
        start = row['scheduled_a_us']
        end = start + row['duration_ms'] * 1000
        if not np.isfinite(start) or not np.isfinite(end) or end <= start:
            raise ValueError('Invalid requested observation window')
        if len(row['receivers']) != 2:
            raise ValueError('Exactly two receiver results required')
        for result in row['receivers']:
            _validate_stream_result(result)
        ordered = sorted(anchors, key=lambda a: a['a_us'])

        def nearest_pairs(candidates):
            selected, labels = [], set()
            for anchor in candidates:
                label = anchor.get('pair')
                if label not in labels and len(labels) >= 8:
                    break
                labels.add(label)
                selected.append(anchor)
            return selected

        # Limit independent capture pairs, not packets: one capture can decode
        # many packets and must never crowd out independent observations.
        before = nearest_pairs(reversed([a for a in ordered if a['a_us'] < start]))
        after = nearest_pairs([a for a in ordered if a['a_us'] > end])
        if not before or not after:
            raise ValueError('Missing bracketing RF anchors')
        if any('pair' not in anchor for anchor in before + after):
            raise ValueError('Missing independent capture-pair labels')
        before_groups = {anchor['pair'] for anchor in before}
        after_groups = {anchor['pair'] for anchor in after}
        if len(before_groups) < 3 or len(after_groups) < 3 or before_groups & after_groups:
            raise ValueError('Three distinct independent capture pairs required on each side')
        selected = before + after
        model = fit_clock(selected)
        # Screening limits, not certified timing uncertainty bounds.
        if abs(model['relative_drift']) > 0.001 or model['max_residual_us'] > 20:
            raise ValueError('Clock fit exceeds 1000 ppm / 20 us screening limits')
        # Leave out whole capture pairs, not individual packets from one capture.
        groups = {a.get('pair', i) for i, a in enumerate(selected)}
        heldout = []
        evaluated_folds = 0
        for group in groups:
            train = [a for i, a in enumerate(selected) if a.get('pair', i) != group]
            test = [a for i, a in enumerate(selected) if a.get('pair', i) == group]
            if len(train) < 3:
                continue
            fitted = fit_clock(train)
            evaluated_folds += 1
            heldout.extend(abs(to_a(a['b_us'], fitted) - a['a_us']) for a in test)
        model['heldout_max_error_us'] = max(heldout) if heldout else None
        model['independent_capture_pair_count'] = len(groups)
        model['before_capture_pair_count'] = len(before_groups)
        model['after_capture_pair_count'] = len(after_groups)
        model['heldout_evaluated_fold_count'] = evaluated_folds
        if evaluated_folds < 3:
            raise ValueError('At least three evaluated independent held-out folds required')
        if heldout and max(heldout) > 20:
            raise ValueError('Held-out clock error exceeds 20 us screen')
        windows = []
        receiver_windows = [[], []]
        decisions = []
        for k, result in enumerate(row['receivers']):
            scale = 1 + model['relative_drift'] if k else 1
            for r in result['records']:
                t = to_a(r['trigger_us'], model) if k else r['trigger_us']
                window = (t, t + APERTURE_US / scale)
                windows.append(window)
                receiver_windows[k].append(window)
                if r['flags'] & 2:
                    decisions.append((t, t + (16320 / 16) / scale))
        sensitivity = []
        for uncertainty_us in (1, 5, 20):
            shifted = {}
            for sign in (-1, 1):
                offset = sign * uncertainty_us
                shifted[str(offset)] = coverage(
                    receiver_windows[0]
                    + [(a + offset, b + offset) for a, b in receiver_windows[1]],
                    start,
                    end,
                )
            # Erode both receivers' windows: conservative only under the explicit
            # assumption that each nominal endpoint error is bounded by this value.
            eroded = [
                (a + uncertainty_us, b - uncertainty_us)
                for a, b in windows
                if b - a > 2 * uncertainty_us
            ]
            sensitivity.append(
                dict(
                    assumed_endpoint_error_us=uncertainty_us,
                    receiver_b_offset_scenarios=shifted,
                    eroded_union=coverage(eroded, start, end),
                )
            )
        return dict(
            status='verified-telemetry',
            sensitivity=sensitivity,
            sensitivity_note='Assumption-based scenarios, not confidence bounds. Offset scenarios shift receiver B only; erosion removes the assumed error at both ends of every receiver window. Bracketing anchors cannot rule out nonlinear drift within the run.',
            clock_model=model,
            nominal_union=coverage(windows, start, end),
            nominal_decision_union=coverage(decisions, start, end),
            note='Nominal trigger+N/fs, not calibrated RF aperture or packet recall. Residual and held-out errors are empirical, not certified bounds.',
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return dict(status='unverified', reason=str(exc))


class Campaign:
    def __init__(self, radios, tx, pool, output):
        self.radios, self.tx, self.pool, self.out = radios, tx, pool, output
        self.report = dict(status='running', anchors=[], anchor_pairs=[], runs=[])

    def save(self):
        atomic_write_json(self.out / 'results.json', self.report)

    def raw(self, r, deadline, path):
        reply = r.command(f'TIMEDCAP {deadline}')
        if not reply.startswith('TIMEDCAP '):
            raise ValueError(reply)
        trigger = int(reply.split()[1])
        h = r._line().split()
        if h[0] != 'DATA' or int(h[1]) != 16380:
            raise ValueError('Invalid anchor header')
        data = r._read(40950)
        if zlib.crc32(data) != int(h[2], 16):
            raise ValueError('Anchor transport CRC failed')
        iq = decode_iq(data, 16380, 10)
        np.save(path, iq)
        return dict(trigger_us=trigger, transport_crc_valid=True, file=path.name + '.npy'), iq

    def anchors(self, needed=3, attempts=40):
        initial_pairs = {a['pair'] for a in self.report['anchors']}
        for _ in range(attempts):
            i = len(self.report['anchor_pairs'])
            self.tx.stop()
            clocks = list(self.pool.map(clock_probe, self.radios))
            target = time.monotonic_ns() / 1000 + 200000 + (i * 137) % 1000
            a = round(target + clocks[0]['offset_us'])
            previous = self.report['anchors']
            delta = (
                delta_at(a, fit_clock(previous[-12:]))
                if len(previous) >= 3
                else (previous[-1]['b_us'] - previous[-1]['a_us'] if previous else None)
            )
            deadlines = [
                a,
                round(a + delta) if delta is not None else round(target + clocks[1]['offset_us']),
            ]
            self.tx.start(count=4000, duration_ms=2000)
            futures = [
                self.pool.submit(self.raw, r, deadlines[k], self.out / f'anchor-{i:04d}-rx{k}')
                for k, r in enumerate(self.radios)
            ]
            try:
                values = [f.result() for f in futures]
            finally:
                self.tx.stop()
                for future in futures:
                    try:
                        future.result()
                    except BaseException:
                        pass
            decoded = [decode(v[1], 16000000, 2, 16) for v in values]
            matches = [
                {
                    h['sequence']: h
                    for h in d['full_payload_matches']
                    if h['crc_verified'] and h['address_verified']
                }
                for d in decoded
            ]
            self.report['anchor_pairs'].append(
                dict(
                    index=i, receivers=[v[0] for v in values], decoders=decoded, tx=self.tx.status()
                )
            )
            for seq in sorted(matches[0].keys() & matches[1].keys()):
                ts = [
                    values[k][0]['trigger_us'] + matches[k][seq]['payload_start_sample'] / 16
                    for k in range(2)
                ]
                self.report['anchors'].append(dict(pair=i, sequence=seq, a_us=ts[0], b_us=ts[1]))
            self.save()
            print(
                'anchor',
                i,
                'matches',
                list(map(len, matches)),
                'total',
                len(self.report['anchors']),
                flush=True,
            )
            if len({a['pair'] for a in self.report['anchors']} - initial_pairs) >= needed:
                return
        raise RuntimeError(
            'Insufficient independent capture pairs with common CRC-valid RF packets'
        )

    def run(self, duration_ms, period_ns, phases, compensate=True):
        self.tx.stop()
        model = fit_clock(self.report['anchors'][-12:])
        c = clock_probe(self.radios[0])
        target = time.monotonic_ns() / 1000 + 250000
        a = round((target + c['offset_us']) / 1000) * 1000
        b = round(a + delta_at(a, model) + period_ns / 2000)
        periods = [
            period_ns,
            round(period_ns * (1 + model['relative_drift'])) if compensate else period_ns,
        ]
        stop = Event()
        futures = [
            self.pool.submit(
                run_stream,
                r,
                start_us=d,
                milliseconds=duration_ms,
                period_ns=periods[k],
                yield_phase=phases[k],
                stop=stop,
            )
            for k, (r, d) in enumerate(zip(self.radios, [a, b], strict=True))
        ]
        try:
            for future in as_completed(futures):
                future.result()
            results = [f.result() for f in futures]
        except BaseException:
            stop.set()
            # Do not close a serial port while its worker still uses it.
            for future in futures:
                try:
                    future.result()
                except BaseException:
                    pass
            raise
        row = dict(
            index=len(self.report['runs']),
            scheduled_a_us=a,
            scheduled_b_us=b,
            duration_ms=duration_ms,
            periods_ns=periods,
            yield_phases=phases,
            receivers=results,
            clock_prediction=model,
            calibration_after=[r.command('CALHASH?') for r in self.radios],
        )
        self.report['runs'].append(row)
        self.save()
        print(
            'stream',
            row['index'],
            duration_ms,
            'counts',
            [x['summary']['captures'] for x in results],
            'late',
            [x['summary']['max_late_us'] for x in results],
            flush=True,
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', action='append', required=True)
    p.add_argument('--tx-serial', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run', action='store_true')
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--trials', type=int, default=3)
    p.add_argument('--period-ns', type=int, default=1875000)
    p.add_argument('--phases', default='0,0')
    p.add_argument('--phase-sweep', action='store_true')
    p.add_argument('--no-drift-compensation', action='store_true')
    args = p.parse_args()
    phases = list(map(int, args.phases.split(',')))
    if len(args.port) != 2 or len({str(Path(x).resolve()) for x in args.port}) != 2:
        p.error('Two distinct verified ports required')
    if len(phases) != 2 or any(not 0 <= x <= 33 for x in phases):
        p.error('Two phases in 0..33 required')
    if not 1 <= args.seconds <= 600 or not 1 <= args.trials <= 20:
        p.error('Seconds 1..600, trials 1..20')
    if not 1600000 <= args.period_ns <= 10000000:
        p.error('Period outside firmware range')
    if not args.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    seconds=args.seconds,
                    trials=args.trials,
                    phase_sweep=args.phase_sweep,
                    transmitter=dict(frequency_mhz=2440, power_dbm=0, mode_mbps=2, payload_len=16),
                    note='Explicit --run required. Private output includes raw RF and device details.',
                )
            )
        )
        return
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    radios = [Radio(x) for x in args.port]
    with Transmitter(serial_number=args.tx_serial) as tx, ThreadPoolExecutor(2) as pool:
        campaign = Campaign(radios, tx, pool, args.output)
        report = campaign.report
        try:
            tx.stop()
            report['tx_before'] = tx.status()
            report['devices'] = [r.connect() for r in radios]
            for r in radios:
                if 'DSTREAM' not in r.info['caps']:
                    raise ValueError('DSTREAM firmware required')
                r.command('TRACECLEAR')
                r.command('DETPIPECLEAR')
                r.configure(2440, 16000000, 12, 60, 10)
                r.command('ACQOPT 3')
                r.command('CLEAROPT 1')
                r.command('BGPOLICY 1')
            report['calibration_before'] = [r.command('CALHASH?') for r in radios]
            tx.configure(
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
            campaign.anchors(needed=8, attempts=60)
            if args.phase_sweep:
                for phase in range(8):
                    campaign.run(1000, args.period_ns, [phase, phase])
                campaign.anchors(needed=3)
                for row in report['runs']:
                    row['analysis'] = analyze_run(row, report['anchors'])
                verified = [
                    r for r in report['runs'] if r['analysis']['status'] == 'verified-telemetry'
                ]
                if not verified:
                    raise RuntimeError('No verified phase-sweep result')
                best = min(verified, key=lambda r: r['analysis']['nominal_union']['max_gap_us'])
                phases = best['yield_phases']
            for _ in range(args.trials):
                campaign.run(
                    round(args.seconds * 1000),
                    args.period_ns,
                    phases,
                    not args.no_drift_compensation,
                )
                campaign.anchors(needed=3)
                for row in report['runs']:
                    row['analysis'] = analyze_run(row, report['anchors'])
                row = report['runs'][-1]
                if row['analysis']['status'] != 'verified-telemetry':
                    raise RuntimeError('Unverified coverage: ' + row['analysis']['reason'])
                print(
                    'coverage',
                    row['analysis']['nominal_union']['coverage_percent'],
                    'worst-gap-us',
                    row['analysis']['nominal_union']['max_gap_us'],
                    flush=True,
                )
            report['status'] = 'passed'
        except BaseException as exc:
            report['status'] = 'failed'
            report['error'] = repr(exc)
            raise
        finally:
            try:
                tx.stop()
                report['tx_final'] = tx.status()
            finally:
                for r in radios:
                    r.close()
                campaign.save()


if __name__ == '__main__':
    main()
