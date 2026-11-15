"""Check sanitized projections; these are not raw RF replay or hardware tests."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / 'docs/evidence/four-receiver-evaluation'


def load(name):
    return json.loads((ROOT / name).read_text())


def test_packet_projection_arithmetic_and_negative_controls():
    for path in ROOT.glob('packets-*.json'):
        data = load(path.name)
        assert data['source_final_running'] is False
        assert data['captures_by_condition']['OFF'] > 0
        assert data['captures_by_condition']['ON'] > 0
        result = data['analysis'] or data['separate_reanalysis']['analysis']
        assert result['source_off_packets'] == 0
        assert result['completed_transmissions'] == result['attempted_transmissions']
        assert result['scheduled_slots'] == (
            result['attempted_transmissions'] + result['missed_slots']
        )
        assert result['recovery_percent'] == pytest.approx(
            100 * result['unique_packets'] / result['completed_transmissions']
        )
        assert result['accepted_observations'] == (
            result['unique_packets'] + result['duplicate_observations']
        )
    assert load('packets-smoke.json')['status'] == 'failed'
    assert load('packets-staggered.json')['capture_plan']['stagger_ms'] == 100


def test_timing_projection_preserves_failed_trial_and_boundaries():
    data = load('timing-30s.json')
    assert data['status'] == 'failed'
    assert len(data['trials']) == 2  # The third rejected stream is not a successful trial.
    for path in ROOT.glob('timing-*.json'):
        for trial in load(path.name)['trials']:
            if trial['analysis_status'] != 'verified-telemetry':
                continue
            result = trial['nominal_union']
            assert result['duration_us'] == trial['duration_ms'] * 1000
            assert 0 <= result['covered_us'] <= result['duration_us']
            assert result['coverage_percent'] == pytest.approx(
                100 * result['covered_us'] / result['duration_us']
            )
            assert result['max_gap_us'] > 0  # No gap-free result is claimed in this set.
            assert result['first_gaps_relative_us'][0][0] == 0


def test_transport_failure_and_preservation_are_not_hidden():
    data = load('transport-control.json')
    assert data['source_final_running'] is False
    assert [row['status'] for row in data['trials']] == ['failed', 'passed', 'failed', 'passed']
    for row in data['trials'][::2]:
        assert row['receiver_label'] == 'C'
        assert row['failed_frame_all_ff'] is True
    for row in load('postboot-preservation-audit.json')['receivers']:
        assert row['application_verified'] is True
        regions = {value['region']: value for value in row['regions']}
        assert regions['bootloader']['unchanged_from_original'] is True
        assert regions['phy_init']['unchanged_from_original'] is True
        assert regions['nvs']['unchanged_from_original'] is False


def test_public_projection_has_no_machine_paths_or_raw_device_identity():
    forbidden = {'port', 'mac', 'serial_number', 'calhash', 'frame_hex', 'payload_hex_observed'}

    def inspect(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    for path in ROOT.glob('*.json'):
        text = path.read_text()
        assert '/home/' not in text and '/dev/' not in text
        inspect(json.loads(text))


@pytest.mark.parametrize(
    ('name', 'expected_count', 'expected_percent'),
    [
        ('timing-smoke.json', 1, 99.69999),
        ('timing-30s.json', 2, 99.89999666666667),
        ('timing-abd-120s.json', 2, 99.97499916666666),
    ],
)
def test_decision_union_keeps_warmup_in_requested_denominator(
    name, expected_count, expected_percent
):
    trials = load(name)['trials']
    assert len(trials) == expected_count
    for trial in trials:
        assert trial['analysis_status'] == 'verified-telemetry'
        decision = trial['nominal_decision_union']
        duration_us = trial['duration_ms'] * 1000
        assert decision['duration_us'] == duration_us
        assert decision['covered_us'] == duration_us - 30001
        assert decision['coverage_percent'] == pytest.approx(expected_percent, rel=0, abs=1e-10)
        assert decision['gap_count'] == 1
        assert decision['max_gap_us'] == 30001
        assert decision['first_gaps_relative_us'] == [[0, 30001]]
        assert decision['gap_list_truncated'] is False
        assert decision['covered_us'] < trial['nominal_union']['covered_us']
