import copy

import pytest
from test_dual_stream_analysis_review import anchors, row, seal_result

from scripts.dual_stream_campaign import analyze_run, delta_at, fit_clock


def test_final_drain_reduces_completion_coverage_not_requested_coverage():
    initial = row()
    baseline = analyze_run(initial, anchors())
    extended = copy.deepcopy(initial)
    # No samples change: only receiver-B's final drain becomes 10ms longer.
    extended['receivers'][1]['summary']['end_us'] += 10000
    seal_result(extended['receivers'][1])
    result = analyze_run(extended, anchors())
    assert result['status'] == 'verified-telemetry'
    assert result['nominal_union'] == baseline['nominal_union']
    assert (
        result['nominal_full_burst_opportunities'] == baseline['nominal_full_burst_opportunities']
    )
    assert (
        result['nominal_completion_inclusive_union']['coverage_percent']
        < baseline['nominal_completion_inclusive_union']['coverage_percent']
    )
    assert (
        result['nominal_completion_inclusive_union']['covered_us']
        == baseline['nominal_completion_inclusive_union']['covered_us']
    )
    assert 'ASCII' in result['nominal_completion_inclusive_union']['excludes']


def test_completion_uses_later_mapped_receiver_not_raw_clock_epoch():
    data = row()
    model = fit_clock(anchors())
    completion_a = 1_015_000
    for i, receiver in enumerate(data['receivers']):
        receiver['summary']['end_us'] = completion_a + (delta_at(completion_a, model) if i else 0)
        seal_result(receiver)
    result = analyze_run(data, anchors())
    completion = result['nominal_completion_inclusive_union']
    assert completion['start_a_us'] == 1_000_000
    assert completion['end_a_us'] == pytest.approx(completion_a, abs=1)
    assert completion['duration_us'] == pytest.approx(15000, abs=1)
    assert result['nominal_union']['duration_us'] == 10000


def test_host_elapsed_is_separate_optional_information():
    data = row()
    data['receivers'][0]['host_elapsed_s'] = 0.123
    data['receivers'][1]['host_elapsed_s'] = 10.0
    baseline = analyze_run(row(), anchors())
    result = analyze_run(data, anchors())
    assert result['receiver_host_elapsed_s'] == [0.123, 10.0]
    assert baseline['receiver_host_elapsed_s'] == [None, None]
    assert (
        result['nominal_completion_inclusive_union']
        == baseline['nominal_completion_inclusive_union']
    )
