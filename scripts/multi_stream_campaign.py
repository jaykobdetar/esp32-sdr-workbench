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
from sdr_research.gc_policy import deferred_cyclic_gc
from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json
from sdr_research.stream_diagnostics import diagnose_failed_stream

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
from .trial_clock_brackets import (
    MAX_BOUNDARY_AGE_US,
    MIN_GROUPS,
    anchor_seal,
    batch_spec,
    select_trial_anchors,
    trial_spec,
)

_SOURCE_FILES = {
    'scripts/trial_clock_brackets.py': inspect.getsourcefile(select_trial_anchors),
    'sdr_research/gc_policy.py': inspect.getsourcefile(inspect.unwrap(deferred_cyclic_gc)),
    'scripts/multi_stream_campaign.py': __file__,
    'scripts/dual_stream_campaign.py': inspect.getsourcefile(DualCampaign),
    'sdr_research/detector_stream.py': inspect.getsourcefile(run_stream),
    'sdr_research/protocol.py': inspect.getsourcefile(Radio),
    'scripts/analyze_nrf_iq.py': inspect.getsourcefile(decode),
    'sdr_research/calibration.py': inspect.getsourcefile(record_calibration),
    'sdr_research/stream_diagnostics.py': inspect.getsourcefile(diagnose_failed_stream),
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
        bracket_diagnostics = None
        if 'clock_brackets' in row:
            anchors, bracket_diagnostics = select_trial_anchors(row, anchors)
        models = [None]
        pair_diagnostics = []
        for k in range(1, count):
            pair_row = dict(row, receivers=[row['receivers'][0], row['receivers'][k]])
            selected = [a for a in anchors if a.get('receiver_index') == k]
            result = analyze_pair(
                pair_row, selected, use_all_bracketing=bracket_diagnostics is not None
            )
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
            clock_brackets=bracket_diagnostics,
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
    def __init__(self, radios, tx, pool, output, *, source_hashes=None, defer_cyclic_gc=False):
        if not 2 <= len(radios) <= 4 or len({id(r) for r in radios}) != len(radios):
            raise ValueError('Two to four distinct receiver objects required')
        hashes = source_provenance() if source_hashes is None else dict(source_hashes)
        super().__init__(radios, tx, pool, output)
        self.report['source_sha256'] = hashes
        self.defer_cyclic_gc = defer_cyclic_gc
        self.report['defer_cyclic_gc'] = defer_cyclic_gc

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

    def _save_anchor_progress(self):
        batch = self._anchor_batch
        pair_ids = batch['pair_ids']
        atomic_write_json(
            self.out / f'anchor-progress-{batch["batch_id"]}.json',
            dict(
                schema=1,
                batch=dict(batch),
                source_sha256=self.report['source_sha256'],
                anchors=[
                    a for a in self.report['anchors'] if a.get('batch_id') == batch['batch_id']
                ],
                anchor_pairs=[p for p in self.report['anchor_pairs'] if p['index'] in pair_ids],
                note='Durable trial-local anchor progress; full results checkpoint remains separate. No prior stream records serialized here.',
            ),
        )
        # Persist the rename as well as the fsynced file contents on this Linux host.
        directory = os.open(self.out, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def bracket_batch(self, trial_index, role, *, reference_boundary_us=None):
        batch = dict(batch_spec(trial_index, role), status='collecting', pair_ids=[])
        if reference_boundary_us is not None:
            batch['reference_boundary_us'] = reference_boundary_us
        batches = self.report.setdefault('anchor_batches', [])
        if any(b['batch_id'] == batch['batch_id'] for b in batches):
            raise ValueError('Calibration batch ID cannot be reused')
        batches.append(batch)
        self._anchor_batch = batch
        try:
            self._save_anchor_progress()
            self.anchors(needed=MIN_GROUPS, attempts=60)
            batch.update(
                anchor_seal(
                    [a for a in self.report['anchors'] if a.get('batch_id') == batch['batch_id']]
                )
            )
            batch['status'] = 'complete'
            self._save_anchor_progress()
        except BaseException:
            batch['status'] = 'failed'
            try:
                self._save_anchor_progress()
            except BaseException as save_error:
                batch['progress_save_error_type'] = type(save_error).__name__
            raise
        finally:
            self._anchor_batch = None
        return dict(batch, pair_ids=list(batch['pair_ids']))

    def trial_clock_run(self, duration_ms, period_ns, phases, compensate=True):
        index = len(self.report['runs'])
        before = self.bracket_batch(index, 'before')
        # No full-report serialization between fresh pre-batch and scheduling.
        self._pending_brackets = trial_spec(index)
        self._pending_before_batch = before
        try:
            self.run(duration_ms, period_ns, phases, compensate)
        finally:
            self._pending_brackets = None
        row = self.report['runs'][-1]
        after = self.bracket_batch(
            index, 'after', reference_boundary_us=row['scheduled_a_us'] + row['duration_ms'] * 1000
        )
        row['clock_bracket_batches'] = [before, after]
        row['analysis'] = analyze_run(row, self.report['anchors'])
        row['analysis_frozen'] = True
        self.save()
        if row['analysis']['status'] != 'verified-telemetry':
            raise RuntimeError('Unverified trial-local coverage: ' + row['analysis']['reason'])
        return row

    def _finish_anchor_readers(self, futures):
        """STOP source and positively join every submitted reader, despite signals."""
        errors = []
        try:
            self.tx.stop()
        except BaseException as exc:
            errors.append(dict(stage='transmitter-stop', error_type=type(exc).__name__))
        for k, future in enumerate(futures):
            while not future.done():
                try:
                    future.result()
                except BaseException as exc:
                    if not future.done():
                        errors.append(
                            dict(
                                stage='reader-join-interrupted',
                                receiver_index=k,
                                error_type=type(exc).__name__,
                            )
                        )
        return errors

    def _capture_anchor_pair(self, index, deadlines):
        futures = []
        try:
            # START and partial submission both belong inside cleanup scope.
            self.tx.start(count=4000, duration_ms=2000)
            for k, radio in enumerate(self.radios):
                futures.append(
                    self.pool.submit(
                        self.raw, radio, deadlines[k], self.out / f'anchor-{index:04d}-rx{k}'
                    )
                )
            values = [future.result() for future in futures]
        except BaseException:
            errors = self._finish_anchor_readers(futures)
            self.report.setdefault('anchor_failures', []).append(
                dict(
                    pair=index,
                    submitted_readers=len(futures),
                    readers_joined=True,
                    cleanup_observations=errors,
                )
            )
            raise  # Preserve the primary START/submission/read/wait exception.
        errors = self._finish_anchor_readers(futures)
        if errors:
            self.report.setdefault('anchor_failures', []).append(
                dict(
                    pair=index,
                    submitted_readers=len(futures),
                    readers_joined=True,
                    cleanup_observations=errors,
                )
            )
            raise RuntimeError('Anchor source STOP or reader cleanup was interrupted/unverified')
        return values

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
            batch = getattr(self, '_anchor_batch', None)
            if batch is not None:
                existing = [
                    v['a_us']
                    for v in self.report['anchors']
                    if v.get('batch_id') == batch['batch_id']
                ]
                boundary = batch.get('reference_boundary_us')
                if boundary is not None and a - boundary > MAX_BOUNDARY_AGE_US:
                    raise ValueError('Post-batch cannot obtain fresh anchors within 60 seconds')
                if (
                    batch['role'] == 'before'
                    and existing
                    and a - min(existing) > MAX_BOUNDARY_AGE_US
                ):
                    raise ValueError(
                        'Pre-batch already exceeds 60 seconds; no anchor exclusions allowed'
                    )
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
            values = self._capture_anchor_pair(i, deadlines)
            decoded = [decode(v[1], 16000000, 2, 16) for v in values]
            matches = [
                {
                    h['sequence']: h
                    for h in d['full_payload_matches']
                    if h['crc_verified'] and h['address_verified']
                }
                for d in decoded
            ]
            batch = getattr(self, '_anchor_batch', None)
            if batch is not None:
                batch['pair_ids'].append(i)
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
                        dict(
                            pair=i,
                            sequence=seq,
                            a_us=ts[0],
                            b_us=ts[1],
                            receiver_index=k,
                            **(
                                {key: batch[key] for key in ('batch_id', 'trial_index', 'role')}
                                if batch is not None
                                else {}
                            ),
                        )
                    )
            self._save_anchor_progress() if batch is not None else self.save()
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
                self._save_anchor_progress() if batch is not None else self.save()
                return
        raise RuntimeError('Insufficient independent RF-anchor pairs for every receiver')

    def run(self, duration_ms, period_ns, phases, compensate=True):
        if not getattr(self, 'defer_cyclic_gc', False):
            return self._run_stream(duration_ms, period_ns, phases, compensate)
        policies = self.report.setdefault('cyclic_gc_policy', [])
        if not 1000 <= duration_ms <= 120000 or len(policies) >= 3:
            raise ValueError('GC deferral limited to three runs of 1..120 seconds')
        observation = dict(attempt=len(policies), status='started')
        policies.append(observation)
        try:
            with deferred_cyclic_gc(observation):
                result = self._run_stream(duration_ms, period_ns, phases, compensate)
            observation['status'] = 'returned'
            return result
        except BaseException as error:
            observation.update(status='raised', error_type=type(error).__name__)
            raise
        finally:
            try:
                self.save()
            except BaseException as error:
                observation['persistence_error_type'] = type(error).__name__

    def _run_stream(self, duration_ms, period_ns, phases, compensate=True):
        count = len(self.radios)
        if len(phases) != count or any(
            isinstance(p, bool) or not isinstance(p, int) or not 0 <= p <= 34 for p in phases
        ):
            raise ValueError('One integer phase in 0..34 per receiver required')
        self.tx.stop()
        pending = getattr(self, '_pending_brackets', None)
        prediction_anchors = self.report['anchors']
        if pending is not None:
            prediction_anchors = [
                x for x in prediction_anchors if x.get('batch_id') == pending['before_batch_id']
            ]
        models = [None] + [
            fit_clock(
                [x for x in prediction_anchors if x.get('receiver_index') == k]
                if pending is not None
                else [x for x in prediction_anchors if x.get('receiver_index') == k][-12:]
            )
            for k in range(1, count)
        ]
        c = clock_probe(self.radios[0])
        a = round((time.monotonic_ns() / 1000 + 300000 + c['offset_us']) / 1000) * 1000
        if pending is not None:
            ages = [a - x['a_us'] for x in prediction_anchors]
            if not ages or min(ages) <= 0 or max(ages) > MAX_BOUNDARY_AGE_US:
                raise ValueError('Fresh pre-batch exceeds the declared 60-second boundary age')
        # Stagger in reference time, then transform both phase and period.
        deadlines, periods = [a], [period_ns]
        for k in range(1, count):
            phase_a = a + k * period_ns / (1000 * count)
            deadlines.append(round(phase_a + delta_at(phase_a, models[k])))
            periods.append(
                round(period_ns * (1 + models[k]['relative_drift'])) if compensate else period_ns
            )
        stop = Event()
        futures = []
        try:
            # Submission can fail after earlier workers have started. Keep those
            # futures inside the same cancellation/join path before GC restoration.
            for k, r in enumerate(self.radios):
                futures.append(
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
                )
            for f in as_completed(futures):
                f.result()
            results = [f.result() for f in futures]
        except BaseException:
            cancellation = dict(event_set_started_host_monotonic_ns=time.monotonic_ns())
            stop.set()
            cancellation['event_set_returned_host_monotonic_ns'] = time.monotonic_ns()
            outcomes = []
            join_interruptions = []
            for k, f in enumerate(futures):
                outcome = dict(receiver_index=k, port=getattr(self.radios[k], 'port', None))
                # A signal can interrupt Future.result while the worker is
                # still running. Never interpret that as a completed worker.
                while not f.done():
                    try:
                        f.result()
                    except BaseException as join_error:
                        if not f.done():
                            join_interruptions.append(
                                dict(
                                    receiver_index=k,
                                    error_type=type(join_error).__name__,
                                    host_monotonic_ns=time.monotonic_ns(),
                                )
                            )
                # Only inspect its outcome after positive completion. This also
                # prevents diagnostic I/O racing the original serial reader.
                try:
                    peer = f.result()
                    outcome.update(
                        status='completed-peer',
                        summary=peer['summary'],
                        transport_crc_valid=peer.get('transport_crc_valid'),
                        stop_requested=peer.get('stop_requested'),
                        stop_command_timing=peer.get('stop_command_timing', []),
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
                    cancellation_timing=cancellation,
                    join_interruptions=join_interruptions,
                    receivers=outcomes,
                    reason='At least one receiver failed; no union coverage is accepted.',
                )
            )
            try:
                self.save()  # Preserve primary evidence before best-effort diagnostics.
                for k, outcome in enumerate(outcomes):
                    if outcome['status'] != 'error':
                        continue
                    previous = outcome.get('private_stream_diagnostics', {}).get(
                        'last_valid_record'
                    )
                    states = self.report.get('calibration_by_receiver', [])
                    observations = (
                        states[k].get('calibration_observations', []) if k < len(states) else []
                    )
                    calibration = next(
                        (v for v in reversed(observations) if v.get('status') == 'observed'), None
                    )
                    try:
                        outcome['same_descriptor_diagnostics'] = diagnose_failed_stream(
                            self.radios[k], previous_record=previous, calibration_before=calibration
                        )
                    except BaseException as diagnostic_error:
                        outcome['same_descriptor_diagnostics'] = dict(
                            status='diagnostic-failed', error_type=type(diagnostic_error).__name__
                        )
                self.save()
            except BaseException as save_error:
                rejected[-1]['diagnostic_persistence_error_type'] = type(save_error).__name__
            raise  # Never replace the primary stream failure with cleanup failure.
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
        if pending is not None:
            row['clock_brackets'] = dict(pending)
            row['clock_bracket_batches'] = [self._pending_before_batch]
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
    p.add_argument('--defer-cyclic-gc', action='store_true')
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--trials', type=int, default=3)
    p.add_argument('--period-ns', type=int, default=1875000)
    p.add_argument('--phases', default=None)
    p.add_argument('--phase-sweep', action='store_true')
    p.add_argument('--trial-clock-brackets', action='store_true')
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
    if args.trial_clock_brackets and args.phase_sweep:
        p.error('Trial-local clock brackets do not support phase sweep')
    if args.defer_cyclic_gc and (args.seconds > 120 or args.trials > 3 or args.phase_sweep):
        p.error('GC deferral requires <=120 seconds, <=3 trials, and no phase sweep')
    if not args.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    defer_cyclic_gc=args.defer_cyclic_gc,
                    seconds=args.seconds,
                    trials=args.trials,
                    phase_sweep=args.phase_sweep,
                    trial_clock_brackets=trial_spec(0) if args.trial_clock_brackets else None,
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
        campaign = Campaign(
            radios,
            tx,
            pool,
            args.output,
            source_hashes=source_hashes,
            defer_cyclic_gc=args.defer_cyclic_gc,
        )
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
            report['trial_clock_brackets_enabled'] = args.trial_clock_brackets
            if not args.trial_clock_brackets:
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
                if args.trial_clock_brackets:
                    row = campaign.trial_clock_run(
                        round(args.seconds * 1000),
                        args.period_ns,
                        phases,
                        not args.no_drift_compensation,
                    )
                else:
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
