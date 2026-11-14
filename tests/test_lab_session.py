"""No device access: shared-session coordination and cleanup regressions."""

import json
import queue
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest

from sdr_research import lab_devices, lab_session
from sdr_research.lab_session import LabSession, ReceiverConfig, TransmitterConfig


class FakeWorker(threading.Thread):
    fail_after = None
    fail_ready = False

    def __init__(self, port, settings, output_dir, demo=False):
        super().__init__()
        self.error = None
        self.frames = deque(maxlen=2)
        self.notices = queue.Queue()
        self.capture_count = self.run_count = self.candidate_count = self.retained_count = 0
        self.nominal_rf_s = 0
        self.done = threading.Event()

    def run(self):
        if self.fail_ready:
            self.error = ValueError('bad receiver')
            return
        self.capture_count = self.run_count = 1
        self.frames.append(('capture', {}, {}))
        self.notices.put(('state', 'receiving'))
        if self.fail_after:
            self.done.wait(self.fail_after)
            if not self.done.is_set():
                self.error = RuntimeError('receiver lost')
        else:
            self.done.wait(5)

    def stop(self):
        self.done.set()


class FakeTX:
    instances = []
    fail_start = False
    fail_stop = False

    def __init__(self, port=None, serial_number=None):
        self.calls = []
        self.running = False
        self.closed = False
        self.__class__.instances.append(self)

    def hello(self):
        return {'ok': True, 'healthy': True}

    def status(self):
        return {
            'running': self.running,
            'frequency_mhz': 2444,
            'power_dbm': -40,
            'payload_len': 32,
            'payload_hex': '',
            'hop_list': [],
        }

    def configure(self, **settings):
        self.calls.append(('config', settings))
        return settings

    def start(self, duration_ms, count=0):
        self.calls.append(('start', duration_ms))
        if self.fail_start:
            raise TimeoutError('uncertain start')
        self.running = True
        return {'running': True}

    def stop(self):
        self.calls.append(('stop', None))
        if self.fail_stop:
            raise TimeoutError('uncertain stop')
        self.running = False
        return {'running': False}

    def close(self):
        self.closed = True


@pytest.fixture
def mocked(monkeypatch):
    import nrf_tx.rf_tx

    monkeypatch.setattr(lab_session, 'AcquisitionWorker', FakeWorker)
    monkeypatch.setattr(nrf_tx.rf_tx, 'Transmitter', FakeTX)
    FakeTX.instances = []
    monkeypatch.setattr(FakeTX, 'fail_start', False)
    monkeypatch.setattr(FakeTX, 'fail_stop', False)
    monkeypatch.setattr(FakeWorker, 'fail_ready', False)
    monkeypatch.setattr(FakeWorker, 'fail_after', None)


def configs():
    return [ReceiverConfig('RX1', '/fake/rx1'), ReceiverConfig('RX2', '/fake/rx2')], [
        TransmitterConfig('TX1', '/fake/tx', 'A' * 16)
    ]


def test_complete_multi_receiver_session(mocked, tmp_path):
    session = LabSession(*configs(), tmp_path / 'session', duration_s=0.1)
    session.start()
    session.join(3)
    assert not session.is_alive()
    assert session.state == 'complete'
    assert session.error is None
    assert len(session.workers) == 2
    assert all(not w.is_alive() for w in session.workers.values())
    tx = FakeTX.instances[0]
    assert tx.closed and not tx.running
    assert tx.calls[-1] == (
        'config',
        {
            'frequency_mhz': 2444,
            'power_dbm': -40,
            'length': 32,
            'payload_hex': 'off',
            'hop_list': 'off',
        },
    )
    document = json.loads((tmp_path / 'session/session.json').read_text())
    assert document['status'] == 'complete'
    assert document['transmitter_results']['TX1']['stop']['running'] is False


def test_receiver_failure_prevents_transmission(mocked, monkeypatch, tmp_path):
    monkeypatch.setattr(FakeWorker, 'fail_ready', True)
    session = LabSession(*configs(), tmp_path / 'session')
    session.run()
    assert session.state == 'error'
    assert not FakeTX.instances


def test_receiver_loss_stops_transmitter(mocked, monkeypatch, tmp_path):
    monkeypatch.setattr(FakeWorker, 'fail_after', 0.1)
    session = LabSession(*configs(), tmp_path / 'session', duration_s=5)
    session.run()
    assert session.state == 'error'
    assert 'receiver lost' in session.error
    assert FakeTX.instances[0].closed
    assert not FakeTX.instances[0].running


def test_uncertain_start_still_stops_and_closes(mocked, monkeypatch, tmp_path):
    monkeypatch.setattr(FakeTX, 'fail_start', True)
    session = LabSession(*configs(), tmp_path / 'session')
    session.run()
    assert session.state == 'error'
    assert ('stop', None) in FakeTX.instances[0].calls
    assert FakeTX.instances[0].closed


