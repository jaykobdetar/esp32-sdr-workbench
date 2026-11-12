"""Qt-free acquisition, atomic publication, and unattended recorder regressions."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sdr_research import acquisition, recording
from sdr_research.acquisition import AcquisitionWorker


def settings(**overrides):
    result = dict(
        mode='raw',
        frequency_mhz=2440,
        rate_hz=16_000_000,
        bandwidth_mhz=0,
        gain=40,
        bits=10,
        samples=256,
        threshold_db=10,
        autosave=True,
        record_all=True,
        scan=False,
        max_runs=2,
    )
    result.update(overrides)
    return result


def test_worker_without_qt_records_all_bursts_and_stops(tmp_path):
    worker = AcquisitionWorker('SIMULATED', settings(), tmp_path, demo=True)
    worker.start()
    assert worker.wait(3000)
    assert worker.error is None
    assert worker.capture_count == 2
    assert len(list(tmp_path.glob('*.sigmf-meta'))) == 2
    assert not worker.isRunning()


def test_atomic_json_reader_sees_only_complete_final_document(tmp_path, monkeypatch):
    path = tmp_path / 'summary.json'
    original = recording.os.replace
    seen = []

    def inspect_replace(source, target):
        assert not path.exists()
        document = json.loads(Path(source).read_text())
        assert document['retained_sigmf'] == 'capture.sigmf-meta'
        seen.append(document)
        original(source, target)

    monkeypatch.setattr(recording.os, 'replace', inspect_replace)
    recording.atomic_write_json(path, {'retained_sigmf': 'capture.sigmf-meta'})
    assert json.loads(path.read_text()) == seen[0]
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_failure_preserves_previous_document_and_removes_temp(tmp_path, monkeypatch):
    path = tmp_path / 'summary.json'
    path.write_text('{"old": true}')

    def fail_replace(*args):
        raise OSError('disk full')

    monkeypatch.setattr(recording.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='disk full'):
        recording.atomic_write_json(path, {'new': True})
    assert json.loads(path.read_text()) == {'old': True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('fail_save', [False, True])
def test_detector_summary_not_visible_until_recording_finishes(tmp_path, monkeypatch, fail_save):
    worker = AcquisitionWorker('fake', settings(mode='DET1', det_ms=1, ratio_milli=4000), tmp_path)
    worker.started_ns = time.monotonic_ns()
    capture = worker.demo_capture(2440)
    summary = dict(
        captures=20,
        detections=1,
        sample_rate_hz=16_000_000,
        total_samples=5120,
        analyzed_samples=5120,
        warmup_captures=16,
        status=0,
    )
    monkeypatch.setattr(acquisition, 'select_acquisition_policy', lambda *args: {})
    monkeypatch.setattr(acquisition, 'run_detection', lambda *args, **kwargs: (summary, capture))
    save = recording.save_capture

    def save_and_check(capture, base):
        assert not list(tmp_path.glob('*.det1.json'))
        if fail_save:
            raise OSError('capture disk full')
        return save(capture, base)

    monkeypatch.setattr(acquisition, 'save_capture', save_and_check)
    if fail_save:
        with pytest.raises(OSError, match='capture disk full'):
            worker.detector_run(object(), 2440)
    else:
        worker.detector_run(object(), 2440)
    document = json.loads(next(tmp_path.glob('*.det1.json')).read_text())
    assert 'host_session_elapsed_through_recording_s' in document
    if fail_save:
        assert document['recording_error'] == 'capture disk full'
        assert document['retained_sigmf'] is None
    else:
        assert (tmp_path / document['retained_sigmf']).exists()
    assert not list(tmp_path.glob('.*.tmp'))


def test_cli_has_no_qt_dependency_and_records_demo(tmp_path):
    code = """
import importlib.abc, sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide6', 'pyqtgraph')):
            raise AssertionError('Headless recorder imported Qt')
