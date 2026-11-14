"""Offline coordinator tests; fake radios never open a serial port."""

import importlib.util
import time
from pathlib import Path

import pytest


@pytest.fixture
def app(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts/dual_receiver_timing.py'
    spec = importlib.util.spec_from_file_location('dual_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    owned = []

    class FakeRadio:
        def __init__(self, port):
            self.port = port
            self.closed = False
            owned.append(self)

        def connect(self):
            if self.port == 'fail':
                raise RuntimeError('injected connection failure')
            return {'caps': ['DUALTIMING']}

        def configure(self, *args):
            # A deliberately slower second device must not get a stale start.
            if self.port == 'slow':
                time.sleep(0.02)

        def command(self, command):
            if command.startswith('TRACEARM '):
                self.deadline, self.period, self.phase = map(int, command.split()[1:])
                assert self.deadline > time.monotonic_ns() / 1000 + 100000
            return 'OK'

        def close(self):
            self.closed = True

    def pipeline(radio, **kwargs):
        return {'captures': 2, 'status': 0, 'errors': 0}, None

    def trace(radio):
        return {
            'count': 2,
            'first_trigger_device_us': radio.deadline,
            'offsets_us': [0, 1800],
            'transport_crc_valid': True,
        }

    monkeypatch.setattr(module, 'Radio', FakeRadio)
    monkeypatch.setattr(module, 'clock_probe', lambda radio, samples: {'offset_us': 0})
    monkeypatch.setattr(module, 'run_pipeline', pipeline)
    monkeypatch.setattr(module, 'read_trace', trace)
    return module, owned


def test_waits_for_both_devices_and_closes(app, tmp_path):
    module, owned = app
    result = module.run(['fast', 'slow'], tmp_path / 'results', 1800, 900)
    assert result['status'] == 'passed'
    assert len(owned) == 2 and all(r.closed for r in owned)
    assert owned[1].deadline - owned[0].deadline == 900
    assert result['mapped_nominal_union']['coverage_percent'] <= 100
    assert (tmp_path / 'results/results.json').exists()


def test_connect_failure_aborts_waiting_peer(app, tmp_path):
    module, owned = app
    result = module.run(['fail', 'slow'], tmp_path / 'failure')
    assert result['status'] == 'failed'
    assert all(r.closed for r in owned)
    assert any('connection failure' in r.get('error', '') for r in result['receivers'])


def test_same_resolved_port_rejected(app, tmp_path):
    module, owned = app
    original = tmp_path / 'device'
    original.touch()
    alias = tmp_path / 'alias'
    alias.symlink_to(original)
    with pytest.raises(ValueError, match='distinct'):
        module.run([str(original), str(alias)], tmp_path / 'unused')
    assert not owned
