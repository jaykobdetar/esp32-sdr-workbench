import copy
import json

import pytest
from test_packet_only import objects, source, wire

from scripts.four_receiver_packets import configuration
from scripts.project_multi_packet_only import condition_key, project
from sdr_research.packet_only import validate_lines


def fixture(tmp_path):
    cal = {'sha256': 'a' * 64, 'bytes': 1904, 'device_us': 1}
    plan = dict(
        receivers=2,
        count=3,
        period_us=10000,
        cap=16,
        stagger_ms=0,
        source_duration_ms=5000,
        off_only=True,
        expected_config=configuration(0),
    )
    rows = []
    lines = wire(objects(False))
    for i in range(2):
        (tmp_path / f'off-{i}.wire.txt').write_text('\n'.join(lines) + '\n')
        rows.append(
            dict(
                receiver=i,
                condition='OFF',
                status='verified',
                host_only_planned_delay_ms=0,
                stream=validate_lines(lines, 3, 10000, 16),
                calibration_before=cal,
                calibration_after=cal,
                host_collect_start_ns=1,
                host_collect_end_ns=1001,
            )
        )
    report = dict(
        status='passed-source-off-control',
        plan=plan,
        conditions=rows,
        devices=[{}, {}],
        calibration_before=[cal, cal],
        calibration_after=[cal, cal],
        source_stop=source(),
        source_before=source(),
        source_restored=source(),
    )
    path = tmp_path / 'results.json'
    path.write_text(json.dumps(report))
    return path, report


def test_projection_revalidates_wire_and_is_sanitized(tmp_path):
    path, _ = fixture(tmp_path)
    result = project('ab-off', path)
    assert result['conditions'][0]['wire_verified']
    assert 'analysis' not in result
    assert '/home/' not in json.dumps(result)
    assert 'sha256' not in result['conditions'][0]  # calibration identifiers not exposed


@pytest.mark.parametrize(
    'field',
    [
        'receivers',
        'count',
        'period_us',
        'cap',
        'stagger_ms',
        'source_duration_ms',
        'off_only',
        'power',
    ],
)
def test_full_condition_groups_distinct(tmp_path, field):
    _, report = fixture(tmp_path)
    original = report['plan']
    changed = copy.deepcopy(original)
    if field == 'power':
        changed['expected_config']['power_dbm'] = -4
    elif field == 'off_only':
        changed[field] = False
    else:
        changed[field] += 1
    assert condition_key(original) != condition_key(changed)


@pytest.mark.parametrize('mutation', ['running', 'missing', 'corrupt', 'cleanup', 'analysis'])
def test_projection_failure_accounting(tmp_path, mutation):
    path, report = fixture(tmp_path)
    if mutation == 'running':
        report['status'] = 'running'
    if mutation == 'missing':
        report['conditions'].pop()
    if mutation == 'corrupt':
        (tmp_path / 'off-0.wire.txt').write_text('bad frame\n')
    if mutation == 'cleanup':
        report['cleanup_errors'] = ['failed']
    if mutation == 'analysis':
        report.update(status='failed', analysis={})
    path.write_text(json.dumps(report))
    with pytest.raises((ValueError, RuntimeError)):
        project('control', path)


def test_failed_partial_stream_is_retained_without_recall(tmp_path):
    path, report = fixture(tmp_path)
    report['status'] = 'failed'
    path.write_text(json.dumps(report))
    (tmp_path / 'off-0.wire.txt').write_text('partial bad frame\n')
    result = project('failed', path)
    assert result['conditions'][0]['wire_verified'] is False
    assert result['conditions'][1]['wire_verified'] is True
    assert 'analysis' not in result
    assert result['status'] == 'failed'


def test_retained_four_receiver_projection_groups_and_totals():
    from pathlib import Path

    evidence = json.loads(
        (Path(__file__).parents[1] / 'docs/evidence/multi-packet-initial/summary.json').read_text()
    )
    runs = {r['label']: r for r in evidence['runs']}
    labels = [f'abcd-stagger5-{i}' for i in (1, 2, 3)]
    group = [runs[label] for label in labels]
    assert len({r['condition_key'] for r in group}) == 1
    assert runs['abcd-simultaneous']['condition_key'] != group[0]['condition_key']
    assert runs['ab-stagger5']['condition_key'] != group[0]['condition_key']
    assert sum(r['analysis']['unique_packets'] for r in group) == 1042
    assert sum(r['analysis']['completed_transmissions'] for r in group) == 14936
    for row in group:
        assert row['status'] == 'passed'
        assert row['analysis']['duplicate_observations'] == 0
        assert row['analysis']['source_off_packets'] == 0
        assert len(row['conditions']) == 8
        assert [r['unique_packets'] for r in row['analysis']['per_board']] == {
            'abcd-stagger5-1': [81, 106, 79, 94],
            'abcd-stagger5-2': [77, 108, 74, 86],
            'abcd-stagger5-3': [69, 104, 80, 84],
        }[row['label']]
        assert all(
            c['wire_verified']
            and c['completed'] == 128
            and c['skipped'] == 0
            and c['output_drops'] == 0
            for c in row['conditions']
        )
