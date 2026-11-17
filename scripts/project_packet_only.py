"""Read-only, allowlisted numeric projection of finished packet-only controls."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from sdr_research.packet_only import validate_lines

from .four_receiver_packets import check_calibration, saved_config
from .packet_only_campaign import complete_end_before_source_deadline, packet_recovery


def project(label, path):
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', label):
        raise ValueError('Non-identifying label required')
    raw = path.read_bytes()
    report = json.loads(raw)
    status = report['status']
    if status not in ('passed', 'passed-source-off-control', 'failed'):
        raise ValueError('Unfinished control')
    plan = report['plan']
    result = dict(
        label=label,
        status=status,
        receipt_sha256=hashlib.sha256(raw).hexdigest(),
        count=plan['count'],
        period_us=plan['period_us'],
        cap=plan['cap'],
        source_duration_ms=plan['source_duration_ms'],
        power_dbm=plan['expected_config']['power_dbm'],
        conditions=[],
    )
    verified = []
    for row in report['conditions']:
        wire = path.parent / (row['condition'].lower() + '.wire.txt')
        stream = validate_lines(
            wire.read_text().splitlines(), plan['count'], plan['period_us'], plan['cap']
        )
        if stream != row['stream']:
            raise ValueError('Retained wire differs from receipt')
        check_calibration(row['calibration_before'], row['calibration_after'])
        end = stream['end']
        result['conditions'].append(
            dict(
                condition=row['condition'],
                completed=end['completed'],
                skipped=end['skipped'],
                observations=end['packets'],
                output_drops=end['output_drops'],
                busy=end['busy'],
                incomplete=end['incomplete'],
                decode_mean_us=end['decode_total_us'] / end['decoded'],
                decode_max_us=end['decode_max_us'],
                session_us=end['session_us'],
                host_collect_ms=(row['host_collect_end_ns'] - row['host_collect_start_ns']) / 1e6,
                wire_sha256=hashlib.sha256(wire.read_bytes()).hexdigest(),
            )
        )
        verified.append(dict(condition=row['condition'], stream=stream))
    if report.get('source_final'):
        result['source_counters'] = {
            k: report['source_final'][k]
            for k in ('attempted', 'completed', 'scheduled', 'missed_slots')
        }
    if status != 'failed':
        if report.get('cleanup_errors') or report['source_stop']['running'] is not False:
            raise ValueError('Unverified cleanup')
        if saved_config(report['source_before']) != saved_config(report['source_restored']):
            raise ValueError('Unverified source restore')
        check_calibration(report['calibration_before'], report['calibration_after'])
        if status == 'passed':
            on = report['conditions'][1]
            if not complete_end_before_source_deadline(
                report['source_start_host_before_ns'],
                on['host_collect_end_ns'],
                plan['source_duration_ms'],
            ):
                raise ValueError('Late END')
            analysis = packet_recovery(
                verified, report['source_start'], report['source_final'], plan['expected_config']
            )
            if analysis != report['analysis']:
                raise ValueError('Cached analysis mismatch')
            result['analysis'] = analysis
        elif [r['condition'] for r in verified] != ['OFF'] or verified[0]['stream']['packets']:
            raise ValueError('Invalid OFF control')
    else:
        if 'analysis' in report:
            raise ValueError('Failed control carries recall analysis')
        result['exclusion'] = (
            'Failed campaign: no accepted recall, even when individual wire observations validate.'
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = [project(label, Path(path)) for label, path in (v.split('=', 1) for v in args.input)]
    args.output.write_text(json.dumps(dict(runs=results), indent=2) + '\n')


if __name__ == '__main__':
    main()
