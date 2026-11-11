"""No hardware: matched-gain design, readback and failure cleanup."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'gain_compare', Path(__file__).parents[1] / 'scripts/nrf_gain_compare.py'
)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class TX:
    def __init__(self):
        self.running = False
        self.completed = 0
        self.cfg = {}
        self.stops = 0

    def stop(self):
        self.running = False
        self.stops += 1
        return {'running': False}

    def status(self):
        if self.running:
            self.completed += 10
        return dict(
            self.cfg,
            running=self.running,
            completed=self.completed,
            attempted=self.completed,
            scheduled=self.completed,
        )

    def configure(self, **kw):
        self.cfg = kw
        return kw

    def start(self, **kw):
        assert 0 < kw['duration_ms'] <= 6000 and 0 < kw['count'] <= 5000
        self.running = True
        return kw


class RX:
    failed = False
    gain = 40

    def connect(self):
        return {'version': 'VERSION esp32-pipeline-optimized-v2'}

    def configure(self, frequency, rate, bandwidth, gain, bits):
        self.gain = gain

    def command(self, command):
        if command == 'GAIN?':
            return (
                f'GAIN MANUAL {self.gain} 0 79 1'
                if self.gain is not None
                else 'GAIN HARDWARE -1 0 79 0'
            )
        if command.startswith('GAIN MANUAL '):
            self.gain = int(command.split()[-1])
        if command == 'GAIN HARDWARE':
            self.gain = None
        return 'OK'


def args(tmp_path):
    artifact = tmp_path / 'synthetic.bin'
    artifact.write_bytes(b'synthetic')
    return m.parser().parse_args(
        [
            '--rx-port',
            'fake',
            '--tx-port',
            'fake',
            '--tx-serial',
            'fake',
            '--rx-artifact',
            str(artifact),
            '--output-directory',
            str(tmp_path / 'new'),
        ]
    )


def pipeline(*args, **kw):
    return {
        'status': 0,
        'errors': 0,
        'captures': 20,
        'warmup_captures': 16,
        'detections': 2,
        'total_samples': 327600,
        'wall_elapsed_us': 1000000,
    }, None


def test_matched_counterbalanced_plan(tmp_path):
    a = args(tmp_path)
    plan = m.plan(a)
    assert plan == m.plan(a) and len(plan) == 24
    for pair in range(4):
        rows = [r for r in plan if r['pair'] == pair]
        assert {(r['mode'], r['tx_on']) for r in rows} == {
            (g, on) for g in ('hardware-agc', 'manual-40', 'manual-60') for on in (False, True)
        }
    assert sum(next(r for r in plan if r['pair'] == p)['tx_on'] for p in range(4)) == 2


def test_finite_success_and_restore(tmp_path):
    a, tx, rx = args(tmp_path), TX(), RX()
    result = m.execute(a, rx, tx, pipeline=pipeline, sleep=lambda _: None)
    assert result['status'] == 'passed' and tx.running is False and rx.gain == 40
    assert len(result['runs']) == 24 and result['geometry_measured'] is False
    assert result['comparison']['hardware-agc']['paired_excess_per_second'] == [0] * 4
    assert (
        json.loads((a.output_directory / 'results.json').read_text())['tx_final']['running']
        is False
    )


def test_receiver_error_always_stops_source(tmp_path):
    a, tx = args(tmp_path), TX()

    def fail(*args, **kw):
        raise RuntimeError('test failure')

    with pytest.raises(RuntimeError, match='test failure'):
        m.execute(a, RX(), tx, pipeline=fail, sleep=lambda _: None)
    result = json.loads((a.output_directory / 'results.json').read_text())
    assert result['status'] == 'failed' and tx.running is False


def test_mismatched_gain_and_source_rejected():
    with pytest.raises(RuntimeError, match='Gain readback'):
        m.check_gain('GAIN MANUAL 60 0 79 1', 40)
    tx = TX()
    with pytest.raises(RuntimeError, match='running-state'):
        m.checked_status(tx, True)


def test_existing_output_not_overwritten(tmp_path):
    a = args(tmp_path)
    a.output_directory.mkdir()
    sentinel = a.output_directory / 'results.json'
    sentinel.write_text('original')
    with pytest.raises(FileExistsError):
        m.execute(a, RX(), TX())
    assert sentinel.read_text() == 'original'


def test_wrong_firmware_does_not_transmit(tmp_path):
    class WrongReceiver(RX):
        def connect(self):
            return {'version': 'some other firmware'}

    a, tx = args(tmp_path), TX()
    with pytest.raises(RuntimeError, match='Expected unchanged'):
        m.execute(a, WrongReceiver(), tx, sleep=lambda _: None)
    assert not tx.running and not tx.cfg
    assert json.loads((a.output_directory / 'results.json').read_text())['status'] == 'failed'


def test_no_transmitter_progress_rejected(tmp_path):
    class Stalled(TX):
        def status(self):
            return dict(self.cfg, running=self.running, completed=0, attempted=0, scheduled=0)

    a, tx = args(tmp_path), Stalled()
    with pytest.raises(RuntimeError, match='completed-counter'):
        m.execute(a, RX(), tx, pipeline=pipeline, sleep=lambda _: None)
    assert not tx.running


def test_cleanup_failure_is_not_success(tmp_path):
    class RestoreFails(RX):
        def command(self, command):
            if command == 'GAIN MANUAL 40':
                raise RuntimeError('restoration unavailable')
            return super().command(command)

    a, tx = args(tmp_path), TX()
    result = m.execute(a, RestoreFails(), tx, pipeline=pipeline, sleep=lambda _: None)
    assert result['status'] == 'failed'
    assert 'restoration unavailable' in result['receiver_cleanup_error']
    assert not tx.running


def test_exact_block_sign_flips():
    from nrf_campaigns.nrf_gain_analysis import exact_sign_flip

    assert exact_sign_flip([1, 1, 1, 1])['two_sided_p'] == 0.125
    assert exact_sign_flip([0, 0, 0, 0])['two_sided_p'] == 1
    assert exact_sign_flip([1, -1, 1, -1])['two_sided_p'] == 1
    with pytest.raises(ValueError):
        exact_sign_flip([float('nan')])


def test_published_gain_evidence_is_recomputable():
    from nrf_campaigns.nrf_gain_analysis import exact_sign_flip

    path = Path(__file__).parents[1] / 'docs/evidence/gain-comparison-20261111.json'
    data = json.loads(path.read_text())
    assert data['status'] == 'passed' and len(data['runs']) == 24
    assert data['transmitter_stopped_at_end'] and data['initial_gain_restored']
    by_key = {(r['pair'], r['mode'], r['tx_on']): r for r in data['runs']}
    for row in data['runs']:
        summary = row['receiver_summary']
        assert (
            row['candidate_rate_per_local_second']
            == summary['detections'] * 1e6 / summary['wall_elapsed_us']
        )
        assert row['retained_transport_crc_valid'] is True
        assert row['retained_iq_bytes'] == row['retained_endpoints']['samples'] * 8
    for mode, saved in data['agc_minus_manual_contrasts'].items():
        contrasts = [
            (
                by_key[p, 'hardware-agc', True]['candidate_rate_per_local_second']
                - by_key[p, 'hardware-agc', False]['candidate_rate_per_local_second']
            )
            - (
                by_key[p, mode, True]['candidate_rate_per_local_second']
                - by_key[p, mode, False]['candidate_rate_per_local_second']
            )
            for p in saved['block_ids']
        ]
        assert exact_sign_flip(contrasts)['two_sided_p'] == saved['two_sided_p'] == 0.25