sys.meta_path.insert(0, NoQt())
from sdr_research.cli import main
raise SystemExit(main(sys.argv[1:]))
"""
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            code,
            'record',
            '--demo',
            '--mode',
            'raw',
            '--runs',
            '2',
            '--output',
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.splitlines()[-1])
    assert result['runs'] == 2 and result['synthetic'] and result['ok']
    assert not result['stopped']
    assert len(list(tmp_path.glob('*.sigmf-meta'))) == 2


@pytest.mark.parametrize(
    'args',
    [
        [],
        ['--demo'],
        ['--port', '/fake', '--bits', '8'],
        ['--port', '/fake', '--runs', '0'],
        ['--port', '/fake', '--background-policy', '3'],
        ['--port', '/fake', '--mode', 'raw', '--bits', '8', '--background-policy', '1'],
    ],
)
def test_cli_rejects_unsafe_or_invalid_configuration(tmp_path, args):
    from sdr_research.cli import record

    with pytest.raises(SystemExit) as exc:
        record(['--output', str(tmp_path), *args])
    assert exc.value.code == 2


@pytest.mark.skipif(os.name != 'posix', reason='POSIX SIGTERM behavior')
def test_cli_sigterm_finishes_recording_and_exits(tmp_path):
    process = subprocess.Popen(
        [
            sys.executable,
            '-m',
            'sdr_research.cli',
            'record',
            '--demo',
            '--mode',
            'raw',
            '--output',
            str(tmp_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 8
        while not list(tmp_path.glob('*.sigmf-meta')) and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.03)
        assert list(tmp_path.glob('*.sigmf-meta'))
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert json.loads(stdout.splitlines()[-1])['stopped']
        for path in tmp_path.glob('*.sigmf-meta'):
            assert recording.load_capture(path).crc_ok
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize('fail_index', [None, 1])
def test_multi_candidate_recorder_saves_crops_and_preserves_trigger_metadata(
    tmp_path, monkeypatch, fail_index
):
    from types import SimpleNamespace

    worker = AcquisitionWorker(
        'fake', settings(mode='DETPIPE1', candidate_count=3, det_ms=1, ratio_milli=4000), tmp_path
    )
    worker.started_ns = time.monotonic_ns()
    captures = [worker.demo_capture(2440) for _ in range(3)]
    for i, capture in enumerate(captures):
        capture.metadata['trigger_device_us'] = 1234 + i
        capture.metadata['crop_offset_samples'] = 128
    summary = dict(
        captures=20,
        detections=3,
        sample_rate_hz=16_000_000,
        total_samples=5120,
        analyzed_samples=5120,
        warmup_captures=16,
        status=0,
        first_trigger_device_us=1000,
        gain_register_start=42,
        gain_register_end=43,
    )
    monkeypatch.setattr(
        acquisition, 'run_pipeline_candidates', lambda *args, **kwargs: (summary, captures)
    )
    save = recording.save_capture
    saved_count = 0

    def save_or_fail(capture, base):
        nonlocal saved_count
        assert not list(tmp_path.glob('*.detpipe1.json'))
        if saved_count == fail_index:
            raise OSError('second crop disk full')
        saved_count += 1
        return save(capture, base)

    monkeypatch.setattr(acquisition, 'save_capture', save_or_fail)
    radio = SimpleNamespace(info={'caps': ['PIPEKEEP']})
    if fail_index is None:
        worker.detector_run(radio, 2440)
    else:
        with pytest.raises(OSError, match='second crop disk full'):
            worker.detector_run(radio, 2440)
    doc = json.loads(next(tmp_path.glob('*.detpipe1.json')).read_text())
    assert len(doc['retained_sigmf_candidates']) == (3 if fail_index is None else 1)
    assert doc['retained_sigmf'] == doc['retained_sigmf_candidates'][0]
    assert doc['recording_state'] == ('complete' if fail_index is None else 'error')
    for i, filename in enumerate(doc['retained_sigmf_candidates']):
        stored = recording.load_capture(tmp_path / filename)
        assert stored.metadata['trigger_device_us'] == 1234 + i
        assert 'device uptime' in stored.metadata['timestamp_reference']
    assert doc['gain_register_start'] == 42
    assert 'device trigger uptime' in doc['timestamp_reference']


def test_cli_error_exit_closes_radio_and_reports_failure(tmp_path, monkeypatch, capsys):
    from sdr_research.cli import record

    closed = []

    class FailingRadio:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            raise OSError('fake serial disconnected')

        def close(self):
            closed.append(True)

    monkeypatch.setattr(acquisition, 'Radio', FailingRadio)
    assert record(['--port', 'fake', '--output', str(tmp_path), '--runs', '1']) == 1
    output = capsys.readouterr()
    assert 'fake serial disconnected' in output.out
    assert not json.loads(output.out.splitlines()[-1])['ok']
    assert closed == [True]


def test_cli_duration_bounds_starting_new_runs(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            '-m',
            'sdr_research.cli',
            'record',
            '--demo',
            '--mode',
            'raw',
            '--samples',
            '256',
            '--duration-s',
            '1',
            '--output',
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout.splitlines()[-1])
    assert document['runs'] > 1 and document['ok']


@pytest.mark.parametrize('mode', ['DET1', 'DETPIPE1'])
@pytest.mark.parametrize('policy', [None, 1, 2])
def test_recorder_passes_background_policy_only_when_chosen(tmp_path, monkeypatch, mode, policy):
    chosen = {} if policy is None else {'background_policy': policy}
    worker = AcquisitionWorker(
        'fake',
        settings(mode=mode, det_ms=1, ratio_milli=4000, autosave=False, **chosen),
        tmp_path,
    )
    worker.started_ns = time.monotonic_ns()
    summary = dict(
        captures=20,
        detections=0,
        sample_rate_hz=16_000_000,
        total_samples=5120,
        analyzed_samples=5120,
        warmup_captures=16,
        status=0,
    )
    seen = []

    def run(*args, **kwargs):
        seen.append(kwargs)
        return dict(summary), None

    monkeypatch.setattr(acquisition, 'select_acquisition_policy', lambda *args: {})
    monkeypatch.setattr(acquisition, 'run_detection', run)
    monkeypatch.setattr(acquisition, 'run_pipeline', run)

    class Radio:
        info = {'caps': []}

    worker.detector_run(Radio(), 2440)
    # Unset leaves the clients' own default (the firmware default) in force.
    assert [call.get('background_policy', 'absent') for call in seen] == [
        'absent' if policy is None else policy
    ]
