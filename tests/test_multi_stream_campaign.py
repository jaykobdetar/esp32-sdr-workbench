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

        def done(self):
            return self.calls >= 2

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
    with pytest.raises(RuntimeError, match='raw failure'):
        campaign.anchors(attempts=1)
    # First reader failed in the result loop; all four were awaited in cleanup.
    assert [f.calls for f in pool.futures] == [2, 2, 2, 2]
    assert (
        campaign.report['anchor_failures'][0]['cleanup_observations'][0]['stage']
        == 'transmitter-stop'
    )


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


@pytest.mark.parametrize('diagnostic_failure', [False, True])
def test_failed_campaign_persists_private_rejection_and_peer_summaries(
    monkeypatch, tmp_path, diagnostic_failure
):
    import json
    from concurrent.futures import ThreadPoolExecutor

    from sdr_research.protocol import ProtocolError

    class Radio:
        info = {'caps': ['CALHASH']}

        def __init__(self, k):
            self.port = f'/dev/mock{k}'

        def command(self, command):
            return calibration_reply()

    class Tx:
        def stop(self):
            pass

    radios = [Radio(k) for k in range(4)]
    error = ProtocolError('DSTREAM framing/CRC failure; coverage is unverified')
    error.stream_diagnostics = {'frame_hex': '00' * 48, 'expected_sequence': 3}
    finished = []

    def diagnose(radio, **kwargs):
        assert sorted(finished) == [0, 1, 2, 3]
        if diagnostic_failure:
            raise RuntimeError('injected diagnostic failure')
        return {'status': 'diagnosed-rejected-stream'}

    monkeypatch.setattr(module, 'diagnose_failed_stream', diagnose)

    def stream(r, **kwargs):
        finished.append(radios.index(r))
        if r is radios[2]:
            raise error
        return {'summary': {'captures': 2}, 'transport_crc_valid': True, 'stop_requested': False}

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
        with pytest.raises(ProtocolError) as caught:
            campaign.run(1000, 2000000, [34] * 4)
        assert caught.value is error
    assert campaign.report['runs'] == []
    rejected = campaign.report['rejected_runs'][0]
    assert rejected['status'] == 'rejected'
    cancellation = rejected['cancellation_timing']
    assert (
        cancellation['event_set_started_host_monotonic_ns']
        <= cancellation['event_set_returned_host_monotonic_ns']
    )
    assert rejected['receivers'][2]['same_descriptor_diagnostics']['status'] == (
        'diagnostic-failed' if diagnostic_failure else 'diagnosed-rejected-stream'
    )
    assert rejected['receivers'][2]['port'] == '/dev/mock2'
    assert rejected['receivers'][2]['private_stream_diagnostics'] == error.stream_diagnostics
    assert [r['status'] for r in rejected['receivers']] == [
        'completed-peer',
        'completed-peer',
        'error',
        'completed-peer',
    ]
    assert rejected['receivers'][0]['summary']['captures'] == 2
    assert module.analyze_run(rejected, campaign.report['anchors'])['status'] == 'unverified'
    saved = json.loads((tmp_path / 'results.json').read_text())
    assert saved['rejected_runs'] == campaign.report['rejected_runs']


def test_provenance_hashes_actual_sources_without_absolute_keys(tmp_path):
    import hashlib

    hashes = module.source_provenance()
    assert len(hashes) == 9
    for name, path in module._SOURCE_FILES.items():
        assert not name.startswith('/') and '..' not in name
        assert hashes[name] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
    campaign = module.Campaign([object(), object()], None, None, tmp_path)
    assert campaign.report['source_sha256'] == hashes


