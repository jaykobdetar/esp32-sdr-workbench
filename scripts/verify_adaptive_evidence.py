#!/usr/bin/env python3
"""Check published summary arithmetic, not withheld RF samples or acquisition truth."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'docs/evidence/adaptive-evaluation/evaluation-results.json'
IMAGE_HASHES = {
    'v2': '8fff02862f5036dc2775fe8e58b1aa3db29181180ae06524c5555aa86d22f1ad',
    'v3': 'c5360d2b4e2ff5711d9b9ef43040b1290e5c31ec4de631a1f372fa5ecd0ce860',
    'health': '2f5be585ae66126496080cb1fcd6e59424dbaa959f5078286338bdbebab8dffe',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, message):
    require(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9), message)


def wilson(successes, n):
    z = 1.959963984540054
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0, center - radius), min(1, center + radius)]


def signflip(differences):
    observed = abs(sum(differences))
    extreme = sum(
        abs(sum(sign * delta for sign, delta in zip(signs, differences, strict=True)))
        >= observed - 1e-9
        for signs in itertools.product((-1, 1), repeat=len(differences))
    )
    return extreme / 2 ** len(differences)


def verify(data):
    totals = dict(
        pipeline_runs=0,
        direct_source_control_captures=0,
        pipeline_captures=0,
        retained_files=0,
        raw_files=0,
        failed_runs=0,
        pipeline_no_retained_event_runs=0,
    )
    endpoints = {}
    for name, stage in data['stages'].items():
        records = stage['records']
        pipeline = stage['stage_type'] == 'pipeline'
        require(len(records) == stage['run_count'], f'{name}: run count')
        require(stage['status'] == 'passed', f'{name}: stage status')
        require(stage['run_statuses'] == {'passed': len(records)}, f'{name}: statuses')
        require(not stage['duplicate_generation_runs'], f'{name}: duplicate generations')
        require(not stage['heap_clear_mismatches'], f'{name}: heap-clear mismatch')
        key = 'health' if name.startswith('health-') else ('v2' if name.startswith('v2-') else 'v3')
        if stage['artifact_sha256'] is not None:
            require(stage['artifact_sha256'] == IMAGE_HASHES[key], f'{name}: image identity')
        buffers = [buffer for row in records for buffer in row['buffers']]
        require(
            len(buffers) == stage['crop_count' if pipeline else 'direct_raw_count'],
            f'{name}: buffer count',
        )
        require(
            stage['transport_crc_counts'] == {'True': len(buffers), 'False': 0, 'None': 0},
            f'{name}: reported CRC accounting',
        )
        all_buffers = buffers + stage['additional_raw_records']
        require(all(b['transport_crc_ok'] is True for b in all_buffers), f'{name}: saved CRC')
        require(
            stage['raw_count']
            == len(stage['additional_raw_records']) + (0 if pipeline else len(buffers)),
            f'{name}: raw count',
        )
        totals['raw_files'] += stage['raw_count']
        totals['failed_runs'] += stage['failed_run_count']
        if pipeline:
            totals['pipeline_runs'] += len(records)
            totals['retained_files'] += len(buffers)
            totals['pipeline_captures'] += sum(r['summary']['captures'] for r in records)
            empty = sum(not r['buffers'] for r in records)
            require(empty == stage['unretained_run_count'], f'{name}: no-event count')
            totals['pipeline_no_retained_event_runs'] += empty
            for field, expected in stage['totals'].items():
                require(sum(r['summary'][field] for r in records) == expected, f'{name}: {field}')
            for row in records:
                summary = row['summary']
                require(summary['captures'] == summary['processed_captures'], f'{name}: processing')
                require(
                    not any(summary[k] for k in ('status', 'errors', 'pack_failed')),
                    f'{name}: errors',
                )
                close(
                    summary['nominal_local_rf_duty_percent'],
                    summary['total_samples']
                    / summary['sample_rate_hz']
                    / summary['wall_elapsed_us']
                    * 1e8,
                    f'{name}: local duty',
                )
        else:
            totals['direct_source_control_captures'] += len(records)
        for mode, comparison in stage.get('gain_comparison', {}).items():
            paired = {}
            for on, label in ((False, 'off'), (True, 'on')):
                rows = [r for r in records if r['mode'] == mode and r['tx_on'] is on]
                rates = [
                    r['summary']['detections'] / r['summary']['wall_elapsed_us'] * 1e6 for r in rows
                ]
                expected = comparison[label]
                close(
                    statistics.mean(rates),
                    expected['candidate_rate']['mean'],
                    f'{name}/{mode}: rate',
                )
                successes = sum(r['any_complete_known_packet_verified_rf_crc'] for r in rows)
                require(
                    successes == expected['runs_with_any_complete_known_packet_verified_rf_crc'],
                    f'{name}/{mode}: packet count',
                )
                for actual, saved in zip(
                    wilson(successes, len(rows)),
                    expected['complete_packet_run_wilson95'],
                    strict=True,
                ):
                    close(actual, saved, f'{name}/{mode}: Wilson interval')
                paired[on] = {r['pair']: rate for r, rate in zip(rows, rates, strict=True)}
                if 'strong' in name:
                    endpoints[f'{name}/{mode}/{label}'] = [successes, len(rows)]
            require(paired[False].keys() == paired[True].keys(), f'{name}/{mode}: pair IDs')
            differences = [
                paired[True][pair] - paired[False][pair] for pair in sorted(paired[True])
            ]
            saved = comparison['paired_rate_on_minus_off']
            close(statistics.mean(differences), saved['mean'], f'{name}/{mode}: paired mean')
            close(signflip(differences), saved['signflip_two_sided_p'], f'{name}/{mode}: signflip')
    require(totals == data['totals'], 'Global totals disagree')
    health = [s['health'] for s in data['stages'].values() if 'health' in s]
    require(all(h['all_run_valid'] and h['consecutive_run_ids'] for h in health), 'Health validity')
    for h in health:
        require(
            h['monitor_start_error']['max'] == h['monitor_stop_error']['max'] == 0, 'Monitor error'
        )
    return dict(
        totals=totals,
        transport_crc_valid_files=totals['retained_files'] + totals['raw_files'],
        strong_source_endpoints=endpoints,
        reported_minimum_heap_bytes=min(h['run_min_bytes']['min'] for h in health),
        reported_minimum_stack_bytes=min(h['stack_after_bytes']['min'] for h in health),
        soak_pipeline_seconds=data['stages']['health-fixed-soak']['totals']['wall_elapsed_us']
        / 1e6,
        scope='Public summary consistency only. No independent RF decoding, CRC recomputation from samples, calibration audit or new hardware measurement.',
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', nargs='?', type=Path, default=DEFAULT)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.evidence.read_text())), indent=2))


if __name__ == '__main__':
    main()
