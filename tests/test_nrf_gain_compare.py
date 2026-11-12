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

    def __init__(self):
        self.settings = dict(PIPEKERNEL=0, ACQOPT=0, CLEAROPT=0, PIPECOPY=0, PIPEKEEP=1)

    def connect(self):
        return {'version': 'VERSION esp32-pipeline-optimized-v2'}

    def configure(self, frequency, rate, bandwidth, gain, bits):
        self.gain = gain

    def command(self, command):
        if command == 'DETPIPEMEM?':
            return 'DETPIPEMEM 40000 20000'
        name = command.split()[0].rstrip('?')
        if name in self.settings:
            if not command.endswith('?'):
                self.settings[name] = int(command.split()[1])
            return f'{name} {self.settings[name]}'
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


class AdaptiveRX(RX):
    def connect(self):
        return {
            'version': 'VERSION '
            + json.dumps(dict(firmware_variant=m.VARIANTS[1], revision='test-revision'))
        }


def adaptive_args(tmp_path, count=3):
    a = args(tmp_path)
    a.expected_variant = m.VARIANTS[1]
    a.expected_revision = 'test-revision'
    a.candidate_count = count
    return a


def test_defaults_still_v2_single(tmp_path):
    a = args(tmp_path)
    assert a.expected_variant == m.VARIANTS[0] and a.candidate_count == 1
    a.candidate_count = 3
    with pytest.raises(ValueError, match='explicit adaptive'):
        m.execute(a, RX(), TX())


@pytest.mark.parametrize('count', [1, 3])
@pytest.mark.parametrize('event', [False, True])
def test_adaptive_crops_and_no_event(tmp_path, count, event):
    from types import SimpleNamespace

    a, rx, tx = adaptive_args(tmp_path, count), AdaptiveRX(), TX()
    saved = []

    def run(*args, **kwargs):
        summary, _ = pipeline()
        n = count if event else 0
        summary.update(
            background_policy=2, retained_event_count=n, retained_samples=100 if n else 0
        )
        captures = [
            SimpleNamespace(crc_ok=True, metadata={'retained_candidate': {'slot': i}})
            for i in range(n)
        ]
        return summary, captures if count == 3 else (captures[0] if captures else None)

    def save(capture, prefix):
        saved.append(str(prefix))
        return prefix

    result = m.execute(a, rx, tx, pipeline=run, multiple=run, saver=save, sleep=lambda _: None)
    assert result['status'] == 'passed'
    assert len(saved) == (24 * count if event else 0) and len(saved) == len(set(saved))
    for row in result['runs']:
        assert row['retained_count'] == (count if event else 0)
        assert row['retained_transport_crc_valid'] is (True if event else None)
        assert row['heap_before'] == row['heap_cleared'] == result['heap_final']
        assert len(row['crops']) == (count if event else 0)
    assert result['selectors_restored'] == result['selectors_initial']
    assert not tx.running


def test_strict_revision_blocks_source(tmp_path):
    a, tx = adaptive_args(tmp_path), TX()
    a.expected_revision = 'different'
    with pytest.raises(RuntimeError, match='revision mismatch'):
        m.execute(a, AdaptiveRX(), tx)
    assert not tx.running and not tx.cfg


@pytest.mark.parametrize('failure', ['policy', 'crc', 'count', 'heap', 'selector', 'transport'])
def test_adaptive_failure_cleanup(tmp_path, failure):
    from types import SimpleNamespace

    a, rx, tx = adaptive_args(tmp_path), AdaptiveRX(), TX()

    def run(*args, **kwargs):
        summary, _ = pipeline()
        summary.update(
            background_policy=0 if failure == 'policy' else 2,
            retained_event_count=2 if failure == 'count' else 1,
            retained_samples=100,
        )
        if failure == 'selector':
            rx.settings['PIPEKEEP'] = 3
        if failure == 'heap':
            original = rx.command
            rx.command = lambda cmd: (
                'DETPIPEMEM 39999 19999' if cmd == 'DETPIPEMEM?' else original(cmd)
            )
        if failure == 'transport':
            rx.failed = True
            raise RuntimeError('transport failure')
        return summary, [SimpleNamespace(crc_ok=failure != 'crc', metadata={})]

    with pytest.raises(RuntimeError):
        m.execute(a, rx, tx, multiple=run, saver=lambda c, p: p, sleep=lambda _: None)
    report = json.loads((a.output_directory / 'results.json').read_text())
    assert report['status'] == 'failed' and not tx.running
    assert report['runs'][-1]['status'] == 'failed'
    assert report['tx_final']['running'] is False
    if failure in ('transport', 'heap'):
        assert 'receiver_cleanup_error' in report
    else:
        assert report['selectors_restored'] == report['selectors_initial']


def test_exact_usb_identity():
    from types import SimpleNamespace

    p = SimpleNamespace(
        device='/dev/fake',
        serial_number='exact',
        vid=1,
        pid=2,
        location='fake',
        manufacturer='fake',
        product='fake',
    )
    assert m.usb_identity('/dev/fake', 'exact', [p])['pid'] == 2
    for serial, ports in [('wrong', [p]), ('exact', []), ('exact', [p, p])]:
        with pytest.raises(RuntimeError, match='Exact USB'):
            m.usb_identity('/dev/fake', serial, ports)


