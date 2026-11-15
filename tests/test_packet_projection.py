import copy
import json
from pathlib import Path

import pytest

from scripts.project_packet_controls import aggregate, project

EVIDENCE = Path(__file__).resolve().parents[1] / 'docs/evidence/iq-format-initial/summary.json'


def test_numeric_projection_accounting_and_privacy():
    data = json.loads(EVIDENCE.read_text())
    assert len(data['runs']) == 8
    assert data['groups'] == aggregate(data['runs'])
    for run in data['runs']:
        assert run['status'] == 'passed'
        assert all(
            run[key] is True
            for key in ('calibration_unchanged', 'source_stopped', 'source_config_restored')
        )
        for condition in run['conditions']:
            assert condition['captures'] == sum(condition['per_receiver_captures'])
            assert condition['calls_started_after_latest_source_duration_deadline'] == 0
        packets = run['packet_analysis']
        assert (
            packets['unique_packets'] + packets['duplicate_observations']
            == packets['accepted_observations']
        )
        assert packets['source_off_packets'] == 0
    text = EVIDENCE.read_text()
    for forbidden in ('/home/', '/dev/', 'CALHASH', 'serial_number', 'device_us', '.npy'):
        assert forbidden not in text


def test_aggregate_never_pools_different_stagger_conditions():
    row = json.loads(EVIDENCE.read_text())['runs'][0]
    changed = copy.deepcopy(row)
    changed['stagger_ms'] = 5
    assert len(aggregate([row, changed])) == 2


@pytest.mark.parametrize('status', ['running', 'failed', None])
def test_project_rejects_incomplete_results(status):
    with pytest.raises(ValueError, match='completed passed'):
        project('test', {'status': status})


def test_project_rejects_identifying_path_as_label():
    with pytest.raises(ValueError, match='non-identifying'):
        project('/home/person/result', {})