@pytest.mark.parametrize('enabled', [False, True])
def test_partial_submission_joins_before_gc_restore(monkeypatch, tmp_path, enabled):
    import gc
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    original_gc = gc.isenabled()
    monkeypatch.setattr(gc, 'collect', lambda: 0)
    monkeypatch.setattr(module, 'clock_probe', lambda r: {'offset_us': 0})
    started, finished = Event(), Event()
    error = RuntimeError('second submit failed')

    def worker(r, **kwargs):
        started.set()
        assert not gc.isenabled()
        assert kwargs['stop'].wait(2)
        assert not gc.isenabled()
        finished.set()
        return {'summary': {}, 'transport_crc_valid': True}

    monkeypatch.setattr(module, 'run_stream', worker)

    class Tx:
        def stop(self):
            pass

    try:
        gc.enable() if enabled else gc.disable()
        with ThreadPoolExecutor(1) as real:

            class Pool:
                calls = 0

                def submit(self, *args, **kwargs):
                    self.calls += 1
                    if self.calls == 2:
                        assert started.wait(2)
                        raise error
                    return real.submit(*args, **kwargs)

            campaign = module.Campaign(
                [object(), object()], Tx(), Pool(), tmp_path, defer_cyclic_gc=True
            )
            campaign.report['anchors'] = [dict(a, receiver_index=1) for a in anchors()]
            with pytest.raises(RuntimeError) as caught:
                campaign.run(1000, 2000000, [34, 34])
            assert caught.value is error and finished.is_set()
            assert gc.isenabled() == enabled
            assert campaign.report['cyclic_gc_policy'][0]['restored_enabled'] == enabled
    finally:
        gc.enable() if original_gc else gc.disable()


def test_default_gc_policy_does_not_collect(monkeypatch, tmp_path):
    import gc

    monkeypatch.setattr(gc, 'collect', lambda: pytest.fail('Default must not collect'))
    campaign = module.Campaign([object(), object()], None, None, tmp_path)
    monkeypatch.setattr(campaign, '_run_stream', lambda *a: 123)
    assert campaign.run(1000, 2000000, [34, 34]) == 123
    assert 'cyclic_gc_policy' not in campaign.report


@pytest.mark.parametrize('extra', [['--seconds', '121'], ['--trials', '4'], ['--phase-sweep']])
def test_gc_cli_bounds_before_hardware(monkeypatch, tmp_path, extra):
    import sys

    monkeypatch.setattr(module, 'Radio', lambda *a: pytest.fail('No hardware for invalid bounds'))
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'campaign',
            '--port',
            'mock0',
            '--port',
            'mock1',
            '--tx-serial',
            'mock',
            '--output',
            str(tmp_path / 'unused'),
            '--defer-cyclic-gc',
            '--run',
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as caught:
        module.main()
    assert caught.value.code == 2


def test_interrupted_join_waits_for_real_worker_before_restore(monkeypatch, tmp_path):
    import gc
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    monkeypatch.setattr(gc, 'collect', lambda: 0)
    monkeypatch.setattr(module, 'clock_probe', lambda r: {'offset_us': 0})
    started, release, finished = Event(), Event(), Event()
    primary = RuntimeError('submission failed')
    original_gc = gc.isenabled()

    def worker(r, **kwargs):
        started.set()
        assert release.wait(2)
        assert not gc.isenabled()
        finished.set()
        return {'summary': {}, 'transport_crc_valid': True}

    monkeypatch.setattr(module, 'run_stream', worker)

    class Tx:
        def stop(self):
            pass

    class InterruptedFuture:
        calls = 0

        def __init__(self, real):
            self.real = real

        def done(self):
            return self.real.done()

        def result(self):
            self.calls += 1
            if self.calls <= 2:
                assert not self.done()
                raise KeyboardInterrupt('additional interrupt')
            release.set()
            return self.real.result()

    with ThreadPoolExecutor(1) as executor:

        class Pool:
            calls = 0

            def submit(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    assert started.wait(2)
                    raise primary
                return InterruptedFuture(executor.submit(*args, **kwargs))

        campaign = module.Campaign(
            [object(), object()], Tx(), Pool(), tmp_path, defer_cyclic_gc=True
        )
        campaign.report['anchors'] = [dict(a, receiver_index=1) for a in anchors()]
        with pytest.raises(RuntimeError) as caught:
            campaign.run(1000, 2000000, [34, 34])
        assert caught.value is primary
        assert finished.is_set() and gc.isenabled() == original_gc
    interruptions = campaign.report['rejected_runs'][0]['join_interruptions']
    assert [x['error_type'] for x in interruptions] == ['KeyboardInterrupt'] * 2
