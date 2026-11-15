"""Synthetic, sealed telemetry. No hardware and no claimed physical coverage."""

import copy
import importlib.util
from pathlib import Path

import pytest
from test_dual_stream_analysis_review import anchors, row

spec = importlib.util.spec_from_file_location(
    'nrf_campaigns.multi_stream_campaign',
    Path(__file__).resolve().parents[1] / 'scripts/multi_stream_campaign.py',
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(count=4):
    data = row()
    data['receivers'] += [copy.deepcopy(data['receivers'][1]) for _ in range(count - 2)]
    values = [dict(a, receiver_index=k) for k in range(1, count) for a in anchors()]
    return data, values


@pytest.mark.parametrize('count', [2, 3, 4])
def test_all_clocks_independently_screened(count):
    data, values = fixture(count)
    result = module.analyze_run(data, values)
    assert result['status'] == 'verified-telemetry'
    assert result['receiver_count'] == count
    assert len(result['clock_models_to_reference']) == count - 1
    assert len(result['sensitivity'][0]['offset_corner_scenarios']) == 2 ** (count - 1)
    assert result['nominal_union']['coverage_percent'] == pytest.approx(100)
    assert result['nominal_decision_union']['coverage_percent'] == 0


@pytest.mark.parametrize('receiver', [1, 2, 3])
def test_missing_clock_not_implicitly_reference_clock(receiver):
    data, values = fixture()
    values = [a for a in values if a['receiver_index'] != receiver]
    assert module.analyze_run(data, values)['status'] == 'unverified'


def test_bad_fourth_stream_fails_whole_union():
    data, values = fixture()
    data['receivers'][3]['transport_crc_valid'] = False
    assert module.analyze_run(data, values)['status'] == 'unverified'


def test_fourth_clock_without_after_bracket_fails():
    data, values = fixture()
    values = [a for a in values if a['receiver_index'] != 3 or a['a_us'] < 1000000]
    assert module.analyze_run(data, values)['status'] == 'unverified'


def test_requested_start_edge_is_not_trimmed():
    data, values = fixture()
    data['scheduled_a_us'] -= 500
    data['duration_ms'] += 0.5
    result = module.analyze_run(data, values)
    assert result['status'] == 'verified-telemetry'
    assert result['nominal_union']['max_gap_us'] >= 499
    assert result['nominal_union']['coverage_percent'] < 96


def test_endpoint_erosion_is_assumption_not_certified_bound():
    data, values = fixture()
    result = module.analyze_run(data, values)
    assert result['sensitivity'][-1]['eroded_union']['coverage_percent'] < 100
    assert 'not confidence bounds' in result['sensitivity_note']


def test_fourth_clock_outlier_rejected():
    data, values = fixture()
    values[-1]['b_us'] += 500
    assert module.analyze_run(data, values)['status'] == 'unverified'


def test_wrong_receiver_count():
    data, values = fixture()
    data['receivers'] *= 2
    assert module.analyze_run(data, values)['status'] == 'unverified'


def test_scheduler_staggers_reference_time_and_drifts_period(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    class Radio:
        def command(self, command):
            return 'CALHASH stable'

    class Tx:
        def stop(self):
            pass

    radios = [Radio() for _ in range(4)]
    calls = {}

    def stream(r, **kwargs):
        calls[radios.index(r)] = kwargs
        return {'summary': {'captures': 1}}

    monkeypatch.setattr(module, 'run_stream', stream)
    monkeypatch.setattr(module, 'clock_probe', lambda r: {'offset_us': 0})
    monkeypatch.setattr(module.time, 'monotonic_ns', lambda: 700000000)
    with ThreadPoolExecutor(4) as pool:
        campaign = module.Campaign(radios, Tx(), pool, tmp_path)
        campaign.report['anchors'] = [
            dict(a, receiver_index=k)
            for k in range(1, 4)
            for a in anchors(offset=k * 100000, drift=k * 10e-6)
        ]
        campaign.run(1000, 2000000, [34] * 4)
    saved = campaign.report['runs'][0]
    assert calls[0]['start_us'] == 1000000
    for k in range(1, 4):
        expected_reference = 1000000 + k * 500
        assert module.to_a(calls[k]['start_us'], saved['clock_predictions'][k]) == pytest.approx(
            expected_reference, abs=0.51
        )
        assert calls[k]['period_ns'] == round(2000000 * (1 + k * 10e-6))


def test_duplicate_receiver_object_rejected(tmp_path):
    r = object()
    with pytest.raises(ValueError):
        module.Campaign([r, r], None, None, tmp_path)
