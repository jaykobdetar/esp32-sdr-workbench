#!/usr/bin/env python3
"""Offline matched-gain summary with exact sign flips and signed-ADC endpoints.

Reads private result/retained-IQ files; writes a scrubbed summary, never opens hardware.
"""

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from statistics import mean

from .count_sigmf_endpoints import count_endpoints
from .nrf_gain_compare import summarize


def exact_sign_flip(values):
    """Two-sided |mean| sign-flip enumeration; exchangeability is an assumption."""
    if not 1 <= len(values) <= 16 or not all(math.isfinite(x) for x in values):
        raise ValueError('Require 1..16 finite block contrasts')
    observed = abs(sum(values))
    extreme = sum(
        abs(sum(s * v for s, v in zip(signs, values, strict=True))) >= observed - 1e-9
        for signs in itertools.product((-1, 1), repeat=len(values))
    )
    return {
        'block_contrasts': values,
        'mean': mean(values),
        'two_sided_p': extreme / 2 ** len(values),
        'extreme_assignments': extreme,
        'assignments': 2 ** len(values),
        'null_assumption': 'Independent exchangeable signs of block differences; temporal bench order does not guarantee this.',
    }


def analyze(report, *, read_bytes=Path.read_bytes):
    if report['status'] != 'passed' or any(r['status'] != 'passed' for r in report['runs']):
        raise ValueError('Complete passed campaign required')
    rows = report['runs']
    keys = [(r['pair'], r['mode'], r['tx_on']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate block/mode/state')
    modes = sorted({r['mode'] for r in rows})
    blocks = sorted({r['pair'] for r in rows})
    if set(keys) != set(itertools.product(blocks, modes, (False, True))):
        raise ValueError('Incomplete matched blocks')
    result = {
        'schema': 1,
        'status': report['status'],
        'settings': report['settings'],
        'geometry': report['geometry'],
        'geometry_measured': report['geometry_measured'],
        'cautions': report['cautions']
        + [
            f'This trial uses {report["settings"]["power_dbm"]} dBm; the earlier ABAB evidence used 0 dBm.',
            'Endpoint fractions describe selected retained buffers, not all acquired windows.',
            'Zero ADC endpoints does not establish analog linearity or packet reception.',
            'Exact sign-flip p values are descriptive under exchangeability, not proof of causality.',
        ],
        'receiver_version': report['device']['version'],
        'receiver_local_reference_sha256': report['local_receiver_artifact_sha256'],
        'receiver_artifact_note': report['artifact_note'],
        'transmitter_version': report['tx_initial']['version'],
        'transmitter_stopped_at_end': not report['tx_final']['running'],
        'initial_gain_restored': report['gain_initial'] == report['gain_restored'],
        'comparison': summarize(rows),
        'runs': [],
        'agc_minus_manual_contrasts': {},
    }
    by_key = {}
    for row in rows:
        summary = row['summary']
        expected = summary['detections'] * 1e6 / summary['wall_elapsed_us']
        if not math.isclose(expected, row['candidate_rate_per_local_second'], rel_tol=1e-12):
            raise ValueError('Candidate rate does not match run counts')
        by_key[(row['pair'], row['mode'], row['tx_on'])] = expected
        public = {
            k: row[k]
            for k in (
                'index',
                'pair',
                'mode',
                'gain',
                'tx_on',
                'status',
                'gain_before',
                'gain_after',
                'tx_completed_delta',
                'retained_transport_crc_valid',
                'candidate_rate_per_local_second',
                'candidate_fraction_postwarmup',
                'local_rf_duty_percent',
            )
        }
        public['receiver_summary'] = {
            k: summary[k]
            for k in (
                'status',
                'captures',
                'warmup_captures',
                'detections',
                'total_samples',
                'wall_elapsed_us',
                'errors',
                'retained_samples',
                'background_adc2',
                'best_ratio_milli',
            )
            if k in summary
        }
        if row.get('sigmf'):
            data = read_bytes(Path(row['sigmf']).with_suffix('.sigmf-data'))
            public['retained_iq_sha256'] = hashlib.sha256(data).hexdigest()
            public['retained_iq_bytes'] = len(data)
            public['retained_endpoints'] = count_endpoints(data, 10)
        result['runs'].append(public)
    for mode in modes:
        if mode == 'hardware-agc':
            continue
        contrasts = [
            (by_key[(p, 'hardware-agc', True)] - by_key[(p, 'hardware-agc', False)])
            - (by_key[(p, mode, True)] - by_key[(p, mode, False)])
            for p in blocks
        ]
        result['agc_minus_manual_contrasts'][mode] = {
            'block_ids': blocks,
            **exact_sign_flip(contrasts),
        }
    for mode in modes:
        for on in (False, True):
            group = [r for r in result['runs'] if r['mode'] == mode and r['tx_on'] is on]
            retained = [r['retained_endpoints'] for r in group if 'retained_endpoints' in r]
            target = result['comparison'][mode]['states']['on' if on else 'off']
            target['detections_total'] = sum(r['receiver_summary']['detections'] for r in group)
            target['retained_buffers'] = len(retained)
            target['retained_buffers_without_adc_endpoints'] = sum(
                x['either_component_endpoint_samples'] == 0 for x in retained
            )
            target['mean_retained_endpoint_percent'] = (
                mean(x['either_component_endpoint_percent'] for x in retained) if retained else None
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(json.loads(args.results.read_text()))
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
