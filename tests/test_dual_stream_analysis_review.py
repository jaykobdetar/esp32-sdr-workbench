"""Synthetic clock/coverage checks; these tests never access hardware."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    'nrf_campaigns.dual_stream_campaign',
    Path(__file__).resolve().parents[1] / 'scripts/dual_stream_campaign.py',
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
analyze_run, delta_at, fit_clock, to_a = (
    _module.analyze_run,
    _module.delta_at,
    _module.fit_clock,
    _module.to_a,
)


def anchors(offset=123456, drift=23.4e-6):
    origin = 1_000_000
    return [
        dict(pair=i, a_us=t, b_us=t + offset + drift * (t - origin))
        for i, t in enumerate([900000, 950000, 990000, 1020000, 1050000, 1100000])
    ]


def seal_record(record):
    import struct
    import zlib

    from sdr_research.detector_stream import MAGIC, WIRE, decode_record

    record = dict(record)
    record['trigger_us'] = round(record['trigger_us'])
    fields = [
        'sequence',
        'trigger_us',
        'mean_adc2',
        'peak_adc2',
        'background_adc2',
        'events_total',
        'flags',
        'completion_observed_us',
        'gain_register_at_completion',
    ]
    data = WIRE.pack(MAGIC, *(record.get(k, 0) for k in fields), 0)
    return decode_record(data[:-4] + struct.pack('<I', zlib.crc32(data[:-4])))


def seal_result(result):
    from sdr_research.detector_stream import END

    result['records'] = [seal_record(r) for r in result['records']]
    summary = result['summary']
    for k in ('first_trigger_us', 'last_trigger_us', 'end_us'):
        summary[k] = round(summary[k])
    result['terminal'] = seal_record(
        dict(
            sequence=summary['processed'],
            trigger_us=summary['end_us'],
            flags=END,
            events_total=summary['events'],
            mean_adc2=summary['status'],
            peak_adc2=summary['max_late_us'],
            background_adc2=summary['skipped'],
        )
    )
    return result


def row():
    model = fit_clock(anchors())
    receivers = []
    for side in range(2):
        times = [1_000_000 + 2000 * i + 1000 * side for i in range(5)]
        records = [
            dict(
                sequence=i + 1,
                trigger_us=t + delta_at(t, model) if side else t,
                flags=0,
                events_total=0,
            )
            for i, t in enumerate(times)
        ]
        receivers.append(
            dict(
                transport_crc_valid=True,
                records=records,
                summary=dict(
                    status=0,
                    captures=5,
                    processed=5,
                    events=0,
                    overflow=0,
                    first_trigger_us=records[0]['trigger_us'],
                    last_trigger_us=records[-1]['trigger_us'],
                    end_us=records[-1]['trigger_us'] + 2000,
                    skipped=0,
                    max_late_us=0,
                ),
            )
        )
    return dict(
        scheduled_a_us=1_000_000, duration_ms=10, receivers=[seal_result(r) for r in receivers]
    )


def test_clock_inverse_and_drift_over_large_uptime():
    values = anchors()
    model = fit_clock(values)
    assert model['relative_drift'] == pytest.approx(23.4e-6, abs=1e-12)
    for a in [0, 1_000_000, 1e10]:
        assert to_a(a + delta_at(a, model), model) == pytest.approx(a, abs=1e-5)
    assert model['max_residual_us'] < 1e-7


def test_fixed_requested_window_not_observed_envelope():
    data = row()
    data['receivers'][0]['records'] = data['receivers'][0]['records'][1:]
    data['receivers'][0]['summary'].update(captures=4, processed=4)
    for i, r in enumerate(data['receivers'][0]['records']):
        r['sequence'] = i + 1
    data['receivers'][0]['summary']['first_trigger_us'] = data['receivers'][0]['records'][0][
        'trigger_us'
    ]
    seal_result(data['receivers'][0])
    result = analyze_run(data, anchors())
    assert result['status'] == 'verified-telemetry'
    assert result['nominal_union']['coverage_percent'] == pytest.approx(90, abs=0.01)
    assert result['nominal_union']['max_gap_us'] == pytest.approx(1000, abs=0.5)


def test_complete_staggered_union_and_no_warmup_decisions():
    result = analyze_run(row(), anchors())
    assert result['nominal_union']['coverage_percent'] == pytest.approx(100)
    assert result['nominal_decision_union']['coverage_percent'] == 0


@pytest.mark.parametrize('subset', [slice(0, 3), slice(3, None)])
def test_missing_bracket_is_unverified(subset):
    assert analyze_run(row(), anchors()[subset])['status'] == 'unverified'


@pytest.mark.parametrize('fault', ['status', 'crc'])
def test_failed_receiver_is_unverified(fault):
    data = row()
    if fault == 'status':
        data['receivers'][1]['summary']['status'] = 3
    else:
        data['receivers'][1]['transport_crc_valid'] = False
    assert analyze_run(data, anchors())['status'] == 'unverified'


def test_fit_rejects_insufficient_or_coincident_anchors():
    with pytest.raises(ValueError):
        fit_clock(anchors()[:2])
    with pytest.raises(ValueError):
        fit_clock([dict(a_us=1, b_us=2)] * 3)


@pytest.mark.parametrize(
    'fault',
    [
        'missing_receiver',
        'extra_receiver',
        'drop',
        'sequence',
        'timestamp',
        'events',
        'flags',
        'last',
        'overflow',
        'end',
    ],
)
def test_corrupted_saved_evidence_is_unverified(fault):
    data = row()
    result = data['receivers'][0]
    if fault == 'missing_receiver':
        data['receivers'].pop()
    elif fault == 'extra_receiver':
        data['receivers'].append(result)
    elif fault == 'drop':
        result['records'].pop()
    elif fault == 'sequence':
        result['records'][1]['sequence'] = 9
    elif fault == 'timestamp':
        result['records'][1]['trigger_us'] = result['records'][0]['trigger_us']
    elif fault == 'events':
        result['records'][1]['events_total'] = 1
    elif fault == 'flags':
        result['records'][1]['flags'] = 2
    elif fault == 'last':
        result['summary']['last_trigger_us'] += 1
    elif fault == 'overflow':
        result['summary']['overflow'] = 1
    elif fault == 'end':
        result['summary']['end_us'] = 0
    assert analyze_run(data, anchors())['status'] == 'unverified'


@pytest.mark.parametrize('fault', ['nan', 'drift', 'outlier'])
def test_bad_clock_fit_is_unverified(fault):
    values = anchors(drift=0.002 if fault == 'drift' else 23.4e-6)
    if fault == 'nan':
        values[1]['b_us'] = float('nan')
    elif fault == 'outlier':
        values[1]['b_us'] += 500
    assert analyze_run(row(), values)['status'] == 'unverified'


def test_unsorted_anchors_produce_same_result():
    assert analyze_run(row(), list(reversed(anchors()))) == analyze_run(row(), anchors())


def test_worker_failure_signals_stop_and_joins_peer(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import Mock

    entered = Event()
    exited = Event()
    radios = [Mock(), Mock()]

    def fake_run(radio, *, stop, **kwargs):
        if radio is radios[0]:
            assert entered.wait(1)
            raise ValueError('broken first receiver')
        entered.set()
        assert stop.wait(1)
        exited.set()
        return {}

    monkeypatch.setattr(_module, 'run_stream', fake_run)
    monkeypatch.setattr(_module, 'clock_probe', lambda radio: {'offset_us': 0})
    with ThreadPoolExecutor(2) as pool:
        campaign = _module.Campaign(radios, Mock(), pool, tmp_path)
        campaign.report['anchors'] = anchors()
        with pytest.raises(ValueError, match='broken first receiver'):
            campaign.run(30000, 1875000, [0, 0])
        assert exited.is_set()


@pytest.mark.parametrize('fault', ['payload', 'crc_missing', 'crc', 'terminal', 'terminal_missing'])
def test_original_wire_crc_recomputed_offline(fault):
    data = row()
    result = data['receivers'][0]
    if fault == 'payload':
        result['records'][1]['mean_adc2'] += 1
    elif fault == 'crc_missing':
        del result['records'][1]['wire_crc32']
    elif fault == 'crc':
        result['records'][1]['wire_crc32'] ^= 1
    elif fault == 'terminal':
        result['terminal']['gain_register_at_completion'] ^= 1
    else:
        del result['terminal']
    assert analyze_run(data, anchors())['status'] == 'unverified'


@pytest.mark.parametrize('fault', ['missing', 'same_pair', 'overlap'])
def test_independent_anchor_pairs_required(fault):
    values = anchors()
    if fault == 'missing':
        del values[0]['pair']
    elif fault == 'same_pair':
        for a in values[:3]:
            a['pair'] = 0
    else:
        values[3]['pair'] = values[0]['pair']
    assert analyze_run(row(), values)['status'] == 'unverified'


def test_assumption_based_sensitivity_and_evaluated_folds():
    result = analyze_run(row(), anchors())
    assert result['clock_model']['heldout_evaluated_fold_count'] == 6
    assert result['clock_model']['before_capture_pair_count'] == 3
    assert result['clock_model']['after_capture_pair_count'] == 3
    nominal = result['nominal_union']['coverage_percent']
    previous = nominal
    for scenario in result['sensitivity']:
        error = scenario['assumed_endpoint_error_us']
        assert set(scenario['receiver_b_offset_scenarios']) == {str(-error), str(error)}
        eroded = scenario['eroded_union']['coverage_percent']
        assert eroded <= previous
        previous = eroded
    assert 'not confidence bounds' in result['sensitivity_note']
