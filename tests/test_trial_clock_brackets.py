"""Prospective batch policy tests; synthetic sealed telemetry, no hardware."""

import copy

import pytest
from test_dual_stream_analysis_review import row as dual_row

from scripts.multi_stream_campaign import Campaign, analyze_run
from scripts.trial_clock_brackets import anchor_seal, batch_spec, select_trial_anchors, trial_spec


def reseal(row, anchors):
    for receipt in row['clock_bracket_batches']:
        receipt.update(
            anchor_seal([a for a in anchors if a.get('batch_id') == receipt['batch_id']])
        )


def fixture():
    row = dual_row()
    row['scheduled_device_us'] = [row['scheduled_a_us'], row.pop('scheduled_b_us')]
    row.update(index=0, clock_brackets=trial_spec(0))
    anchors, receipts = [], []
    for role, offset in [('before', 0), ('after', 8)]:
        spec = batch_spec(0, role)
        pairs = list(range(offset, offset + 8))
        receipts.append(dict(spec, status='complete', pair_ids=pairs))
        for i, pair in enumerate(pairs):
            t = 990000 + i * 100 if role == 'before' else 1020000 + i * 100
            anchors.append(
                dict(
                    spec,
                    pair=pair,
                    sequence=i,
                    receiver_index=1,
                    a_us=t,
                    b_us=t + 123456 + 23.4e-6 * (t - 1000000),
                )
            )
    row['clock_bracket_batches'] = receipts
    reseal(row, anchors)
    return row, anchors


def test_explicit_eight_groups_all_used_and_audited():
    row, anchors = fixture()
    result = analyze_run(row, anchors)
    assert result['status'] == 'verified-telemetry'
    assert result['clock_brackets']['assigned_anchor_count'] == 16
    model = result['clock_models_to_reference'][0]
    assert model['anchor_count'] == 16
    assert model['heldout_evaluated_fold_count'] == 16
    assert result['clock_brackets']['receiver_brackets'][0]['before_pair_ids'] == list(range(8))


@pytest.mark.parametrize(
    'field,value', [('role', 'wrong'), ('trial_index', 1), ('pair', 100), ('a_us', float('nan'))]
)
def test_malformed_assigned_anchor_rejected(field, value):
    row, anchors = fixture()
    anchors[0][field] = value
    assert analyze_run(row, anchors)['status'] == 'unverified'


@pytest.mark.parametrize('fault', ['age', 'minimum', 'receipt', 'policy', 'duplicate', 'inside'])
def test_batch_invariants_fail_closed(fault):
    row, anchors = fixture()
    if fault == 'age':
        anchors[0]['a_us'] = row['scheduled_a_us'] - 60000001
    if fault == 'minimum':
        anchors.pop()
    if fault == 'receipt':
        row['clock_bracket_batches'][1]['status'] = 'collecting'
    if fault == 'policy':
        row['clock_brackets']['minimum_groups_per_side'] = 3
    if fault == 'duplicate':
        anchors.append(copy.deepcopy(anchors[0]))
    if fault == 'inside':
        anchors[0]['a_us'] = row['scheduled_a_us'] + 1
    assert analyze_run(row, anchors)['status'] == 'unverified'


def test_no_future_batch_leakage():
    row, anchors = fixture()
    original = analyze_run(row, anchors)
    future = copy.deepcopy(anchors)
    for a in future:
        a.update(batch_spec(1, a['role']))
        a['b_us'] += 10000
        a['pair'] += 100
    assert analyze_run(row, anchors + future) == original


def test_all_assigned_groups_no_residual_selected_exclusion_or_eight_group_cap():
    row, anchors = fixture()
    extra = dict(anchors[-1], pair=16, sequence=99, a_us=1020900, b_us=1020900 + 123456 + 1000)
    row['clock_bracket_batches'][1]['pair_ids'].append(16)
    anchors.append(extra)
    reseal(row, anchors)
    selected, diagnostics = select_trial_anchors(row, anchors)
    assert len(selected) == 17 and diagnostics['assigned_anchor_count'] == 17
    assert analyze_run(row, anchors)['status'] == 'unverified'


