"""Fake-only direct raw capture controls, restoration and fail-closed checks."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sdr_research.protocol import Capture

SCRIPT_DIR = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location('raw_controls', SCRIPT_DIR / 'nrf_raw_controls.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
sys.path.pop(0)


class TX:
    def __init__(self):
        self.cfg = m.configuration(SimpleNamespace(power_dbm=-20, seed=123))
        self.cfg.update(frequency_mhz=2420, payload_hex='aabb', hop_list='2420,2430')
        self.running = False
        self.completed = 0
        self.starts = []
        self.stops = 0
        self.progress = True
        self.off_progress = False

    def stop(self):
        self.running = False
        self.stops += 1
        return self.status()

    def configure(self, **kwargs):
        self.cfg = kwargs
        return self.status()

    def status(self):
        if self.progress and (self.running or self.off_progress):
            self.completed += 10
        cfg = {k: m.canonical(k, v) for k, v in self.cfg.items()}
        return dict(
            cfg,
            running=self.running,
            healthy=True,
            errors=0,
            active_frequency_mhz=self.cfg['frequency_mhz'],
            completed=self.completed,
            scheduled=self.completed,
            attempted=self.completed,
        )

    def start(self, **kwargs):
        self.starts.append(kwargs)
        self.running = True
        self.completed = 0
        return kwargs


class RX:
    failed = False

    def __init__(self):
        self.gain = 40
        self.selectors = dict(PIPEKERNEL=0, ACQOPT=0, CLEAROPT=0, PIPECOPY=0, PIPEKEEP=1)
        self.commands = []
        self.frequency = 2412
        self.crc_ok = True
        self.variant = m.VARIANTS[1]
        self.capture_failure = False

    def connect(self):
        return {
            'version': 'VERSION ' + json.dumps(dict(firmware_variant=self.variant, revision='abc'))
        }

    def configure(self, frequency, rate, bandwidth, gain, bits):
        self.frequency, self.gain = frequency, gain
        self.rate, self.bandwidth, self.bits = rate, bandwidth, bits

    def command(self, command):
        self.commands.append(command)
        name = command.split()[0].rstrip('?')
        if name in self.selectors:
            if not command.endswith('?'):
                self.selectors[name] = int(command.split()[1])
            return f'{name} {self.selectors[name]}'
        if command.startswith('GAIN MANUAL '):
            self.gain = int(command.split()[-1])
        if command == 'GAIN HARDWARE':
            self.gain = None
        if command == 'GAIN?':
            return (
                f'GAIN MANUAL {self.gain} 0 79 1'
                if self.gain is not None
                else 'GAIN HARDWARE -1 0 79 0'
            )
        return 'OK'

    def capture(self, samples):
        if self.capture_failure:
            self.failed = True
            raise RuntimeError('Simulated transport failure')
        return Capture(
            np.zeros(samples, dtype=np.complex64),
            self.rate,
            self.frequency * 1000000,
            '2026-11-11T00:00:00Z',
            0,
            10000000,
            1024,
            self.bits,
            self.crc_ok,
        )


def args(tmp_path):
    artifact = tmp_path / 'test.bin'
    artifact.write_bytes(b'fake reference')
    return m.parser().parse_args(
        [
            '--rx-port',
            '/fake/rx',
            '--rx-serial',
            'rx123',
            '--tx-port',
            '/fake/tx',
            '--tx-serial',
            'tx123',
            '--rx-artifact',
            str(artifact),
            '--output-directory',
            str(tmp_path / 'private'),
            '--expected-variant',
            m.VARIANTS[1],
            '--expected-revision',
            'abc',
        ]
    )


def run(a, rx=None, tx=None):
    return m.execute(a, rx or RX(), tx or TX(), sleep=lambda _: None)


def result(a):
    return json.loads((a.output_directory / 'results.json').read_text())


def test_plan_counterbalanced(tmp_path):
    a = args(tmp_path)
    rows = m.plan(a)
    assert rows == m.plan(a) and len(rows) == 12
    first = []
    for pair in range(4):
        matched = [r for r in rows if r['pair'] == pair and r['kind'] == 'matched']
        assert {r['tx_on'] for r in matched} == {True, False}
        first.append(matched[0]['tx_on'])
    assert sum(first) == 2
    assert len([r for r in rows if r['rx_frequency_mhz'] == 2470 and r['tx_on']]) == 4


@pytest.mark.parametrize('gain', [40, None])
def test_real_saver_success_and_restoration(tmp_path, gain):
    a, rx, tx = args(tmp_path), RX(), TX()
    rx.gain = gain
    original = tx.cfg.copy()
    r = run(a, rx, tx)
    assert r['status'] == 'passed' and not tx.running
    assert rx.gain == gain and rx.frequency == 2440 and rx.bandwidth == 12
    assert tx.cfg == original
    assert tx.starts == [dict(count=5000, duration_ms=6000)] * 8
    assert tx.stops >= 26
    assert len(list(a.output_directory.glob('*.sigmf-data'))) == 12
    assert all(row['status'] == 'passed' for row in r['runs'])
    assert not any(cmd.startswith('DETPIPE') for cmd in rx.commands)
    assert rx.commands.count('PIPEKERNEL 0') == 1
    meta = json.loads(Path(r['runs'][0]['sigmf']).read_text())
    control = meta['global']['sdr_research:metadata']['raw_source_control']
    assert control['selection'] == 'unselected direct CAP20'
    assert control['source_configuration']['frequency_mhz'] == 2440
    assert len(r['runs']) == 12 and not r['cleanup_errors']


@pytest.mark.parametrize('field', m.TX_KEYS)
def test_every_source_field_read_back(tmp_path, field):
    a = args(tmp_path)
    expected = m.configuration(a)
    observed = TX().status()
    observed.update({k: m.canonical(k, v) for k, v in expected.items()})
    observed['active_frequency_mhz'] = 2440
    del observed[field]
    with pytest.raises(RuntimeError, match='configuration mismatch'):
        m.verify_config(observed, expected)


@pytest.mark.parametrize(
    'failure', ['crc', 'transport', 'no_progress', 'off_progress', 'revision', 'gain', 'save']
)
def test_failure_stops_and_records_all_rows(tmp_path, failure):
    a, rx, tx = args(tmp_path), RX(), TX()
    if failure == 'crc':
        rx.crc_ok = False
    elif failure == 'transport':
        rx.capture_failure = True
    elif failure == 'no_progress':
        tx.progress = False
    elif failure == 'off_progress':
        tx.off_progress = True
    elif failure == 'revision':
        a.expected_revision = 'wrong'
    elif failure == 'gain':
        configure = rx.configure

        def bad_gain(*values):
            configure(*values)
            rx.gain = 41

        rx.configure = bad_gain
    kwargs = {}
    if failure == 'save':

        def saver(*_):
            raise OSError('Simulated disk failure')

        kwargs['saver'] = saver
    with pytest.raises((RuntimeError, OSError)):
        m.execute(a, rx, tx, sleep=lambda _: None, **kwargs)
    r = result(a)
    assert r['status'] == 'failed' and not tx.running and len(r['runs']) == 12
    assert not any(row['status'] == 'running' for row in r['runs'])
    if failure == 'transport':
        assert r['cleanup_errors']
    else:
        assert rx.gain == 40


def test_existing_output_refused_without_device_calls(tmp_path):
    a = args(tmp_path)
    a.output_directory.mkdir()

    class NoDevice:
        def __getattr__(self, name):
            raise AssertionError('No device calls allowed')

    with pytest.raises(FileExistsError):
        run(a, NoDevice(), NoDevice())


def test_usb_canonical_identity_and_exact_serial(tmp_path):
    target = tmp_path / 'tty'
    target.touch()
    alias = tmp_path / 'alias'
    alias.symlink_to(target)
    p = SimpleNamespace(
        device=str(target),
        serial_number='exact',
        vid=1,
        pid=2,
        location='test',
        manufacturer='fake',
        product='fake',
    )
    assert m.usb_identity(str(alias), 'exact', [p])['serial_number'] == 'exact'
    with pytest.raises(RuntimeError, match='Exact USB identity'):
        m.usb_identity(str(alias), 'prefix', [p])
    with pytest.raises(RuntimeError, match='Exact USB identity'):
        m.usb_identity(str(alias), 'exact', [p, p])


def test_cleanup_failure_changes_exit_status(tmp_path):
    a, tx = args(tmp_path), TX()
    configure = tx.configure

    def reject_restore(**values):
        if values['frequency_mhz'] == 2420:
            raise RuntimeError('Restore refused')
        return configure(**values)

    tx.configure = reject_restore
    r = run(a, tx=tx)
    assert r['status'] == 'failed' and r['cleanup_errors'] and not tx.running


def test_receiver_selector_drift_is_rejected(tmp_path):
    a, rx = args(tmp_path), RX()
    original_capture = rx.capture

    def capture(samples):
        value = original_capture(samples)
        rx.selectors['ACQOPT'] = 3
        return value

    rx.capture = capture
    with pytest.raises(RuntimeError, match='selector drift'):
        run(a, rx=rx)
    assert rx.selectors['ACQOPT'] == 0
    assert result(a)['status'] == 'failed'


def test_import_does_not_open_devices(monkeypatch):
    import serial

    def forbidden(*args, **kwargs):
        raise AssertionError('Import must not access hardware')

    monkeypatch.setattr(serial, 'Serial', forbidden)
    spec = importlib.util.spec_from_file_location(
        'raw_import_test', SCRIPT_DIR / 'nrf_raw_controls.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


@pytest.mark.parametrize('seed', [0, -1, 2000000001])
def test_invalid_seed_rejected_before_io(tmp_path, seed):
    a = args(tmp_path)
    a.seed = seed
    with pytest.raises(ValueError, match='Seed'):
        m.execute(a, object(), object())
    assert not a.output_directory.exists()


@pytest.mark.parametrize('variant', m.CALIBRATION_VARIANTS)
@pytest.mark.parametrize('missing', [False, True])
def test_calibration_records_query_only_with_source_stopped(tmp_path, variant, missing):
    class CurrentRX(RX):
        def __init__(self):
            super().__init__()
            self.variant = variant

        def connect(self):
            return dict(super().connect(), caps=[] if missing else ['CALHASH'])

        def command(self, cmd):
            if cmd == 'CALHASH?':
                assert tx.running is False
                return 'CALHASH ' + json.dumps(
                    dict(version=1, algorithm='sha256', bytes=1904, sha256='b' * 64, device_us=100)
                )
            return super().command(cmd)

    a, tx, rx = args(tmp_path), TX(), CurrentRX()
    a.expected_variant = variant
    if missing:
        with pytest.raises(RuntimeError, match='capability missing'):
            m.execute(a, rx, tx, saver=lambda c, p: p, sleep=lambda _: None)
        assert not tx.running
        return
    report = m.execute(a, rx, tx, saver=lambda c, p: p, sleep=lambda _: None)
    assert report['status'] == 'passed'
    assert len(report['calibration_observations']) == 26
    assert report['calibration_observations'][-1]['boundary'] == 'stage_end'