def test_uncertain_stop_cannot_be_success(mocked, monkeypatch, tmp_path):
    monkeypatch.setattr(FakeTX, 'fail_stop', True)
    session = LabSession(*configs(), tmp_path / 'session', duration_s=0.1)
    session.run()
    assert session.state == 'error'
    assert session.manifest['cleanup_errors']
    assert FakeTX.instances[0].closed


def test_cancel_stops_running_session(mocked, tmp_path):
    session = LabSession(*configs(), tmp_path / 'session')
    session.start()
    deadline = time.monotonic() + 2
    while session.state != 'running' and time.monotonic() < deadline:
        time.sleep(0.01)
    session.stop()
    session.join(3)
    assert session.state == 'stopped'
    assert not FakeTX.instances[0].running


def test_cancel_before_start_does_not_open_devices(mocked, tmp_path):
    session = LabSession(*configs(), tmp_path / 'session')
    session.stop()
    session.run()
    assert session.state == 'stopped'
    assert not FakeTX.instances and not session.workers


def test_duplicate_resolved_port_rejected(tmp_path):
    path = tmp_path / 'port'
    path.touch()
    alias = tmp_path / 'alias'
    alias.symlink_to(path)
    with pytest.raises(ValueError, match='physical port'):
        LabSession([ReceiverConfig('a', str(path)), ReceiverConfig('b', str(alias))], [], tmp_path)


def test_no_overwrite_existing_output(mocked, tmp_path):
    (tmp_path / 'session.json').write_text('old')
    session = LabSession(*configs(), tmp_path)
    session.run()
    assert session.state == 'error'
    assert not session.workers and not FakeTX.instances
    assert (tmp_path / 'session.json').read_text() == 'old'


def test_demo_refuses_real_transmitter(tmp_path):
    with pytest.raises(ValueError, match='Synthetic'):
        LabSession([ReceiverConfig('demo', 'SIM', demo=True)], configs()[1], tmp_path)


def test_duration_is_bounded(tmp_path):
    for duration in (0, -1, 61, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            LabSession(*configs(), tmp_path, duration_s=duration)


def test_discovery_keeps_duplicate_usb_serials_distinct(monkeypatch):
    monkeypatch.setattr(
        lab_devices.list_ports,
        'comports',
        lambda: [
            SimpleNamespace(
                device='/dev/ttyUSB0',
                vid=0x10C4,
                pid=0xEA60,
                description='CP2102',
                location='1-1',
                serial_number='0001',
            ),
            SimpleNamespace(
                device='/dev/ttyUSB1',
                vid=0x10C4,
                pid=0xEA60,
                description='CP2102',
                location='1-2',
                serial_number='0001',
            ),
            SimpleNamespace(
                device='/dev/ttyACM0',
                vid=0x2886,
                pid=0xF010,
                description='RF TX',
                location='1-3',
                serial_number='A' * 16,
            ),
        ],
    )
    devices = lab_devices.discover_devices()
    receivers = [d for d in devices if d.kind == 'receiver']
    assert len(receivers) == 2
    assert len({d.port for d in receivers}) == 2
    assert any(d.kind == 'transmitter' for d in devices)


def test_count_is_start_parameter_not_config(mocked, tmp_path, monkeypatch):
    calls = []
    original = FakeTX.start

    def start(self, duration_ms, count=0):
        calls.append(count)
        return original(self, duration_ms, count)

    monkeypatch.setattr(FakeTX, 'start', start)
    receivers, transmitters = configs()
    transmitters[0].settings['count'] = 12
    session = LabSession(receivers, transmitters, tmp_path / 'session', duration_s=0.1)
    session.run()
    assert session.state == 'complete'
    assert calls == [12]
    assert all(
        'count' not in value for kind, value in FakeTX.instances[0].calls if kind == 'config'
    )


@pytest.mark.parametrize(
    'setting',
    [
        {'frequency_mhz': 2400},
        {'count': 20001},
        {'power_dbm': 8},
        {'length': 252, 'interval_us': 1000, 'mode_mbps': 1},
        {'payload_hex': 'xyz'},
        {'hop_list': '2440 2450'},
        {'count': '0'},
    ],
)
def test_invalid_tx_config_rejected_before_devices_open(mocked, tmp_path, setting):
    receivers, transmitters = configs()
    transmitters[0].settings.update(setting)
    with pytest.raises(ValueError):
        LabSession(receivers, transmitters, tmp_path / 'session')
    assert not FakeTX.instances


def test_invalid_receiver_config_rejected_before_devices_open(mocked, tmp_path):
    receivers, transmitters = configs()
    receivers[1].settings['det_ms'] = 6000
    with pytest.raises(ValueError):
        LabSession(receivers, transmitters, tmp_path / 'session')
    assert not FakeTX.instances


def test_configuration_snapshot_not_changed_by_ui(mocked, tmp_path):
    receivers, transmitters = configs()
    session = LabSession(receivers, transmitters, tmp_path / 'session')
    transmitters[0].settings['power_dbm'] = 0
    assert session.transmitters[0].settings['power_dbm'] == -20