def test_whole_group_heldout_not_packetwise():
    row, anchors = fixture()
    # Many packets from one capture are still one independent fold/group.
    extras = [
        dict(
            anchors[0],
            sequence=100 + i,
            a_us=anchors[0]['a_us'] + i,
            b_us=anchors[0]['b_us'] + i * (1 + 23.4e-6),
        )
        for i in range(20)
    ]
    reseal(row, anchors + extras)
    result = analyze_run(row, anchors + extras)
    assert result['status'] == 'verified-telemetry'
    assert result['clock_models_to_reference'][0]['anchor_count'] == 36
    assert result['clock_models_to_reference'][0]['heldout_evaluated_fold_count'] == 16


def test_durable_progress_excludes_prior_large_streams(tmp_path):
    c = object.__new__(Campaign)
    c.out = tmp_path
    c._anchor_batch = dict(batch_spec(0, 'before'), status='collecting', pair_ids=[1])
    c.report = {
        'source_sha256': {},
        'anchors': [dict(batch_id=c._anchor_batch['batch_id'], pair=1)],
        'anchor_pairs': [dict(index=1)],
        'runs': [{'large': 'PRIVATE_STREAM_DATA'}],
    }
    c._save_anchor_progress()
    text = (tmp_path / 'anchor-progress-trial-0000-before.json').read_text()
    assert 'PRIVATE_STREAM_DATA' not in text
    assert 'collecting' in text


def test_batch_receipt_type_rejected():
    row, anchors = fixture()
    row['clock_bracket_batches'][0] = 'bad'
    assert analyze_run(row, anchors)['status'] == 'unverified'


def test_trial_orchestration_freezes_one_analysis_without_prebatch_full_save(tmp_path):
    row, anchors = fixture()
    c = object.__new__(Campaign)
    c.report = dict(runs=[], anchors=[])
    events = []

    def bracket(index, role, **kwargs):
        assert index == 0
        events.append(role)
        c.report['anchors'].extend(a for a in anchors if a['role'] == role)
        return row['clock_bracket_batches'][0 if role == 'before' else 1]

    def run(*args):
        events.append('run')
        assert c._pending_brackets == trial_spec(0)
        c.report['runs'].append(copy.deepcopy(row))

    c.bracket_batch, c.run = bracket, run
    c.save = lambda: events.append('full-save')
    result = c.trial_clock_run(10, 2000000, [34, 34])
    assert events == ['before', 'run', 'after', 'full-save']
    assert result['analysis_frozen'] is True
    frozen = copy.deepcopy(result['analysis'])
    c.report['anchors'].append(dict(batch_spec(1, 'after'), b_us=1e50))
    assert result['analysis'] == frozen
    assert analyze_run(result, c.report['anchors']) == frozen


def test_batch_progress_never_serializes_full_history_and_marks_failure(tmp_path):
    c = object.__new__(Campaign)
    c.out = tmp_path
    c.report = dict(source_sha256={}, anchors=[], anchor_pairs=[], runs=[])
    c.save = lambda: pytest.fail('Batch must not perform a full report save')

    def fail(**kwargs):
        assert kwargs == dict(needed=8, attempts=60)
        raise RuntimeError('not enough shared anchors')

    c.anchors = fail
    with pytest.raises(RuntimeError, match='not enough'):
        c.bracket_batch(0, 'before')
    import json

    saved = json.loads((tmp_path / 'anchor-progress-trial-0000-before.json').read_text())
    assert saved['batch']['status'] == 'failed'
    with pytest.raises(ValueError, match='reused'):
        c.bracket_batch(0, 'before')


def test_mistagged_assigned_group_is_not_silently_excluded():
    row, anchors = fixture()
    extra = dict(anchors[0], pair=16, sequence=16, batch_id='unassigned')
    row['clock_bracket_batches'][0]['pair_ids'].append(16)
    anchors.append(extra)
    assert analyze_run(row, anchors)['status'] == 'unverified'


def test_stale_prebatch_stops_before_stream_submission(monkeypatch):
    import scripts.multi_stream_campaign as campaign

    row, anchors = fixture()
    c = object.__new__(Campaign)
    c.radios = [object(), object()]
    c.tx = type('TX', (), {'stop': lambda self: None})()
    c.report = dict(anchors=[a for a in anchors if a['role'] == 'before'])
    c._pending_brackets = trial_spec(0)
    monkeypatch.setattr(campaign, 'clock_probe', lambda _: {'offset_us': 0})
    monkeypatch.setattr(campaign.time, 'monotonic_ns', lambda: 62000000000)
    with pytest.raises(ValueError, match='pre-batch exceeds'):
        c._run_stream(1000, 1875000, [34, 34])


