import copy
import threading
import time

import pytest
from test_packet_only import fresh_source, objects, source, wire

from scripts.four_receiver_packets import configuration
from scripts.multi_packet_only_campaign import acquire, plan_check, summarize
from sdr_research.packet_only import validate_lines


def rows():
    return [
        dict(
            receiver=i,
            condition=c,
            status='verified',
            stream=validate_lines(wire(objects(c == 'ON')), 3, 10000, 16),
        )
        for c in ('OFF', 'ON')
        for i in range(2)
    ]


def test_union_common_denominator_and_cross_board_duplicates():
    result = summarize(rows(), fresh_source(), source(), configuration(0), 2)
    assert result['unique_packets'] == 1
    assert result['accepted_observations'] == 4
    assert result['duplicate_observations'] == 3
    assert result['completed_transmissions'] == 10
    assert [r['unique_packets'] for r in result['per_board']] == [1, 1]


@pytest.mark.parametrize(
    'mutation', ['missing', 'off', 'payload', 'drops', 'failed', 'bool', 'range', 'denominator']
)
def test_union_fail_closed(mutation):
    data = copy.deepcopy(rows())
    final = source()
    if mutation == 'missing':
        data.pop()
    if mutation == 'off':
        data[0]['stream']['packets'] = data[-1]['stream']['packets']
    if mutation == 'payload':
        data[-1]['stream']['packets'][0]['payload'] = '00' * 16
    if mutation == 'drops':
        data[-1]['stream']['end']['output_drops'] = 1
    if mutation == 'failed':
        data[-1]['status'] = 'failed'
    if mutation == 'bool':
        data[0]['receiver'] = False
    if mutation == 'range':
        data[0]['receiver'] = 2
    if mutation == 'denominator':
        final['completed'] = 9
    with pytest.raises(ValueError):
        summarize(data, fresh_source(), final, configuration(0), 2)


@pytest.mark.parametrize(
    'values',
    [
        (1, 128, 20000, 16, 5000, 0),
        (5, 128, 20000, 16, 5000, 0),
        (4, 128, 20000, 16, 3000, 250),
        (4, 128, 20000, 16, 5000, 251),
    ],
)
def test_plan_rejects(values):
    with pytest.raises(ValueError):
        plan_check(*values)


def test_acquisition_preserves_sibling_after_failure_and_joins(tmp_path, monkeypatch):
    import scripts.multi_packet_only_campaign as module

    completed = threading.Event()

    def reader(radio, *args, on_line):
        on_line('retained-' + str(radio))
        if radio == 0:
            raise KeyboardInterrupt('worker interruption')
        time.sleep(0.02)
        completed.set()
        return {'status': 'verified'}

    monkeypatch.setattr(module, 'collect', reader)
    result = []
    with pytest.raises(KeyboardInterrupt):
        acquire([0, 1], tmp_path, 'OFF', result, 3, 10000, 16, 0)
    assert completed.is_set()
    assert [r['status'] for r in result] == ['failed', 'collected']
    assert (tmp_path / 'off-0.wire.txt').read_text() == 'retained-0\n'
    assert (tmp_path / 'off-1.wire.txt').read_text() == 'retained-1\n'