def test_pending_selection_not_consumed(tmp_path):
    a, rx, tx = adaptive_args(tmp_path), AdaptiveRX(), TX()
    rx.settings['PIPEKEEP'] = 3
    commands = []
    original = rx.command

    def record(command):
        commands.append(command)
        return original(command)

    rx.command = record
    with pytest.raises(RuntimeError, match='Pending external'):
        m.execute(a, rx, tx)
    assert 'DETPIPECLEAR' not in commands
    assert rx.settings['PIPEKEEP'] == 3 and not tx.running


def test_final_stop_failure_marks_report_failed(tmp_path):
    class FinalStopFails(TX):
        def stop(self):
            # Initial stop, then before/after each of the 24 runs, then final.
            if self.stops == 49:
                raise RuntimeError('final STOP unverified')
            return super().stop()

    a = args(tmp_path)
    report = m.execute(a, RX(), FinalStopFails(), pipeline=pipeline, sleep=lambda _: None)
    assert report['status'] == 'failed'
    assert 'STOP unverified' in report['tx_cleanup_error']


def test_save_failure_still_clears_restores_and_stops(tmp_path):
    from types import SimpleNamespace

    a, rx, tx = adaptive_args(tmp_path), AdaptiveRX(), TX()

    def run(*args, **kwargs):
        summary, _ = pipeline()
        summary.update(background_policy=2, retained_samples=100, retained_event_count=1)
        return summary, [SimpleNamespace(crc_ok=True, metadata={})]

    def fail_save(*args):
        raise OSError('disk full')

    with pytest.raises(OSError, match='disk full'):
        m.execute(a, rx, tx, multiple=run, saver=fail_save, sleep=lambda _: None)
    report = json.loads((a.output_directory / 'results.json').read_text())
    assert report['status'] == 'failed' and report['heap_final'] == report['heap_baseline']
    assert report['selectors_initial'] == report['selectors_restored']
    assert not tx.running


def test_usb_identity_accepts_persistent_symlink(tmp_path):
    from types import SimpleNamespace

    target = tmp_path / 'ttyUSB0'
    target.touch()
    alias = tmp_path / 'by-id-receiver'
    alias.symlink_to(target)
    port = SimpleNamespace(
        device=str(target),
        serial_number='0001',
        vid=0x10C4,
        pid=0xEA60,
        location='fake',
        manufacturer='fake',
        product='fake',
    )
    identity = m.usb_identity(str(alias), '0001', [port])
    assert identity['device'] == str(target)
    assert identity['vid'] == 0x10C4 and identity['pid'] == 0xEA60
    for serial, ports in [('wrong', [port]), ('0001', [port, port])]:
        with pytest.raises(RuntimeError, match='Exact USB'):
            m.usb_identity(str(alias), serial, ports)
    port.vid = None
    with pytest.raises(RuntimeError, match='Exact USB'):
        m.usb_identity(str(alias), '0001', [port])


def test_main_rejects_same_device_alias_before_serial_open(tmp_path, monkeypatch):
    target = tmp_path / 'ttyUSB0'
    target.touch()
    alias = tmp_path / 'by-id-receiver'
    alias.symlink_to(target)
    a = args(tmp_path)
    a.rx_port, a.tx_port, a.rx_serial = str(alias), str(target), '0001'
    monkeypatch.setattr(argparse_parser := m.parser(), 'parse_args', lambda: a)
    monkeypatch.setattr(m, 'parser', lambda: argparse_parser)

    def forbid_open(*args, **kwargs):
        raise AssertionError('Radio must not open for device aliases')

    monkeypatch.setattr(m, 'Radio', forbid_open)
    with pytest.raises(ValueError, match='distinct USB devices'):
        m.main()


@pytest.mark.parametrize('variant', m.CALIBRATION_VARIANTS)
@pytest.mark.parametrize('missing', [False, True])
def test_calibration_boundary_logging_and_preflight(tmp_path, missing, variant):
    class CurrentRX(AdaptiveRX):
        def connect(self):
            info = super().connect()
            info['version'] = 'VERSION ' + json.dumps(
                dict(firmware_variant=variant, revision='test-revision')
            )
            info['caps'] = [] if missing else ['CALHASH']
            return info

        def command(self, cmd):
            if cmd == 'CALHASH?':
                assert tx.running is False
                return 'CALHASH ' + json.dumps(
                    dict(version=1, algorithm='sha256', bytes=1904, sha256='a' * 64, device_us=100)
                )
            return super().command(cmd)

    a, tx, rx = adaptive_args(tmp_path, 1), TX(), CurrentRX()
    a.expected_variant = variant

    def run(*args, **kw):
        summary, capture = pipeline()
        summary['background_policy'] = 2
        return summary, capture

    if missing:
        with pytest.raises(RuntimeError, match='capability missing'):
            m.execute(a, rx, tx, pipeline=run, sleep=lambda _: None)
        assert not tx.running and not tx.cfg
    else:
        report = m.execute(a, rx, tx, pipeline=run, sleep=lambda _: None)
        assert report['status'] == 'passed'
        assert len(report['calibration_observations']) == 50
        assert report['calibration_observations'][0]['boundary'] == 'stage_start'
        assert report['calibration_observations'][-1]['boundary'] == 'stage_end'
