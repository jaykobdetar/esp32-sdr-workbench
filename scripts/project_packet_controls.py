"""Project completed private packet-control JSON into explicit sanitized numeric evidence.

No serial access, I/Q loading, or RF decoding. Usage: --input LABEL=RESULTS_JSON.
"""

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path

from .four_receiver_packets import check_calibration, saved_config, summarize


def project(label, report):
    if re.fullmatch(r'[a-zA-Z0-9-]{1,64}', label) is None:
        raise ValueError('Use a short non-identifying alphanumeric/hyphen label')
    if report.get('status') != 'passed' or report.get('cleanup_errors'):
        raise ValueError('Only completed passed controls can enter this projection')
    plan = report['capture_plan']
    config = report['expected_config']
    bits = plan['capture_format']['bits_per_component']
    rows = report['captures']
    count = len(report['devices'])
    analysis = summarize(rows, report['tx_start'], report['tx_final_run'], count, config, bits)
    if analysis != report['analysis']:
        raise ValueError('Saved analysis differs from current validated summary')
    check_calibration(report['calibration_before'], report['calibration_after'])
    if len(report['calibration_before']) != count:
        raise ValueError('Missing receiver calibration control')
    if (
        report['tx_stop'].get('running') is not False
        or report['tx_stop'].get('healthy') is not True
    ):
        raise ValueError('Source stop/health not verified')
    if saved_config(report['tx_restored']) != saved_config(report['tx_before']):
        raise ValueError('Source configuration not restored')
    boundaries = report['calibration_boundaries']
    if [b['condition'] for b in boundaries] != ['OFF', 'ON']:
        raise ValueError('Missing condition boundaries')
    conditions = []
    for boundary in boundaries:
        condition = boundary['condition']
        check_calibration(boundary['before'], boundary['after'])
        if len(boundary['before']) != count:
            raise ValueError('Incomplete boundary calibration')
        selected = [r for r in rows if r['condition'] == condition]
        per_receiver = [sum(r['receiver'] == k for r in selected) for k in range(count)]
        budget = boundary['acquisition_budget']
        if (
            budget['requested_ms'] != plan['acquisition_budget_ms']
            or budget['round_cap'] != plan['captures_per_condition']
        ):
            raise ValueError('Condition budget/cap differs from requested plan')
        if per_receiver != budget['per_receiver_captures']:
            raise ValueError('Saved capture accounting differs from observed rows')
        durations = [(r['host_end_ns'] - r['host_start_ns']) / 1e6 for r in selected]
        payloads = [r['metadata']['payload_transfer_us'] / 1000 for r in selected]
        if any(not isinstance(v, (int, float)) or not 0 < v < 60000 for v in durations + payloads):
            raise ValueError('Invalid capture timing')
        conditions.append(
            dict(
                condition=condition,
                captures=len(selected),
                per_receiver_captures=per_receiver,
                skipped_calls=sum(r['condition'] == condition for r in report['skipped_captures']),
                round_cap=budget['round_cap'],
                round_cap_reached=budget['round_cap_reached'],
                rounds_started=budget['rounds_started'],
                requested_acquisition_budget_ms=budget['requested_ms'],
                actual_host_condition_ms=(budget['end_host_ns'] - budget['start_host_ns']) / 1e6,
                median_capture_ms=statistics.median(durations),
                median_payload_transfer_ms=statistics.median(payloads),
                calls_started_after_latest_source_duration_deadline=sum(
                    r.get('host_duration_deadline_observation', {}).get(
                        'capture_call_started_after_latest_deadline', False
                    )
                    for r in selected
                ),
                calls_ended_after_latest_source_duration_deadline=sum(
                    r.get('host_duration_deadline_observation', {}).get(
                        'capture_call_ended_after_latest_deadline', False
                    )
                    for r in selected
                ),
            )
        )
    return dict(
        run=label,
        status='passed',
        capture_mode=plan['capture_mode'],
        bits_per_component=bits,
        complex_samples=16380,
        sample_rate_hz=16000000,
        packed_payload_bytes=plan['capture_format']['packed_payload_bytes'],
        source_duration_ms=plan['source_duration_ms'],
        power_dbm=config['power_dbm'],
        stagger_ms=plan['stagger_ms'],
        conditions=conditions,
        packet_analysis=analysis,
        calibration_unchanged=True,
        source_stopped=True,
        source_config_restored=True,
    )


def aggregate(runs):
    groups = []

    def group_key(r):
        return (
            r['capture_mode'],
            r['bits_per_component'],
            r['power_dbm'],
            r['stagger_ms'],
            r['source_duration_ms'],
            r['conditions'][1]['requested_acquisition_budget_ms'],
            tuple(c['round_cap'] for c in r['conditions']),
        )

    keys = sorted(
        {group_key(r) for r in runs},
        key=lambda key: (*key[:5], -1 if key[5] is None else key[5], key[6]),
    )
    for mode, bits, power, stagger, source_ms, budget_ms, caps in keys:
        selected = [
            r
            for r in runs
            if group_key(r) == (mode, bits, power, stagger, source_ms, budget_ms, caps)
        ]
        unique = sum(r['packet_analysis']['unique_packets'] for r in selected)
        completed = sum(r['packet_analysis']['completed_transmissions'] for r in selected)
        groups.append(
            dict(
                capture_mode=mode,
                bits_per_component=bits,
                power_dbm=power,
                stagger_ms=stagger,
                source_duration_ms=source_ms,
                acquisition_budget_ms=budget_ms,
                round_caps_off_on=list(caps),
                runs=len(selected),
                on_captures=sum(r['conditions'][1]['captures'] for r in selected),
                off_captures=sum(r['conditions'][0]['captures'] for r in selected),
                sum_run_unique_packets=unique,
                sum_completed_transmissions=completed,
                pooled_descriptive_recovery_percent=100 * unique / completed,
                median_run_on_capture_ms=statistics.median(
                    r['conditions'][1]['median_capture_ms'] for r in selected
                ),
                cap_reached_any=any(
                    c['round_cap_reached'] for r in selected for c in r['conditions']
                ),
            )
        )
    return groups


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', action='append', required=True, help='LABEL=private results.json')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    runs, provenance = [], []
    for spec in args.input:
        label, path = spec.split('=', 1)
        data = Path(path).read_bytes()
        runs.append(project(label, json.loads(data)))
        provenance.append(dict(run=label, input_json_sha256=hashlib.sha256(data).hexdigest()))
    if len({r['run'] for r in runs}) != len(runs):
        raise ValueError('Duplicate run label')
    result = dict(
        schema=1,
        scope='Completed JSON revalidation only; no I/Q re-decode.',
        runs=runs,
        groups=aggregate(runs),
        input_provenance=provenance,
        limitations='Small balanced ABBA controls, not statistical superiority or '
        'continuous coverage. Fixed-count tests measure service-time savings; '
        'equal-budget counts measure retained-snapshot throughput. Packet percentages '
        'retain the entire completed-source denominator and are not window recall. '
        'No device identifiers, RF samples, calibration hashes, or local paths included.',
    )
    with args.output.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps(result['groups'], indent=2))


if __name__ == '__main__':
    main()