@pytest.mark.parametrize('failure', [None, 'worker', 'stop', 'close', 'calibration'])
def test_campaign_lifecycle_and_failclosed_receipt(tmp_path, monkeypatch, failure):
    import io
    import json

    import scripts.multi_packet_only_campaign as module
    from sdr_research.packet_only import INFO

    class RX:
        def __init__(self, index):
            self.index = index
            self.serial = io.BytesIO()
            self.closed = False

        def connect(self):
            return {
                'version': 'VERSION '
                + json.dumps({'firmware_variant': 'esp32-packet-only-bounded-v1finish'}),
                'caps': ['PKTONLY'],
            }

        def command(self, command):
            return INFO

        def configure(self, *args):
            pass

        def close(self):
            self.closed = True
            if failure == 'close' and self.index == 0:
                raise KeyboardInterrupt('close interrupted')

    class TX:
        stops = 0
        started = False

        def stop(self):
            self.stops += 1
            if failure == 'stop' and self.stops == 2:
                raise KeyboardInterrupt('stop interrupted')
            return source()

        def configure(self, **kwargs):
            return source()

        def status(self):
            return source(elapsed_us=5000000)

        def start(self, **kwargs):
            self.started = True
            return fresh_source()

    finished = []

    def reader(rx, *args, on_line):
        on_line('retained')
        if failure == 'worker' and rx.index == 0:
            raise RuntimeError('receiver failed')
        time.sleep(0.01)
        finished.append(rx.index)
        return validate_lines(wire(objects(tx.started)), 3, 10000, 16)

    monkeypatch.setattr(module, 'collect', reader)
    monkeypatch.setattr(
        module,
        'calibration',
        lambda radios, *args: [{'sha256': 'a' * 64, 'bytes': 1904, 'device_us': 1} for _ in radios],
    )
    radios, tx = [RX(0), RX(1)], TX()
    if failure == 'calibration':

        def bad_final(radios, boundary):
            if boundary == 'campaign-after':
                raise RuntimeError('final calibration failed')
            return [{'sha256': 'a' * 64, 'bytes': 1904, 'device_us': 1} for _ in radios]

        monkeypatch.setattr(module, 'calibration', bad_final)
    if failure in ('worker', 'calibration'):
        with pytest.raises(RuntimeError):
            module.run(radios, tx, tmp_path, count=3, period_us=10000)
        if failure == 'worker':
            assert finished == [1]
    else:
        result = module.run(radios, tx, tmp_path, count=3, period_us=10000)
        assert result['status'] == ('passed' if failure is None else 'failed')
    report = json.loads((tmp_path / 'results.json').read_text())
    assert report['status'] == ('passed' if failure is None else 'failed')
    assert all(r.closed and r.serial.closed for r in radios)
    assert tx.stops == 2
    assert ('analysis' in report) is (failure is None)


@pytest.mark.parametrize('where', ['submit', 'wait'])
def test_coordinator_interrupt_drains_real_workers(tmp_path, monkeypatch, where):
    import concurrent.futures

    import scripts.multi_packet_only_campaign as module

    finished = threading.Event()
    started = threading.Event()

    def reader(*args, on_line):
        started.set()
        on_line('retained before coordinator interruption')
        time.sleep(0.03)
        finished.set()
        return {'status': 'verified'}

    class FutureProxy:
        interrupted = False

        def __init__(self, future):
            self.future = future

        def done(self):
            return self.future.done()

        def result(self):
            if where == 'wait' and not self.interrupted:
                self.interrupted = True
                assert started.wait(1)
                raise KeyboardInterrupt('coordinator wait interrupted')
            return self.future.result()

    class ExecutorProxy:
        def __init__(self, **kwargs):
            self.pool = concurrent.futures.ThreadPoolExecutor(**kwargs)
            self.submitted = 0

        def submit(self, *args):
            self.submitted += 1
            if where == 'submit' and self.submitted == 2:
                assert started.wait(1)
                raise KeyboardInterrupt('partial submit interrupted')
            return FutureProxy(self.pool.submit(*args))

        def shutdown(self, **kwargs):
            return self.pool.shutdown(**kwargs)

    monkeypatch.setattr(module, 'collect', reader)
    monkeypatch.setattr(module, 'ThreadPoolExecutor', ExecutorProxy)
    rows = []
    with pytest.raises(KeyboardInterrupt):
        acquire([0, 1], tmp_path, 'OFF', rows, 3, 10000, 16, 0)
    assert finished.is_set()
    assert rows[0]['status'] == 'collected'
    assert (tmp_path / 'off-0.wire.txt').exists()
    assert all(r['status'] in ('collected', 'pending') for r in rows)
