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


def test_awake_serial_controls_preserve_intermittence_and_setup_failure():
    data = load('awake-serial-controls.json')
    rows = data['trials']
    assert len(rows) == 6
    assert [r['status'] for r in rows[:3]] == [
        'passed-exact-response-control',
        'failed',
        'passed-exact-response-control',
    ]
    assert [r['receiver_label'] for r in rows] == ['C', 'C', 'A', 'C', 'C', 'C']
    failure = rows[1]
    assert 8 < failure['elapsed_seconds'] < 9
    assert failure['leading_ff_bytes'] == 64
    assert failure['failed_response_bytes'] == 254
    assert failure['remainder_after_64_exact'] is True
    assert failure['same_descriptor_resynchronized'] is True
    assert failure['calibration_hash_unchanged'] is True
    for row in rows[3:]:
        assert row['status'] == 'passed-exact-response-control'
        assert 120 <= row['elapsed_seconds'] < 121
        assert row['failed_response_bytes'] == 0
    attempts = {row['cohort']: row for row in data['attempts']}
    absent = attempts['awake-c-new-port-control']
    assert absent['trial_count'] == 2
    assert absent['source_condition'] == 'physically-absent'
    setup = attempts['awake-c-new-port-with-source-control']
    assert setup['status'] == 'failed' and setup['trial_count'] == 0
    restored = attempts['awake-c-new-port-with-source-control-retry1']
    assert restored['status'] == 'passed' and restored['trial_count'] == 1
    assert restored['source_condition'] == 'connected-stopped'


def test_corrected_iq8_replay_preserves_observation_and_unique_distinction():
    data = load('iq8-offline-replay.json')
    assert data['status'] == 'passed'
    assert data['quantized_dtype'] == 'complex64'
    assert len(data['prior_replay_attempts']) == 2
    runs = {r['run']: r['analysis'] for r in data['runs']}
    assert len(runs) == 5
    weak = runs.pop('packets-low-repeat')
    assert weak['original_on_observations'] == 8
    assert weak['iq8_on_observations'] == 7
    assert weak['lost_observations'] == 1
    assert weak['original_unique_packets'] == weak['iq8_unique_packets'] == 7
    assert sum(a['original_on_observations'] for a in runs.values()) == 187
    assert sum(a['iq8_on_observations'] for a in runs.values()) == 187
    for result in [*runs.values(), weak]:
        assert result['captures'] == result['on_captures'] + result['off_captures']
        assert result['original_off_observations'] == result['iq8_off_observations'] == 0
        assert result['gained_observations'] == result['gained_unique_packets'] == 0
        assert result['lost_unique_packets'] == 0
        assert 'not CAP16 hardware validation' in result['note']
    for result in runs.values():
        assert result['lost_observations'] == 0


def test_awake_projections_in_source_distribution_manifest():
    manifest = (ROOT.parents[2] / 'MANIFEST.in').read_text()
    for name in ('awake-serial-controls.json', 'iq8-offline-replay.json'):
        assert f'include docs/evidence/four-receiver-evaluation/{name}' in manifest.splitlines()


def test_awake_timing_keeps_startup_failure_and_rejected_stream_separate():
    data = load('timing-awake-four-120s.json')
    assert data['status'] == 'failed' and data['source_final_running'] is False
    assert data['initial_startup_attempt']['accepted_trial_count'] == 0
    assert data['initial_startup_attempt']['source_final_running'] is False
    assert len(data['trials']) == 2
    for row, gap in zip(data['trials'], [13, 5], strict=True):
        assert row['duration_ms'] == 120000
        assert row['nominal_union']['max_gap_us'] == gap
        assert row['nominal_decision_union']['covered_us'] == 120000000 - 30001
    assert len(data['rejected_trials']) == 1
    rejected = data['rejected_trials'][0]
    assert 'nominal_union' not in rejected
    assert rejected['earliest_observed_error_receiver'] == 'C'
    peers = {r['receiver_label']: r for r in rejected['peer_diagnostics']}
    assert [peers[k]['sequence_gap'] for k in 'ABCD'] == [36, 40, 36, 40]
    assert (
        peers['C']['error_observed_relative_to_shared_stop_us']
        < peers['A']['error_observed_relative_to_shared_stop_us']
        < 0
    )
    assert all(peers[k]['error_observed_relative_to_shared_stop_us'] > 0 for k in 'BD')
    for row in peers.values():
        assert row['failed_frame_crc_valid'] is True
        assert row['same_descriptor_resynchronized'] is True
        assert row['clock_regressed'] is False
        assert row['calibration_hash_unchanged'] is True