def test_expired_postbatch_stops_before_another_transmission(monkeypatch):
    import scripts.multi_stream_campaign as campaign

    c = object.__new__(Campaign)
    c.radios = [object(), object()]

    class TX:
        def stop(self):
            pass

        def start(self, **kwargs):
            pytest.fail('Stale post-batch must not transmit again')

    c.tx = TX()
    c.pool = type('Pool', (), {'map': lambda self, fn, radios: map(fn, radios)})()
    c.report = dict(anchors=[], anchor_pairs=[])
    c._anchor_batch = dict(batch_spec(0, 'after'), reference_boundary_us=1000000)
    monkeypatch.setattr(campaign, 'clock_probe', lambda _: {'offset_us': 0})
    monkeypatch.setattr(campaign.time, 'monotonic_ns', lambda: 62000000000)
    with pytest.raises(ValueError, match='Post-batch cannot'):
        c.anchors(needed=8)


def test_removed_outlier_cannot_pass_with_original_completed_receipt():
    row, anchors = fixture()
    extra = dict(anchors[-1], pair=16, sequence=99, a_us=1020900, b_us=1020900 + 123456 + 1000)
    row['clock_bracket_batches'][1]['pair_ids'].append(16)
    anchors.append(extra)
    reseal(row, anchors)
    assert analyze_run(row, anchors)['status'] == 'unverified'
    anchors.pop()
    result = analyze_run(row, anchors)
    assert result['status'] == 'unverified'
    assert 'inventory seal' in result['reason']


def test_timestamp_mutation_fails_seal_even_when_fit_would_pass():
    row, anchors = fixture()
    anchors[0]['b_us'] += 0.1
    result = analyze_run(row, anchors)
    assert result['status'] == 'unverified' and 'inventory seal' in result['reason']


def test_anchor_partial_submission_and_interrupted_join_wait_for_actual_reader(tmp_path):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    started, release, finished = Event(), Event(), Event()

    class TX:
        stops = 0

        def start(self, **kwargs):
            pass

        def stop(self):
            self.stops += 1
            release.set()

    class InterruptingFuture:
        def __init__(self, future):
            self.future = future
            self.calls = 0

        def done(self):
            return self.future.done()

        def result(self):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt('second interruption while joining')
            return self.future.result()

    class PartialPool:
        calls = 0

        def __init__(self, pool):
            self.pool = pool

        def submit(self, fn, *args):
            self.calls += 1
            if self.calls == 2:
                assert started.wait(2)
                raise RuntimeError('primary partial submission failure')
            self.future = InterruptingFuture(self.pool.submit(fn, *args))
            return self.future

    def reader(*args):
        started.set()
        assert release.wait(2)
        time.sleep(0.03)
        finished.set()
        return ({}, None)

    c = object.__new__(Campaign)
    c.radios, c.out, c.tx, c.report, c.raw = [object(), object()], tmp_path, TX(), {}, reader
    with ThreadPoolExecutor(2) as pool:
        c.pool = PartialPool(pool)
        with pytest.raises(RuntimeError, match='primary partial submission failure'):
            c._capture_anchor_pair(0, [1, 2])
        assert finished.is_set() and c.pool.future.done()
        assert c.tx.stops == 1
        assert c.report['anchor_failures'][0]['readers_joined'] is True
        assert (
            c.report['anchor_failures'][0]['cleanup_observations'][0]['stage']
            == 'reader-join-interrupted'
        )


def test_uncertain_start_still_stops_and_preserves_primary(tmp_path):
    class TX:
        stopped = False

        def start(self, **kwargs):
            raise TimeoutError('uncertain START')

        def stop(self):
            self.stopped = True
            raise RuntimeError('secondary STOP')

    c = object.__new__(Campaign)
    c.radios, c.out, c.tx, c.report = [], tmp_path, TX(), {}
    with pytest.raises(TimeoutError, match='uncertain START'):
        c._capture_anchor_pair(0, [])
    assert c.tx.stopped
