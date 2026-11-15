import copy
import json

import pytest
from test_packet_only import objects, wire

from scripts.project_packet_only import project
from sdr_research.packet_only import validate_lines


def fixture(tmp_path):
    lines = wire(objects(False))
    stream = validate_lines(lines, 3, 10000, 16)
    cal = [{'sha256': 'a' * 64, 'bytes': 1904, 'device_us': 1}]
    report = dict(
        status='failed',
        plan=dict(
            count=3,
            period_us=10000,
            cap=16,
            source_duration_ms=3000,
            expected_config={'power_dbm': 0},
        ),
        conditions=[
            dict(
                condition='OFF',
                stream=stream,
                calibration_before=cal,
                calibration_after=cal,
                host_collect_start_ns=1,
                host_collect_end_ns=1001,
            )
        ],
    )
    (tmp_path / 'off.wire.txt').write_text('\n'.join(lines) + '\n')
    path = tmp_path / 'results.json'
    path.write_text(json.dumps(report))
    return path, report


def test_failure_projection_never_salvages_recall(tmp_path):
    path, _ = fixture(tmp_path)
    result = project('failed-control', path)
    assert result['status'] == 'failed'
    assert 'analysis' not in result
    assert result['conditions'][0]['completed'] == 2
    assert '/home/' not in json.dumps(result)


@pytest.mark.parametrize('mutation', ['running', 'analysis', 'wire', 'label'])
def test_projection_rejects_inconsistent_or_unfinished(tmp_path, mutation):
    path, report = fixture(tmp_path)
    report = copy.deepcopy(report)
    if mutation == 'running':
        report['status'] = 'running'
    if mutation == 'analysis':
        report['analysis'] = {}
    if mutation == 'wire':
        report['conditions'][0]['stream']['end']['completed'] = 100
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        project('invalid/path' if mutation == 'label' else 'test', path)
