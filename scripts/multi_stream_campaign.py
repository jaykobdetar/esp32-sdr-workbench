"""Bounded two-to-four receiver RF-anchor campaign. Dry-run unless --run.

Independent receiver clocks map to receiver zero, never host delivery time.
Results are nominal acquisition-window coverage, not packet recall.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import itertools
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event

from nrf_tx.rf_tx import Transmitter

from sdr_research.calibration import record_calibration
from sdr_research.detector_stream import APERTURE_US, run_stream
from sdr_research.dual_timing import clock_probe, coverage
from sdr_research.protocol import Radio

from .analyze_nrf_iq import decode
from .dual_stream_campaign import (
    Campaign as DualCampaign,
)
from .dual_stream_campaign import (
    analyze_run as analyze_pair,
)
from .dual_stream_campaign import (
    delta_at,
    fit_clock,
    full_burst_opportunity,
    to_a,
)

_SOURCE_FILES = {
    'scripts/multi_stream_campaign.py': __file__,
    'scripts/dual_stream_campaign.py': inspect.getsourcefile(DualCampaign),
    'sdr_research/detector_stream.py': inspect.getsourcefile(run_stream),
    'sdr_research/protocol.py': inspect.getsourcefile(Radio),
    'scripts/analyze_nrf_iq.py': inspect.getsourcefile(decode),
    'sdr_research/calibration.py': inspect.getsourcefile(record_calibration),
}


def source_provenance():
    """Hash actual imported source files; expose only stable repo-relative labels."""
    return {
        name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for name, path in _SOURCE_FILES.items()
    }


def analyze_run(row, anchors):
    """Require every reference-to-device fit to pass the existing independent screens."""
    try:
        if row.get('status') == 'rejected':
            raise ValueError('Rejected streaming attempt is not accepted coverage evidence')
        count = len(row['receivers'])
        if not 2 <= count <= 4:
            raise ValueError('Two to four receiver results required')
        models = [None]
        pair_diagnostics = []
        for k in range(1, count):
            pair_row = dict(row, receivers=[row['receivers'][0], row['receivers'][k]])
            selected = [a for a in anchors if a.get('receiver_index') == k]
            result = analyze_pair(pair_row, selected)
            if result['status'] != 'verified-telemetry':
                raise ValueError(f'Receiver {k} clock/telemetry: {result["reason"]}')
            models.append(result['clock_model'])
            pair_diagnostics.append(result['clock_model'])
        start, end = (
            pair_row['scheduled_a_us'],
            pair_row['scheduled_a_us'] + row['duration_ms'] * 1000,
        )
        windows, decisions, by_receiver = [], [], []
        completions = []
        for k, result in enumerate(row['receivers']):
            model = models[k]
            scale = 1 + model['relative_drift'] if model else 1
            own = []
            for record in result['records']:
                t = to_a(record['trigger_us'], model) if model else record['trigger_us']
                own.append((t, t + APERTURE_US / scale))
                if record['flags'] & 2:
                    decisions.append((t, t + 1020 / scale))
            by_receiver.append(own)
            windows.extend(own)
            terminal = result['terminal']['trigger_us']
            completions.append(to_a(terminal, model) if model else terminal)
        sensitivity = []
        for error in (1, 5, 20):
            scenarios = []
            for offsets in itertools.product((-error, error), repeat=count - 1):
                shifted = by_receiver[0] + [
                    (a + offsets[k - 1], b + offsets[k - 1])
                    for k in range(1, count)
                    for a, b in by_receiver[k]
                ]
                scenarios.append(
                    dict(receiver_offsets_us=[0, *offsets], union=coverage(shifted, start, end))
                )
            eroded = [(a + error, b - error) for a, b in windows if b - a > 2 * error]
            sensitivity.append(
                dict(
                    assumed_endpoint_error_us=error,
                    offset_corner_scenarios=scenarios,
                    eroded_union=coverage(eroded, start, end),
                )
            )
        return dict(
            status='verified-telemetry',
            receiver_count=count,
            clock_models_to_reference=pair_diagnostics,
            requested_window_a_us=[start, end],
            nominal_union=coverage(windows, start, end),
            nominal_decision_union=coverage(decisions, start, end),
            nominal_completion_inclusive_union=coverage(windows, start, max(completions)),
            nominal_receiver_unions=[coverage(w, start, end) for w in by_receiver],
            nominal_full_burst_opportunities=[
                full_burst_opportunity(windows, start, end, d) for d in (50, 100, 250, 500)
            ],
            sensitivity=sensitivity,
            sensitivity_note='Assumed endpoint errors and constant-offset corner scenarios, not confidence bounds or exhaustive nonlinear-drift bounds.',
            note='Nominal trigger+N/fs on receiver-zero time, not calibrated RF aperture, continuous retained IQ, packet recall or Quest compatibility. All clocks independently RF-anchored to reference; fit residuals are not certified bounds.',
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return dict(status='unverified', reason=str(exc))


class Campaign(DualCampaign):
    def __init__(self, radios, tx, pool, output, *, source_hashes=None):
        if not 2 <= len(radios) <= 4 or len({id(r) for r in radios}) != len(radios):
            raise ValueError('Two to four distinct receiver objects required')
        hashes = source_provenance() if source_hashes is None else dict(source_hashes)
        super().__init__(radios, tx, pool, output)
        self.report['source_sha256'] = hashes

    def check_calibration(self, boundary):
        states = self.report.setdefault('calibration_by_receiver', [{} for _ in self.radios])
        observations = []
        errors = []
        for k, r in enumerate(self.radios):
            try:
                value = record_calibration(states[k], r, r.info, boundary, required=True)
                observations.append(value)
                observed = [
                    v for v in states[k]['calibration_observations'] if v['status'] == 'observed'
                ]
                if value['sha256'] != observed[0]['sha256'] or value['device_clock_regressed']:
                    raise RuntimeError('Stored calibration changed or device clock regressed')
            except BaseException as exc:
                errors.append(f'Receiver {k}: {exc}')
        if errors:
            raise RuntimeError('; '.join(errors))
        return observations

    def cleanup(self):
        """Attempt every cleanup step; a failed STOP must not skip receivers."""
        errors = []
        try:
            self.tx.stop()
        except BaseException as exc:
            errors.append(f'Transmitter STOP unverified: {exc}')
        try:
            self.report['tx_final'] = self.tx.status()
            if self.report['tx_final'].get('running') is not False:
                raise RuntimeError('Transmitter did not report running=false')
        except BaseException as exc:
            errors.append(f'Transmitter final status unverified: {exc}')
        try:
            self.report['calibration_final'] = self.check_calibration('cleanup')
        except BaseException as exc:
            errors.append(f'Final calibration unverified: {exc}')
        for k, r in enumerate(self.radios):
            try:
                r.close()
            except BaseException as exc:
                errors.append(f'Receiver {k} close failed: {exc}')
        self.report['cleanup_errors'] = errors
        if errors:
            self.report['status'] = 'failed'
        elif self.report['status'] == 'validated':
            self.report['status'] = 'passed'
        return errors

    def anchors(self, needed=3, attempts=60):
        count = len(self.radios)
        initial = [
            {a['pair'] for a in self.report['anchors'] if a.get('receiver_index') == k}
            for k in range(count)
        ]
        for _ in range(attempts):
            i = len(self.report['anchor_pairs'])
            self.tx.stop()
            clocks = list(self.pool.map(clock_probe, self.radios))
            target = time.monotonic_ns() / 1000 + 300000 + (i * 137) % 1000
            a = round(target + clocks[0]['offset_us'])
            deadlines = [a]
            for k in range(1, count):
                previous = [x for x in self.report['anchors'] if x.get('receiver_index') == k]
                delta = (
                    delta_at(a, fit_clock(previous[-12:]))
                    if len(previous) >= 3
                    else (previous[-1]['b_us'] - previous[-1]['a_us'] if previous else None)
                )
                deadlines.append(
                    round(a + delta)
                    if delta is not None
                    else round(target + clocks[k]['offset_us'])
                )
            self.tx.start(count=4000, duration_ms=2000)
            futures = [
                self.pool.submit(self.raw, r, deadlines[k], self.out / f'anchor-{i:04d}-rx{k}')
                for k, r in enumerate(self.radios)
            ]
            try:
                values = [f.result() for f in futures]
            finally:
                try:
                    self.tx.stop()
                finally:
                    # Readers must finish before any outer cleanup closes their ports.
                    for f in futures:
                        try:
                            f.result()
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
            for k in range(1, count):
                for seq in sorted(matches[0].keys() & matches[k].keys()):
                    ts = [
                        values[j][0]['trigger_us'] + matches[j][seq]['payload_start_sample'] / 16
                        for j in (0, k)
                    ]
                    self.report['anchors'].append(
                        dict(pair=i, sequence=seq, a_us=ts[0], b_us=ts[1], receiver_index=k)
                    )
            self.save()
            groups = [
                len(
                    {a['pair'] for a in self.report['anchors'] if a.get('receiver_index') == k}
                    - initial[k]
                )
                for k in range(1, count)
            ]
            print(
                'anchor',
                i,
                'matches',
                list(map(len, matches)),
                'independent pairs',
                groups,
                flush=True,
            )
            if min(groups) >= needed:
                self.check_calibration('after anchors')
                self.save()
                return
        raise RuntimeError('Insufficient independent RF-anchor pairs for every receiver')

    def run(self, duration_ms, period_ns, phases, compensate=True):
        count = len(self.radios)
        if len(phases) != count or any(
            isinstance(p, bool) or not isinstance(p, int) or not 0 <= p <= 34 for p in phases
        ):
            raise ValueError('One integer phase in 0..34 per receiver required')
        self.tx.stop()
        models = [None] + [
            fit_clock([a for a in self.report['anchors'] if a.get('receiver_index') == k][-12:])
            for k in range(1, count)
        ]
        c = clock_probe(self.radios[0])
        a = round((time.monotonic_ns() / 1000 + 300000 + c['offset_us']) / 1000) * 1000
        # Stagger in reference time, then transform both phase and period.
        deadlines, periods = [a], [period_ns]
        for k in range(1, count):
            phase_a = a + k * period_ns / (1000 * count)
            deadlines.append(round(phase_a + delta_at(phase_a, models[k])))
            periods.append(
                round(period_ns * (1 + models[k]['relative_drift'])) if compensate else period_ns
            )
        stop = Event()
        futures = [
            self.pool.submit(
                run_stream,
                r,
                start_us=deadlines[k],
                milliseconds=duration_ms,
                period_ns=periods[k],
                yield_phase=phases[k],
                expected_background_policy=1,
                stop=stop,
            )
            for k, r in enumerate(self.radios)
        ]
        try:
            for f in as_completed(futures):
                f.result()
            results = [f.result() for f in futures]
        except BaseException:
            stop.set()
            outcomes = []
            for k, f in enumerate(futures):
                outcome = dict(receiver_index=k, port=getattr(self.radios[k], 'port', None))
                try:
                    peer = f.result()
                    outcome.update(
                        status='completed-peer',
                        summary=peer['summary'],
                        transport_crc_valid=peer.get('transport_crc_valid'),
                        stop_requested=peer.get('stop_requested'),
                    )
                except BaseException as error:
                    outcome.update(
                        status='error', error_type=type(error).__name__, error=str(error)
                    )
                    diagnostics = getattr(error, 'stream_diagnostics', None)
                    if isinstance(diagnostics, dict):
                        outcome['private_stream_diagnostics'] = diagnostics
                outcomes.append(outcome)
            # Keep failures outside runs: no coverage analysis can count a peer
            # summary as a complete multi-device trial. Raw frame diagnostics are
            # private and must not be included in sanitized public projections.
            rejected = self.report.setdefault('rejected_runs', [])
            rejected.append(
                dict(
                    status='rejected',
                    index=len(rejected),
                    attempted_after_completed_runs=len(self.report['runs']),
                    scheduled_a_us=a,
                    duration_ms=duration_ms,
                    deadlines_us=deadlines,
                    periods_ns=periods,
                    yield_phases=phases,
                    host_failure_monotonic_ns=time.monotonic_ns(),
                    receivers=outcomes,
                    reason='At least one receiver failed; no union coverage is accepted.',
                )
            )
            self.save()
            raise
        row = dict(
            index=len(self.report['runs']),
            scheduled_a_us=a,
            scheduled_device_us=deadlines,
            duration_ms=duration_ms,
            periods_ns=periods,
            yield_phases=phases,
            receivers=results,
            clock_predictions=models,
        )
        self.report['runs'].append(row)
        try:
            row['calibration_after'] = self.check_calibration('after stream')
        finally:
            self.save()
        print(
            'stream',
            row['index'],
            'counts',
            [r['summary']['captures'] for r in results],
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
    p.add_argument('--phases', default=None)
    p.add_argument('--phase-sweep', action='store_true')
    p.add_argument('--no-drift-compensation', action='store_true')
    args = p.parse_args()
    phases = list(map(int, args.phases.split(','))) if args.phases else [0] * len(args.port)
    if not 2 <= len(args.port) <= 4 or len({str(Path(x).resolve()) for x in args.port}) != len(
        args.port
    ):
        p.error('Two to four distinct verified ports required')
    if len(phases) != len(args.port) or any(not 0 <= x <= 34 for x in phases):
        p.error('One phase in 0..34 per receiver required')
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
    source_hashes = source_provenance()  # Before opening transmitter or receivers.
    radios = [Radio(x) for x in args.port]
    with Transmitter(serial_number=args.tx_serial) as tx, ThreadPoolExecutor(len(radios)) as pool:
        campaign = Campaign(radios, tx, pool, args.output, source_hashes=source_hashes)
        report = campaign.report
        try:
            tx.stop()
            report['tx_before'] = tx.status()
            report['devices'] = [r.connect() for r in radios]
            report['calibration_before'] = campaign.check_calibration('before configuration')
            for r in radios:
                if 'DSTREAM' not in r.info['caps']:
                    raise ValueError('DSTREAM firmware required')
                r.command('TRACECLEAR')
                r.command('DETPIPECLEAR')
                r.configure(2440, 16000000, 12, 60, 10)
                r.command('ACQOPT 3')
                r.command('CLEAROPT 1')
                r.command('BGPOLICY 1')
            report['calibration_configured'] = campaign.check_calibration('after configuration')
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
                    campaign.run(
                        1000, args.period_ns, [phase] * len(radios), not args.no_drift_compensation
                    )
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
            report['status'] = 'validated'
        except BaseException as exc:
            report['status'] = 'failed'
            report['error'] = repr(exc)
            raise
        finally:
            validated = report['status'] == 'validated'
            cleanup_errors = campaign.cleanup()
            campaign.save()
            if validated and cleanup_errors:
                raise RuntimeError('Campaign cleanup unverified: ' + '; '.join(cleanup_errors))


if __name__ == '__main__':
    main()