def test_gc_observation_retains_monitor_loss_and_only_correlates():
    data = load('timing-awake-gc-observed.json')
    assert data['status'] == 'failed' and data['source_final_running'] is False
    assert len(data['trials']) == 2
    rejected = data['rejected_trials'][0]
    assert rejected['earliest_observed_error_receiver'] == 'D'
    assert 'nominal_union' not in rejected
    assert all(r['sequence_gap'] == 44 for r in rejected['peer_diagnostics'])
    assert all(r['failed_frame_crc_valid'] for r in rejected['peer_diagnostics'])
    monitor = data['host_observation']
    assert monitor['gc_policy_changed'] is False
    assert monitor['gc_event_coverage_at_failure'] is False
    assert monitor['gc_events_retained'] == 20000
    assert monitor['gc_events_dropped'] == 75298
    assert monitor['preceding_heartbeat_gap_ms'] == pytest.approx(249.998862)
    assert monitor['gap_end_before_first_error_ms'] == pytest.approx(3.222629)
    assert monitor['last_retained_gc_event_before_first_error_s'] > 280


def test_nonce_controls_report_actual_not_target_rates():
    data = load('awake-nonce-controls.json')
    assert data['matching_source_revision'].startswith('298261f')
    assert len(data['cohorts']) == 2
    for cohort, requested in zip(data['cohorts'], [5, 120], strict=True):
        assert cohort['status'] == 'passed'
        assert cohort['source_initial_running'] is cohort['source_final_running'] is False
        assert [r['receiver_label'] for r in cohort['trials']] == list('ABCD')
        for row in cohort['trials']:
            assert row['status'] == 'passed' and row['requested_seconds'] == requested
            assert row['elapsed_seconds'] >= requested
            assert row['validated_nonce_replies'] == row['completed_batches'] * 16
            assert row['actual_validated_bytes_per_second'] == pytest.approx(
                row['validated_response_bytes'] / row['elapsed_seconds']
            )
            assert (
                row['actual_validated_bytes_per_second'] < row['target_response_bytes_per_second']
            )
    assert [
        round(r['actual_validated_bytes_per_second'], 1) for r in data['cohorts'][1]['trials']
    ] == [24112.2, 24221.2, 24029.4, 24083.6]


def test_gc_deferred_complete_transport_does_not_certify_coverage():
    data = load('timing-awake-gc-deferred.json')
    assert data['status'] == 'failed' and data['production_mitigation'] is False
    assert data['source_final_running'] is False
    assert len(data['trials']) == 3
    for trial in data['trials']:
        assert trial['analysis_status'] == 'unverified'
        assert 'nominal_union' not in trial and 'nominal_decision_union' not in trial
        assert trial['transport_record_counts'] == [64001, 64002, 64000, 64001]
        assert all(trial['transport_crc_valid'])
        assert trial['gc_disabled_during_coordinator_call'] is True
        assert trial['gc_restored'] is True
        assert trial['max_observed_in_run_heartbeat_interval_ms'] < 20
        assert any(f['max_heldout_error_us'] > 20 for f in trial['clock_fits'])
        assert all(abs(f['relative_drift_ppm']) < 1000 for f in trial['clock_fits'])


def test_batched_nonce_meets_rate_without_workload_equivalence_claim():
    data = load('awake-nonce-batch-control.json')
    assert data['status'] == 'passed' and data['matching_source_revision'] == '5737a47'
    assert data['source_initial_running'] is data['source_final_running'] is False
    assert [r['receiver_label'] for r in data['trials']] == list('ABCD')
    for row in data['trials']:
        assert row['requested_seconds'] == 120
        assert row['validated_response_bytes'] == 3072048
        assert row['completed_batches'] == 9143
        assert row['validated_nonce_replies'] == 9143 * 16
        assert row['actual_validated_bytes_per_second'] == pytest.approx(
            row['validated_response_bytes'] / row['elapsed_seconds']
        )
        assert 25600 < row['actual_validated_bytes_per_second'] < 25601
    assert 'not equivalent to DSTREAM' in data['note']


