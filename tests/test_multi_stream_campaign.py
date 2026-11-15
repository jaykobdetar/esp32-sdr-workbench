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
        info = {'caps': ['CALHASH']}

        def command(self, command):
            return calibration_reply()

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


def calibration_reply(digest='a', device_us=1):
    import json

    return 'CALHASH ' + json.dumps(
        dict(version=1, algorithm='sha256', bytes=1904, device_us=device_us, sha256=digest * 64)
    )


class FakeRadio:
    info = {'caps': ['CALHASH']}
    failed = False

    def __init__(self, *, close_error=False):
        self.reply = calibration_reply()
        self.closed = False
        self.close_error = close_error

    def command(self, command):
        assert command == 'CALHASH?'
        return self.reply

    def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError('close fault')


class FakeTx:
    def __init__(self, *, stop_error=False, running=False):
        self.stop_error = stop_error
        self.running = running
        self.calls = 0

    def stop(self):
        self.calls += 1
        if self.stop_error:
            raise RuntimeError('STOP fault')

    def status(self):
        return {'running': self.running}


@pytest.mark.parametrize('fault', ['changed', 'clock_reset', 'malformed', 'unsupported'])
def test_calibration_fails_closed_per_receiver(tmp_path, fault):
    radios = [FakeRadio() for _ in range(4)]
    campaign = module.Campaign(radios, FakeTx(), None, tmp_path)
    campaign.check_calibration('before')
    if fault == 'unsupported':
        radios[3].info = {'caps': []}
    else:
        radios[3].reply = {
            'changed': calibration_reply('b'),
            'clock_reset': calibration_reply(device_us=0),
            'malformed': 'CALHASH invalid',
        }[fault]
    with pytest.raises(RuntimeError, match='Receiver 3'):
        campaign.check_calibration('after')
    assert len(campaign.report['calibration_by_receiver'][0]['calibration_observations']) == 2


def test_cleanup_attempts_all_ports_and_does_not_pass_on_stop_failure(tmp_path):
    radios = [FakeRadio(close_error=i == 0) for i in range(4)]
    campaign = module.Campaign(radios, FakeTx(stop_error=True), None, tmp_path)
    campaign.check_calibration('before')
    campaign.report['status'] = 'validated'
    errors = campaign.cleanup()
    assert all(r.closed for r in radios)
    assert len(errors) == 2
    assert campaign.report['status'] == 'failed'
    assert campaign.report['tx_final'] == {'running': False}


def test_cleanup_rejects_transmitter_still_running(tmp_path):
    campaign = module.Campaign([FakeRadio(), FakeRadio()], FakeTx(running=True), None, tmp_path)
    campaign.report['status'] = 'validated'
    assert campaign.cleanup()
    assert campaign.report['status'] == 'failed'


def test_cleanup_success_required_for_pass_and_does_not_erase_primary_failure(tmp_path):
    campaign = module.Campaign([FakeRadio(), FakeRadio()], FakeTx(), None, tmp_path)
    campaign.report['status'] = 'validated'
    assert campaign.cleanup() == []
    assert campaign.report['status'] == 'passed'
    campaign.report['status'] = 'failed'
    assert campaign.cleanup() == []
    assert campaign.report['status'] == 'failed'


def test_anchor_stop_failure_still_drains_every_reader(monkeypatch, tmp_path):
    class Tx(FakeTx):
        def stop(self):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError('STOP fault')

        def start(self, **kwargs):
            pass

    class Future:
        calls = 0

        def result(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('raw failure')

    class Pool:
        def __init__(self):
            self.futures = []

        def map(self, fn, radios):
            return [{'offset_us': 0} for _ in radios]

        def submit(self, *args):
            f = Future()
            self.futures.append(f)
            return f

    pool = Pool()
    campaign = module.Campaign([FakeRadio() for _ in range(4)], Tx(), pool, tmp_path)
    with pytest.raises(RuntimeError, match='STOP fault'):
        campaign.anchors(attempts=1)
    # First reader failed in the result loop; all four were awaited in cleanup.
    assert [f.calls for f in pool.futures] == [2, 1, 1, 1]


def test_distinct_board_calibrations_are_not_compared_to_each_other(tmp_path):
    radios = [FakeRadio() for _ in range(4)]
    for k, radio in enumerate(radios):
        radio.reply = calibration_reply('abcd'[k])
    campaign = module.Campaign(radios, FakeTx(), None, tmp_path)
    before = campaign.check_calibration('before')
    for k, radio in enumerate(radios):
        radio.reply = calibration_reply('abcd'[k], device_us=10)
    after = campaign.check_calibration('after')
    assert [r['sha256'] for r in before] == [r['sha256'] for r in after]
    assert all(r['device_us'] == 10 for r in after)
