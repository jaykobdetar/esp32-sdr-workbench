"""Headless UI lifecycle checks; no real serial device is opened."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time

import pytest
from PySide6 import QtCore, QtWidgets

from sdr_research.gui import MainWindow
from sdr_research.recording import load_capture, save_capture


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def spin(app, predicate, timeout=4):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert predicate()


def read_summaries(app, folder, pattern, timeout=4):
    """Return every run summary in `folder` once all of them are final.

    Summaries are published atomically only after the final recording outcome is known.
    """
    import json

    end = time.monotonic() + timeout
    while True:
        try:
            docs = [json.loads(path.read_text()) for path in sorted(folder.glob(pattern))]
        except (json.JSONDecodeError, FileNotFoundError):
            docs = []
        if docs and all('host_session_elapsed_through_recording_s' in doc for doc in docs):
            return docs
        assert time.monotonic() < end, f'{len(docs)} summaries read, not all final'
        app.processEvents()
        time.sleep(0.01)


def cleanup(app, w):
    w.stop_acquisition()
    for worker in w.workers.values():
        assert worker.wait(4000)
    w.close()
    w.deleteLater()
    app.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_demo_restart_inspect_calibration_and_scan(app, tmp_path):
    w = MainWindow(demo=True)
    w.output_dir = tmp_path
    w.show()
    try:
        w.autosave.setChecked(True)
        w.start_acquisition()
        spin(app, lambda: 'SIMULATED' in w.latest and w.event_table.rowCount() > 0)
        assert 'SIMULATED' in w.status_label.text()
        assert 'ADC endpoints' in w.status_label.text()
        assert w.workers['SIMULATED'].frames.maxlen == 2
        w.calibrate_noise()
        w.redraw_selected()
        assert w.noise_baselines
        w.inspect_latest()
        app.processEvents()
        assert w.dialogs
        w.dialogs[0].accept()
        app.processEvents()
        spin(app, lambda: bool(list(tmp_path.glob('*.sigmf-meta'))))
        capture = load_capture(next(tmp_path.glob('*.sigmf-meta')))
        assert capture.metadata['synthetic'] is True
        w.stop_acquisition()
        spin(app, lambda: not w.workers['SIMULATED'].isRunning())
        w.scan.setChecked(True)
        w.scan_low.setValue(2440)
        w.scan_high.setValue(2444)
        w.scan_step.setValue(2)
        w.start_acquisition()
        spin(app, lambda: len(w.workers['SIMULATED'].occupancy_counts) == 3)
        assert set(w.workers['SIMULATED'].occupancy_counts) == {2440, 2442, 2444}
        assert not w.noise_baselines
        assert w.occupancy_image.image is not None
    finally:
        cleanup(app, w)


def test_close_while_active_is_graceful(app):
    w = MainWindow(demo=True)
    w.show()
    w.start_acquisition()
    spin(app, lambda: bool(w.latest))
    w.close()
    spin(app, lambda: not w.isVisible())
    assert not w.workers['SIMULATED'].isRunning()
    cleanup(app, w)


def test_offline_replay_and_no_transmitter_attribution(app, tmp_path):
    w = MainWindow(demo=True)
    try:
        w.start_acquisition()
        spin(app, lambda: bool(w.latest))
        w.stop_acquisition()
        spin(app, lambda: not w.workers['SIMULATED'].isRunning())
        path = save_capture(w.latest['SIMULATED'], tmp_path / 'demo')
        w.device_view.clear()
        w.device_view.addItem('Replay')
        w.replay_paths = [str(path)]
        w.replay_index = 0
        w.replay_tick()
        assert 'Offline replay' in w.status_label.text()
        assert w.latest['Replay'].metadata['synthetic']
        w.replay_tick()
        assert not w.replay_timer.isActive()
    finally:
        cleanup(app, w)


def test_independent_frequency_assignments_and_duplicate_guard(app, monkeypatch):
    import sdr_research.gui as gui

    original = gui.AcquisitionWorker

    class SyntheticWorker(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.demo = True

    monkeypatch.setattr(gui, 'AcquisitionWorker', SyntheticWorker)
    w = MainWindow()
    errors = []
    w.show_error = errors.append
    try:
        w.port.setText('/dev/test0@2440,/dev/test1@2480')
        w.start_acquisition()
        spin(app, lambda: len(w.latest) == 2)
        assert w.latest['/dev/test0'].frequency_hz == 2440e6
        assert w.latest['/dev/test1'].frequency_hz == 2480e6
        w.stop_acquisition()
        spin(app, lambda: not any(x.isRunning() for x in w.workers.values()))
        w.port.setText('/dev/test0@2440,/dev/test0@2480')
        w.start_acquisition()
        assert errors and 'only once' in errors[-1]
        assert not any(x.isRunning() for x in w.workers.values())
    finally:
        cleanup(app, w)


def test_render_ranges_contain_physical_frequency_and_image(app):
    import numpy as np

    w = MainWindow(demo=True)
    w.show()
    try:
        w.start_acquisition()
        spin(app, lambda: 'SIMULATED' in w.latest)
        app.processEvents()
        curve = w.spectrum_curve
        lo, hi = w.spectrum_plot.viewRange()[0]
        assert lo <= float(np.median(curve.xData)) <= hi
        assert hi - lo > 15
        assert w.spectrum_plot.getAxis('bottom').autoSIPrefixScale == 1
        assert w.waterfall_plot.getAxis('bottom').autoSIPrefixScale == 1
        image_rect = w.waterfall_image.mapRectToParent(w.waterfall_image.boundingRect())
        vlo, vhi = w.waterfall_plot.viewRange()[0]
        assert vlo <= image_rect.center().x() <= vhi
        assert abs(image_rect.width() - 16) < 1e-6
        assert image_rect.height() > 0
    finally:
        cleanup(app, w)


@pytest.fixture
def detector_fake(monkeypatch):
    from datetime import datetime, timezone

    import numpy as np

    import sdr_research.acquisition as acquisition
    from sdr_research.protocol import Capture

    calls = []
    state = {'retain': False, 'fail': None, 'status': 0}

    class FakeRadio:
        def __init__(self, port, baud):
            self.settings = {}
            self.info = {}
            self.failed = False
            self.closed = False

        def connect(self):
            return {'firmware': 'test only'}

        def configure(self, **kwargs):
            self.settings = kwargs

        def close(self):
            self.closed = True

    def run(radio, milliseconds, samples, rate_hz, ratio_milli, retain):
        start = time.monotonic_ns()
        time.sleep(0.04)
        calls.append((radio.settings['frequency_mhz'], milliseconds, ratio_milli))
        if state['fail']:
            raise RuntimeError(state['fail'])
        count = 20
        warmup = 16
        nanalysis = samples // 64 * 64
        summary = dict(
            version=1,
            status=state['status'],
            captures=count,
            detections=2 if state['retain'] else 0,
            sample_rate_hz=rate_hz,
            frequency_mhz=radio.settings['frequency_mhz'],
            retained_samples=samples if state['retain'] else 0,
            wall_elapsed_us=100000,
            total_samples=count * samples,
            analyzed_samples=count * nanalysis,
            warmup_captures=warmup,
            host_request_timestamp=datetime.now(timezone.utc).isoformat(),
            errors_received=[],
            errors=state['status'],
            nominal_rf_duty_percent=100 * count * samples / rate_hz / 0.1,
            nominal_analyzed_duty_percent=100 * count * nanalysis / rate_hz / 0.1,
            nominal_decision_duty_percent=100 * (count - warmup) * nanalysis / rate_hz / 0.1,
        )
        capture = None
        if state['retain']:
            iq = (0.05 * np.exp(2j * np.pi * 0.1 * np.arange(samples))).astype(np.complex64)
            capture = Capture(
                iq,
                rate_hz,
                radio.settings['frequency_mhz'] * 1000000,
                summary['host_request_timestamp'],
                start,
                time.monotonic_ns(),
                1000,
                10,
                True,
                {'detector_summary': summary, 'synthetic_test': True},
            )
        return summary, capture

    monkeypatch.setattr(acquisition, 'Radio', FakeRadio)
    monkeypatch.setattr(acquisition, 'run_detection', run)
    return state, calls


def test_det1_no_event_records_summaries_and_updates_duty_scan(app, detector_fake, tmp_path):

    state, calls = detector_fake
    w = MainWindow()
    w.output_dir = tmp_path
    w.mode.setCurrentIndex(1)
    w.det_ms.setValue(250)
    w.det_ratio.setValue(3.25)
    w.scan.setChecked(True)
    w.scan_low.setValue(2440)
    w.scan_high.setValue(2442)
    w.scan_step.setValue(2)
    w.autosave.setChecked(True)
    try:
        w.start_acquisition()
        spin(app, lambda: len(calls) >= 3 and bool(w.stats))
        assert 'local nominal RF/analyzed/post-warmup decision duty' in w.status_label.text()
        assert 'no IQ retained' in w.status_label.text()
        assert not w.latest and not w.events
        assert {x[0] for x in calls} == {2440, 2442}
        assert all(x[1:] == (250, 3250) for x in calls)
        paths = list(tmp_path.glob('*.det1.json'))
        assert paths
        # No capture is retained in this scenario, so no saturation counts are recorded.
        summaries = read_summaries(app, tmp_path, '*.det1.json')
        # No capture is retained in this scenario, so no saturation counts are recorded.
        assert all(x['retained_endpoint_counts'] is None for x in summaries)
        assert all(x['receiver_settings']['gain_mode'] == 'hardware_agc' for x in summaries)
        assert all(x['retained_sigmf'] is None for x in summaries)
        assert all(x['gui_mode'] == 'DET1' for x in summaries)
        assert all('host_session_nominal_decision_duty_percent' in x for x in summaries)
        assert not list(tmp_path.glob('*.sigmf-meta'))
        assert w.occupancy_image.image is not None
    finally:
        cleanup(app, w)


@pytest.mark.parametrize('available_port', ['/dev/test-detector', None])
def test_det1_retained_record_render_stop_restart(
    app, detector_fake, tmp_path, monkeypatch, available_port
):
    from types import SimpleNamespace

    import sdr_research.gui as gui

    # Device discovery varies across machines, including hosted CI runners.
    # Exercise both selection paths without depending on attached serial devices.
    monkeypatch.setattr(
        gui.list_ports,
        'comports',
        lambda: (
            [SimpleNamespace(device=available_port, description='Test receiver')]
            if available_port
            else []
        ),
    )

    state, calls = detector_fake
    state['retain'] = True
    w = MainWindow()
    port = w.port.text()
    assert port == (available_port or '/dev/ttyUSB0')
    w.output_dir = tmp_path
    w.mode.setCurrentIndex(1)
    w.autosave.setChecked(True)
    try:
        w.show()
        w.start_acquisition()
        spin(app, lambda: bool(w.latest) and bool(w.events))
        assert 'candidate-positive captures' in w.status_label.text()
        assert 'NOT unique packets' in w.status_label.text()
        assert 'run start, NOT event time' in w.event_table.item(0, 0).text()
        assert w.event_table.horizontalHeaderItem(6).text() == 'ADC end %'
        assert float(w.event_table.item(0, 6).text()) >= 0
        assert 'displayed capture ADC endpoints' in w.status_label.text()
        summaries = read_summaries(app, tmp_path, '*.det1.json')
        paired = [x for x in summaries if x.get('retained_sigmf')]
        assert paired
        # Every run records the requested gain mode; retained runs record saturation counts.
        assert all(x['receiver_settings']['gain_mode'] == 'hardware_agc' for x in summaries)
        assert all(x['receiver_settings']['gain_index'] is None for x in summaries)
        assert paired[0]['retained_endpoint_counts']['samples'] == w.samples.value()
        assert (tmp_path / paired[0]['retained_sigmf']).exists()
        capture = load_capture(tmp_path / paired[0]['retained_sigmf'])
        assert 'exact event time unavailable' in capture.metadata['timestamp_reference']
        assert capture.metadata['endpoint_counts'] == paired[0]['retained_endpoint_counts']
        lo, hi = w.spectrum_plot.viewRange()[0]
        assert lo < capture.frequency_hz / 1e6 < hi
        assert w.stats[port]['candidates'] == w.stats[port]['retained'] * 2
        w.stop_acquisition()
        assert 'DET1 run' in w.status_label.text()
        spin(app, lambda: not any(x.isRunning() for x in w.workers.values()))
        state['retain'] = False
        w.start_acquisition()
        spin(app, lambda: bool(w.stats) and w.stats[port]['runs'] >= 1)
        assert not w.latest
        assert 'no IQ retained' in w.status_label.text()
    finally:
        cleanup(app, w)


def test_det1_unsupported_firmware_and_demo_do_not_flash(app, detector_fake):
    state, calls = detector_fake
    state['fail'] = 'DETINFO?: ERR unknown_command'
    w = MainWindow()
    w.mode.setCurrentIndex(1)
    try:
        w.start_acquisition()
        spin(app, lambda: bool(w.worker_errors))
        assert 'nothing was flashed' in w.status_label.text()
        assert w.start_button.isEnabled()
        assert not w.latest
        state['fail'] = None
        w.demo.setChecked(True)
        count = len(calls)
        w.start_acquisition()
        spin(app, lambda: bool(w.worker_errors))
        assert len(calls) == count
        assert 'no fabricated DET1 performance' in w.status_label.text()
    finally:
        cleanup(app, w)


def test_det1_firmware_error_keeps_summary_and_stops(app, detector_fake, tmp_path):

    state, calls = detector_fake
    state['status'] = 1
    w = MainWindow()
    w.output_dir = tmp_path
    w.mode.setCurrentIndex(1)
    w.autosave.setChecked(True)
    try:
        w.start_acquisition()
        spin(app, lambda: bool(w.worker_errors))
        paths = list(tmp_path.glob('*.det1.json'))
        assert len(paths) == 1
        assert read_summaries(app, tmp_path, '*.det1.json')[0]['status'] == 1
        assert 'ended with status1' in w.status_label.text().replace('status ', 'status')
        assert not any(x.isRunning() for x in w.workers.values())
    finally:
        cleanup(app, w)


def test_det1_recording_failure_preserves_summary_and_closes(
    app, detector_fake, monkeypatch, tmp_path
):

    import sdr_research.acquisition as acquisition

    state, calls = detector_fake
    state['retain'] = True

    def fail_save(*args):
        raise OSError('simulated disk full')

    monkeypatch.setattr(acquisition, 'save_capture', fail_save)
    w = MainWindow()
    w.output_dir = tmp_path
    w.mode.setCurrentIndex(1)
    w.autosave.setChecked(True)
    try:
        w.start_acquisition()
        spin(app, lambda: bool(w.worker_errors))
        docs = read_summaries(app, tmp_path, '*.det1.json')
        assert len(docs) == 1 and docs[0]['recording_error'] == 'simulated disk full'
        assert docs[0]['retained_sigmf'] is None
        assert 'disk full' in w.status_label.text()
    finally:
        cleanup(app, w)


def test_det1_close_during_bounded_run(app, detector_fake):
    state, calls = detector_fake
    w = MainWindow()
    w.mode.setCurrentIndex(1)
    w.show()
    w.start_acquisition()
    spin(app, lambda: len(calls) > 0)
    w.close()
    spin(app, lambda: not w.isVisible())
    assert not any(worker.isRunning() for worker in w.workers.values())
    cleanup(app, w)


@pytest.mark.parametrize('retain', [False, True])
@pytest.mark.parametrize('copy_cap', [False, True])
def test_optimized_pipeline_record_render_restart(
    app, detector_fake, monkeypatch, tmp_path, retain, copy_cap
):

    import sdr_research.acquisition as acquisition

    state, calls = detector_fake
    state['retain'] = retain
    if copy_cap:
        original = acquisition.Radio

        class CopyRadio(original):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.info['caps'] = ['PIPECOPY']

        monkeypatch.setattr(acquisition, 'Radio', CopyRadio)

    def pipeline(*args, kernel, optimized, copy_option, **kwargs):
        assert copy_option == (1 if copy_cap else None)
        assert kernel == 3 and optimized is True
        summary, capture = acquisition.run_detection(*args, **kwargs)
        summary['copy_policy'] = {
            'requested': copy_option,
            'returned': copy_option,
            'supported': copy_cap,
        }
        summary['fused_active'] = int(copy_cap and kwargs['samples'] == 16380)
        summary['acquisition_policies'] = {
            'ACQOPT': {'requested': 3, 'returned': 3},
            'CLEAROPT': {'requested': 1, 'returned': 1},
        }
        return summary, capture

    monkeypatch.setattr(acquisition, 'run_pipeline', pipeline)
    w = MainWindow()
    w.output_dir = tmp_path
    w.mode.setCurrentIndex(2)
    w.autosave.setChecked(True)
    w.scan.setChecked(True)
    w.scan_low.setValue(2440)
    w.scan_high.setValue(2442)
    w.scan_step.setValue(2)
    try:
        w.show()
        w.start_acquisition()
        spin(app, lambda: len(calls) >= 3 and bool(w.stats))
        assert 'Experimental K3 / ACQ3 / CLEAR1' in w.status_label.text()
        assert (
            'COPY1 (fused 1)' if copy_cap else 'copy legacy (not selected)'
        ) in w.status_label.text()
        assert 'host-session duty' in w.status_label.text()
        assert {c[0] for c in calls} == {2440, 2442}
        docs = read_summaries(app, tmp_path, '*.detpipe1.json')
        assert docs and all(d['gui_mode'] == 'DETPIPE1' for d in docs)
        assert all(d['copy_policy']['returned'] == (1 if copy_cap else None) for d in docs)
        assert all(bool(d['retained_sigmf']) == retain for d in docs)
        assert bool(w.latest) == retain
        if retain:
            w.centralWidget().layout().insertWidget(
                0,
                QtWidgets.QLabel(
                    'SYNTHETIC TEST FIXTURE ONLY · no hardware measurements in this screenshot'
                ),
            )
            app.processEvents()
            w.grab().save(str(tmp_path / 'optimized-test-fixture.png'))
        w.stop_acquisition()
        spin(app, lambda: not any(x.isRunning() for x in w.workers.values()))
        w.start_acquisition()
        spin(app, lambda: bool(w.stats))
    finally:
        cleanup(app, w)


def test_endpoint_text_flags_only_saturated_captures():
    import numpy as np

    from sdr_research.acquisition import receiver_settings
    from sdr_research.gui import CLIP_WARN_PERCENT, endpoint_text
    from sdr_research.protocol import Capture

    def capture(iq):
        return Capture(np.asarray(iq, np.complex64), 16_000_000, 2_440_000_000, 't', 0, 0, 0, 10)

    quiet = np.full(1000, (3 - 4j) / 512)
    assert endpoint_text(capture(quiet)) == 'ADC endpoints 0.00%'
    count = int(1000 * CLIP_WARN_PERCENT / 100)
    near = quiet.copy()
    near[:count] = 511j / 512  # wire Q = -511, one code inside the negative endpoint
    assert 'CLIPPING' not in endpoint_text(capture(near))
    clipped = quiet.copy()
    clipped[:count] = 512j / 512  # wire Q = -512, the negative endpoint
    assert endpoint_text(capture(clipped)) == 'ADC endpoints 1.00% · LIKELY CLIPPING'
    manual = receiver_settings({'gain': 40, 'bandwidth_mhz': 12, 'rate_hz': 16_000_000}, 2440)
    assert (manual['gain_mode'], manual['gain_index'], manual['frequency_mhz']) == (
        'manual',
        40,
        2440,
    )


def test_port_picker_preserves_manual_assignments(app, monkeypatch):
    from types import SimpleNamespace

    import sdr_research.gui as gui

    monkeypatch.setattr(
        gui.list_ports,
        'comports',
        lambda: [
            SimpleNamespace(device='/dev/ttyUSB7', description='Test receiver'),
            SimpleNamespace(device='/dev/ttyACM0', description='Test CDC'),
        ],
    )
    w = MainWindow()
    try:
        assert w.port_picker.count() == 2
        assert w.port.text() == '/dev/ttyACM0'
        w.port.setText('/dev/custom@2440,/dev/ttyUSB7@2480')
        w.refresh_ports()
        assert w.port.text() == '/dev/custom@2440,/dev/ttyUSB7@2480'
        monkeypatch.setattr(gui.list_ports, 'comports', lambda: [])
        w.refresh_ports()
        assert w.port.text() == '/dev/custom@2440,/dev/ttyUSB7@2480'
    finally:
        cleanup(app, w)


def test_agc_detector_warning_tracks_both_controls(app):
    w = MainWindow()
    w.show()
    try:
        assert not w.agc_warning.isVisible()
        w.mode.setCurrentIndex(1)
        assert w.agc_warning.isVisible()
        w.gain.setValue(40)
        assert not w.agc_warning.isVisible()
        w.mode.setCurrentIndex(2)
        assert not w.agc_warning.isVisible()
        w.gain.setValue(-1)
        assert w.agc_warning.isVisible()
        w.mode.setCurrentIndex(0)
        assert not w.agc_warning.isVisible()
    finally:
        cleanup(app, w)