def test_single_lowrate_trial_retains_slower_warmup_and_separate_scope():
    data = load('timing-awake-lowrate-120s.json')
    assert data['status'] == 'passed' and len(data['trials']) == 1
    assert data['clock_policy'] == 'legacy-global-affine-selector'
    assert data['source_final_running'] is False and data['gc_restored'] is True
    trial = data['trials'][0]
    assert trial['periods_ns'][0] == 3750000
    assert trial['transport_record_counts'] == [32001, 32002, 32001, 32001]
    assert trial['max_late_us'] == [2, 4, 4, 3]
    for name in ('skipped', 'overflow', 'idle_fallbacks'):
        assert trial[name] == [0, 0, 0, 0]
    assert trial['nominal_union']['covered_us'] == 120000000 - 13
    assert trial['nominal_decision_union']['covered_us'] == 120000000 - 60001
    assert trial['nominal_decision_union']['first_gaps_relative_us'] == [[0, 60001]]


def test_prospective_brackets_use_all_sealed_fresh_groups_without_relabeling():
    data = load('timing-awake-prospective-brackets.json')
    assert data['status'] == 'passed' and len(data['trials']) == 3
    assert data['cleanup_errors'] == [] and data['source_final_running'] is False
    assert all(data['calibration_unchanged_by_receiver'])
    for row, total, gap in zip(data['trials'], [59, 65, 66], [13, 5, 5], strict=True):
        assert row['analysis_frozen'] is True and row['gc_restored'] is True
        assert row['analysis_status'] == 'verified-telemetry'
        assert row['transport_record_counts'] == [64001, 64002, 64000, 64001]
        assert row['nominal_union']['first_gaps_relative_us'] == [[0, gap]]
        assert row['nominal_decision_union']['first_gaps_relative_us'] == [[0, 30001]]
        assert row['clock_brackets']['assigned_anchor_count'] == total
        assert sum(b['anchor_count'] for b in row['sealed_batches']) == total
        assert sum(f['anchor_count'] for f in row['clock_fits']) == total
        for batch in row['sealed_batches']:
            assert batch['status'] == 'complete' and len(batch['anchor_sha256']) == 64
        for bracket in row['clock_brackets']['receiver_brackets']:
            for role in ('before', 'after'):
                assert len(bracket[f'{role}_pair_ids']) >= 8
                assert 0 < min(bracket[f'{role}_boundary_age_range_us'])
                assert max(bracket[f'{role}_boundary_age_range_us']) <= 60000000
        for fit in row['clock_fits']:
            assert fit['max_residual_us'] <= 20 and fit['heldout_max_error_us'] <= 20
            assert abs(fit['relative_drift']) <= 0.001
            assert fit['heldout_evaluated_fold_count'] == fit['independent_capture_pair_count']
        assert len(row['sensitivity']) == 3
        assert all(len(s['offset_corner_scenarios']) == 8 for s in row['sensitivity'])
        assert row['sensitivity'][2]['eroded_union']['covered_us'] == 120000000 - gap - 20
    assert load('timing-awake-gc-deferred.json')['status'] == 'failed'


def test_iq8_viewer_closeout_distinguishes_cards_from_timing_labels():
    data = load('awake-iq8-viewer-closeout.json')
    assert data['status'] == 'passed'
    assert data['final_workers_joined'] and data['qt_window_disposed']
    assert len(data['viewer_sessions']) == 2
    for session in data['viewer_sessions']:
        assert session['all_workers_joined'] and len(session['cards']) == 4
        assert all(
            c['crc_ok'] and c['bits'] == 8 and c['samples'] == 1024 for c in session['cards']
        )
    assert len(data['passive_health']) == 4 and data['source_final_running'] is False
    assert all(r['crc_ok'] and r['release'] == 'OK' for r in data['passive_health'])
