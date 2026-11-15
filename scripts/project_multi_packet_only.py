"""Sanitized completed multi-packet controls; no hardware or RF decoding."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from sdr_research.packet_only import validate_lines
from sdr_research.protocol import ProtocolError

from .four_receiver_packets import check_calibration, saved_config
from .multi_packet_only_campaign import plan_check, summarize
from .packet_only_campaign import complete_end_before_source_deadline


def condition_key(plan):
    # Include full source config, not merely power, so unequal exposures cannot pool.
    return json.dumps(
        {
            k: plan[k]
            for k in (
                'receivers',
                'count',
                'period_us',
                'cap',
                'stagger_ms',
                'source_duration_ms',
                'off_only',
                'expected_config',
            )
        },
        sort_keys=True,
        separators=(',', ':'),
    )


def project(label, path):
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', label):
        raise ValueError('Non-identifying label required')
    raw = path.read_bytes()
    report = json.loads(raw)
    status = report['status']
    if status not in ('passed', 'passed-source-off-control', 'failed'):
        raise ValueError('Only completed controls can be projected')
    plan = report['plan']
    plan_check(
        plan['receivers'],
        plan['count'],
        plan['period_us'],
        plan['cap'],
        plan['source_duration_ms'],
        plan['stagger_ms'],
    )
    result = dict(
        label=label,
        status=status,
        receipt_sha256=hashlib.sha256(raw).hexdigest(),
        condition_key=condition_key(plan),
        plan={
            k: plan[k]
            for k in (
                'receivers',
                'count',
                'period_us',
                'cap',
                'stagger_ms',
                'source_duration_ms',
                'off_only',
            )
        },
        power_dbm=plan['expected_config']['power_dbm'],
        conditions=[],
    )
    rows = []
    for row in report['conditions']:
        index = row['receiver']
        if (
            type(index) is not int
            or not 0 <= index < plan['receivers']
            or row['condition'] not in ('OFF', 'ON')
        ):
            raise ValueError('Invalid receiver/condition')
        projection = dict(receiver=index, condition=row['condition'], status=row['status'])
        wire = path.parent / f'{row["condition"].lower()}-{index}.wire.txt'
        try:
            data = wire.read_bytes()
            projection['wire_sha256'] = hashlib.sha256(data).hexdigest()
            stream = validate_lines(
                data.decode('ascii').splitlines(), plan['count'], plan['period_us'], plan['cap']
            )
            if stream != row['stream']:
                raise ValueError('Retained wire differs from receipt')
            check_calibration([row['calibration_before']], [row['calibration_after']])
            if row['host_only_planned_delay_ms'] != index * plan['stagger_ms']:
                raise ValueError('Unexpected host delay')
            end = stream['end']
            projection.update(
                wire_verified=True,
                completed=end['completed'],
                skipped=end['skipped'],
                observations=end['packets'],
                output_drops=end['output_drops'],
                busy=end['busy'],
                incomplete=end['incomplete'],
                decode_mean_us=end['decode_total_us'] / end['decoded'],
                decode_max_us=end['decode_max_us'],
                host_collect_ms=(row['host_collect_end_ns'] - row['host_collect_start_ns']) / 1e6,
                session_us=end['session_us'],
            )
            if row['condition'] == 'ON':
                valid = complete_end_before_source_deadline(
                    report['source_start_host_before_ns'],
                    row['host_collect_end_ns'],
                    plan['source_duration_ms'],
                )
                projection['complete_end_before_source_deadline'] = valid
                if not valid:
                    raise ValueError('Late END')
            rows.append(dict(row, stream=stream))
        except (ValueError, KeyError, OSError, UnicodeError, ProtocolError) as exc:
            if status != 'failed':
                raise
            projection.update(wire_verified=False, validation_failure_type=type(exc).__name__)
        result['conditions'].append(projection)
    if report.get('source_final'):
        result['source_counters'] = {
            k: report['source_final'][k]
            for k in ('attempted', 'completed', 'scheduled', 'missed_slots')
        }
    if status == 'failed':
        if 'analysis' in report:
            raise ValueError('Failed report carries accepted recall')
        result['exclusion'] = 'Failed whole campaign; no accepted union recall or sibling salvage.'
        return result
    if len(report['devices']) != plan['receivers'] or report.get('cleanup_errors'):
        raise ValueError('Incomplete devices or cleanup')
    if report['source_stop']['running'] is not False or saved_config(
        report['source_before']
    ) != saved_config(report['source_restored']):
        raise ValueError('Unverified source cleanup')
    check_calibration(report['calibration_before'], report['calibration_after'])
    if len(report['calibration_before']) != plan['receivers']:
        raise ValueError('Missing calibration')
    if status == 'passed':
        if plan['off_only']:
            raise ValueError('OFF-only plan cannot carry recall')
        analysis = summarize(
            rows,
            report['source_start'],
            report['source_final'],
            plan['expected_config'],
            plan['receivers'],
        )
        if analysis != report['analysis']:
            raise ValueError('Cached analysis mismatch')
        result['analysis'] = analysis
    else:
        if (
            not plan['off_only']
            or len(rows) != plan['receivers']
            or sorted(r['receiver'] for r in rows) != list(range(plan['receivers']))
        ):
            raise ValueError('Incomplete OFF qualification')
        if any(
            r['condition'] != 'OFF' or r['status'] != 'verified' or r['stream']['packets']
            for r in rows
        ):
            raise ValueError('Invalid OFF qualification')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [
        project(label, Path(path)) for label, path in (value.split('=', 1) for value in args.input)
    ]
    groups = {}
    for row in rows:
        groups.setdefault(row['condition_key'], []).append(row['label'])
    args.output.write_text(json.dumps(dict(runs=rows, groups=groups), indent=2) + '\n')


if __name__ == '__main__':
    main()
