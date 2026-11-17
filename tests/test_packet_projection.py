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


def test_failed_12s_control_preserves_denominator_failure_without_recall():
    path = EVIDENCE.with_name('failed-12s-control.json')
    data = json.loads(path.read_text())
    assert data['status'] == 'failed'
    assert data['recall_analysis_accepted'] is False
    final = data['transmitter_final']
    assert final['attempted'] - final['completed'] == 1
    assert final['attempted'] + final['missed_slots'] == final['scheduled']
    assert final['errors'] == 0 and final['running'] is False
    assert [c['retained_captures'] for c in data['conditions']] == [56, 56]
    assert all(c['all_transport_crc_valid'] for c in data['conditions'])
    assert 'recovery_percent' not in path.read_text()
    assert all(r['run'] != data['run'] for r in json.loads(EVIDENCE.read_text())['runs'])


@pytest.mark.parametrize(
    'field,value', [('stagger_ms', 5), ('power_dbm', -20), ('source_duration_ms', 12000)]
)
def test_grouping_separates_protocol_conditions(field, value):
    original = json.loads(EVIDENCE.read_text())['runs'][0]
    changed = copy.deepcopy(original)
    changed[field] = value
    assert len(aggregate([original, changed])) == 2


def test_grouping_separates_acquisition_budget_and_round_cap():
    original = json.loads(EVIDENCE.read_text())['runs'][0]
    for field, value in [('requested_acquisition_budget_ms', 10000), ('round_cap', 32)]:
        changed = copy.deepcopy(original)
        changed['conditions'][1][field] = value
        assert len(aggregate([original, changed])) == 2


def test_matched_stagger_evidence_accounting():
    path = EVIDENCE.parent.parent / 'iq-stagger-matched/summary.json'
    data = json.loads(path.read_text())
    assert len(data['runs']) == 8
    assert data['groups'] == aggregate(data['runs'])
    assert len(data['groups']) == 4
    assert {(g['bits_per_component'], g['stagger_ms']) for g in data['groups']} == {
        (8, 5),
        (8, 100),
        (10, 5),
        (10, 100),
    }
    for run in data['runs']:
        assert run['source_duration_ms'] == 16000
        assert run['packet_analysis']['source_off_packets'] == 0
        assert run['packet_analysis']['duplicate_observations'] == 0
        for condition in run['conditions']:
            assert condition['requested_acquisition_budget_ms'] == 10000
            assert condition['round_cap'] == 32
            assert condition['round_cap_reached'] is False
            assert condition['captures'] == sum(condition['per_receiver_captures'])
            assert condition['calls_started_after_latest_source_duration_deadline'] == 0
            assert condition['calls_ended_after_latest_source_duration_deadline'] == 0
    for forbidden in ('/home/', '/dev/', 'CALHASH', 'serial_number', 'device_us', '.npy'):
        assert forbidden not in path.read_text()
