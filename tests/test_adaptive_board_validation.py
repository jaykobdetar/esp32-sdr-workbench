"""Failure-oriented checks for passive validation, without hardware."""

import json
from types import SimpleNamespace

import pytest

from scripts import adaptive_board_validation as m


class TX:
    def __init__(self):
        self.stops = 0
        self.completed = 0

    def stop(self):
        self.stops += 1

    def status(self):
        return dict(
            running=False,
            scheduled=self.completed,
            attempted=self.completed,
            completed=self.completed,
        )


class RX:
    failed = False

    def __init__(self):
        self.run_id = 0
        self.gain = None
        self.selectors = dict(PIPEKEEP=1, PIPEKERNEL=0, ACQOPT=0, CLEAROPT=0, PIPECOPY=0)
        self.commands = []
        self.bad_health = {}
        self.leak = False

    def connect(self):
        return dict(
            version='VERSION ' + json.dumps(dict(revision='test', firmware_variant=m.VARIANT)),
            caps=['PIPEKEEP', 'CALHASH'],
            transport='TRANSPORT UART 1000000',
        )

    def configure(self, frequency, rate, bandwidth, gain, bits):
        self.gain = gain

    def command(self, cmd):
        self.commands.append(cmd)
        if cmd == 'CALHASH?':
            return 'CALHASH ' + json.dumps(
                dict(
                    version=1,
                    algorithm='sha256',
                    bytes=1904,
                    sha256='a' * 64,
                    device_us=100 + self.run_id,
                )
            )
        if cmd == 'VERSION?':
            return self.connect()['version']
        if cmd == 'GAIN?':
            return (
                f'GAIN MANUAL {self.gain} 0 81 1'
                if self.gain is not None
                else 'GAIN HARDWARE -1 0 81 0'
            )
        if cmd == 'GAIN HARDWARE':
            self.gain = None
            return 'OK'
        if cmd.startswith('GAIN MANUAL '):
            self.gain = int(cmd.split()[-1])
            return 'OK'
        if cmd == 'DETPIPECLEAR':
            return 'OK'
        if cmd == 'DETPIPEMEM?':
            return 'DETPIPEMEM 99000 60000' if self.leak else 'DETPIPEMEM 100000 60000'
        if cmd == 'DETPIPEHEALTH?':
            return 'DETPIPEHEALTH ' + json.dumps(
                dict(
                    version=1,
                    enabled=True,
                    run_valid=True,
                    run_id=self.run_id,
                    monitor_start_error=0,
                    monitor_stop_error=0,
                    run_min_bytes=20000,
                    stack_after_bytes=3000,
                    **self.bad_health,
                )
            )
        name = cmd.rstrip('?').split()[0]
        if name in self.selectors:
            if not cmd.endswith('?'):
                self.selectors[name] = int(cmd.split()[1])
            return f'{name} {self.selectors[name]}'
        raise AssertionError(cmd)


def args(tmp_path):
    artifact = tmp_path / 'test.bin'
    artifact.write_bytes(b'fake-test-not-firmware')
    return SimpleNamespace(
        stage='medium',
        min_stack_bytes=2048,
        min_heap_bytes=8192,
        rx_artifact=artifact,
        expected_revision='test',
        output_directory=tmp_path / 'out',
    )


def pipeline(rx, **kwargs):
    rx.run_id += 1
    return dict(background_policy=2, status=0, errors=0, pack_failed=0), None


def multiple(rx, **kwargs):
    summary, _ = pipeline(rx, **kwargs)
    return summary, []


def test_finite_plans_cover_retention_lengths_rates_kernels_copies():
    assert len(m.plan('short')) == 10
    rows = m.plan('boundary')
    assert len(rows) == 216
    assert len({tuple(r.values()) for r in rows}) == 216
    assert len(m.plan('medium')) == 40
    assert sum(r['milliseconds'] for r in m.plan('soak')) == 1800000
    for row in rows + m.plan('soak'):
        assert 1 <= row['milliseconds'] <= 5000
        assert row['candidate_count'] in (1, 3)


def test_passed_completion_and_cleanup(tmp_path):
    a, rx, tx = args(tmp_path), RX(), TX()
    report = m.execute(a, rx, tx, single=pipeline, multiple=multiple)
    assert report['status'] == 'passed'
    assert len(report['calibration_observations']) == 82
    assert report['calibration_observations'][-1]['boundary'] == 'stage_end'
    assert report['completed_runs'] == report['planned_runs'] == 40
    assert tx.stops == 2 and rx.gain is None
    assert rx.selectors == dict(PIPEKEEP=1, PIPEKERNEL=0, ACQOPT=0, CLEAROPT=0, PIPECOPY=0)
    assert json.loads((a.output_directory / 'results.json').read_text())['status'] == 'passed'


@pytest.mark.parametrize('failure', ['crc', 'leak', 'stale', 'keyboard'])
def test_failed_run_persisted_and_source_stopped(tmp_path, failure):
    a, rx, tx = args(tmp_path), RX(), TX()

    def fail(r, **kw):
        if failure == 'crc':
            r.failed = True
            raise RuntimeError('CRC error')
        if failure == 'keyboard':
            raise KeyboardInterrupt()
        result = pipeline(r, **kw)
        if failure == 'leak':
            r.leak = True
        else:
            r.run_id = 0
        return result

    with pytest.raises((RuntimeError, KeyboardInterrupt)):
        m.execute(a, rx, tx, single=fail, multiple=multiple)
    report = json.loads((a.output_directory / 'results.json').read_text())
    assert report['status'] == report['runs'][0]['status'] == 'failed'
    assert report['completed_runs'] == 0 and tx.stops == 2
    if failure == 'crc':
        assert 'Framing uncertain' in report['receiver_cleanup_error']


@pytest.mark.parametrize(
    'field,value',
    [
        ('run_min_bytes', 8191),
        ('stack_after_bytes', 2047),
        ('run_valid', False),
        ('monitor_start_error', 1),
        ('run_id', True),
        ('run_id', 0),
    ],
)
def test_health_rejects_invalid_margin_or_telemetry(field, value):
    obj = dict(
        run_valid=True,
        run_id=1,
        monitor_start_error=0,
        monitor_stop_error=0,
        run_min_bytes=8192,
        stack_after_bytes=2048,
    )
    obj[field] = value
    with pytest.raises(RuntimeError):
        m.check_health(obj, SimpleNamespace(min_stack_bytes=2048, min_heap_bytes=8192), 0)


def test_existing_output_not_overwritten(tmp_path):
    a = args(tmp_path)
    a.output_directory.mkdir()
    tx = TX()
    with pytest.raises(FileExistsError):
        m.execute(a, RX(), tx)
    assert not tx.stops
