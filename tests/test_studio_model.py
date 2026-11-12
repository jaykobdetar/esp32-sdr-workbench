"""Presentation contracts: no Qt imports, devices, or serial access required."""

import json

import pytest

from sdr_research.studio_model import TASKS, describe_result, readiness, session_history


@pytest.mark.parametrize('task', TASKS)
def test_every_task_requires_receiver(task):
    assert readiness(task, 0, 1, False)


@pytest.mark.parametrize('demo', [False, True])
def test_listen_requires_no_transmitter(demo):
    assert readiness('listen', 1, 0, demo) is None


def test_compare_requires_two_receivers():
    assert readiness('compare', 1, 0, False)
    assert readiness('compare', 2, 0, False) is None
    assert readiness('compare', 2, 0, True) is None


def test_test_signal_requires_physical_transmitter_and_receivers():
    assert readiness('test', 1, 0, False)
    assert readiness('test', 1, 1, True)
    assert readiness('test', 1, 1, False) is None


@pytest.mark.parametrize(
    'state,title',
    [
        ('complete', 'Session complete'),
        ('stopped', 'Session stopped'),
        ('running', 'Session unfinished'),
        ('error', 'Session needs attention'),
    ],
)
def test_receive_only_result_does_not_claim_hardware_stop(state, title):
    actual, detail = describe_result({'status': state})
    assert actual == title
    assert 'No transmitter was requested' in detail
    assert 'stop confirmed' not in detail.lower()


@pytest.mark.parametrize(
    'extra',
    [
        {'error': 'Connection refused'},
        {'cleanup_errors': ['Restore failed']},
        {'receiver_results': {'Receiver 1': {'error': 'Disconnected'}}},
    ],
)
def test_errors_override_complete(extra):
    title, detail = describe_result({'status': 'complete', **extra})
    assert title == 'Session needs attention'
    assert len(detail.splitlines()) > 1


def tx_manifest(stops):
    return {
        'status': 'complete',
        'transmitters': [{'label': name} for name in stops],
        'transmitter_results': {name: {'stop': stop} for name, stop in stops.items()},
    }


def test_all_requested_transmitters_must_confirm_stop():
    _, detail = describe_result(
        tx_manifest(
            {'A': {'running': False, 'completed': 1000}, 'B': {'running': False, 'completed': 500}}
        )
    )
    assert 'stop confirmed' in detail
    assert '1,500 transmissions completed' in detail


@pytest.mark.parametrize('running', [True, None, 0, 'false'])
def test_only_boolean_false_confirms_stop(running):
    _, detail = describe_result(tx_manifest({'A': {'running': running}}))
    assert 'NOT confirmed' in detail


def test_one_missing_stop_prevents_global_confirmation():
    _, detail = describe_result(tx_manifest({'A': {'running': False}, 'B': {}}))
    assert 'NOT confirmed' in detail


def test_missing_transmitter_result_cannot_claim_stop():
    _, detail = describe_result({'status': 'error', 'transmitters': [{'label': 'A'}]})
    assert 'NOT confirmed' in detail


def write_manifest(root, name, content):
    folder = root / name
    folder.mkdir(parents=True)
    path = folder / 'session.json'
    path.write_text(content)
    return folder


def test_history_is_reverse_order_and_keeps_incomplete_sessions(tmp_path):
    older = write_manifest(tmp_path, '20260101', json.dumps({'status': 'error'}))
    newer = write_manifest(tmp_path, '20260102', json.dumps({'status': 'running'}))
    assert session_history(tmp_path) == [
        (newer, {'status': 'running'}),
        (older, {'status': 'error'}),
    ]


def test_history_skips_invalid_nonobject_oversized_and_nested_manifests(tmp_path):
    write_manifest(tmp_path, 'broken', '{')
    write_manifest(tmp_path, 'array', '[]')
    write_manifest(tmp_path, 'large', ' ' * 2_000_001)
    write_manifest(tmp_path, 'nested/child', '{}')
    valid = write_manifest(tmp_path, 'valid', '{}')
    assert session_history(tmp_path) == [(valid, {})]


def test_history_missing_folder_is_empty(tmp_path):
    assert session_history(tmp_path / 'absent') == []


def test_history_limits_scan_to_200_recent_names(tmp_path):
    for index in range(205):
        write_manifest(tmp_path, f'{index:03}', '{}')
    entries = session_history(tmp_path)
    assert len(entries) == 200
    assert entries[0][0].name == '204'
    assert entries[-1][0].name == '005'


@pytest.mark.parametrize(
    'manifest',
    [
        None,
        [],
        {'transmitters': None},
        {'transmitters': [None]},
        {'transmitters': [{'label': []}]},
        {'transmitter_results': None},
        {'receiver_results': {'A': None}},
        {'cleanup_errors': None},
        {'transmitters': [{'label': 'A'}], 'transmitter_results': {'A': {'stop': None}}},
    ],
)
def test_malformed_history_is_reported_not_crashed(manifest):
    title, detail = describe_result(manifest)
    assert title == 'Session needs attention'
    assert 'stop confirmed' not in detail.lower()


def test_unknown_stop_overrides_nominal_completion():
    title, _ = describe_result(tx_manifest({'A': {}}))
    assert title == 'Session needs attention'


@pytest.mark.parametrize('count', [None, '500', -1, True, 5.5])
def test_invalid_count_does_not_crash_or_invent_number(count):
    _, detail = describe_result(tx_manifest({'A': {'running': False, 'completed': count}}))
    assert 'stop confirmed' in detail
    assert 'count unavailable' in detail


def test_count_excludes_unrequested_result():
    manifest = tx_manifest({'A': {'running': False, 'completed': 7}})
    manifest['transmitter_results']['other'] = {'stop': {'running': False, 'completed': 999}}
    assert '7 transmissions completed' in describe_result(manifest)[1]


def test_duplicate_transmitter_labels_are_not_safe_confirmation():
    manifest = tx_manifest({'A': {'running': False, 'completed': 7}})
    manifest['transmitters'].append({'label': 'A'})
    title, detail = describe_result(manifest)
    assert title == 'Session needs attention'
    assert 'NOT confirmed' in detail
