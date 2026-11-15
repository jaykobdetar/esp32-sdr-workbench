"""Task-first workflows. Synthetic/fake devices only; no hardware is opened."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time

import pytest
from PySide6 import QtCore, QtWidgets

from sdr_research.lab_devices import Device
from sdr_research.studio_gui import ReceiverView, StudioWindow


@pytest.fixture(scope='session')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def until(app, condition, timeout=8):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr('sdr_research.studio_gui.discover_devices', lambda: [])
    w = StudioWindow(demo=True)
    w.output.setText(str(tmp_path))
    w.duration.addItem('Short test', 0.3)
    w.duration.setCurrentIndex(w.duration.count() - 1)
    yield w
    if w.session and w.session.is_alive():
        w.session.stop()
        w.session.join(6)
    w.timer.stop()
    w.close()
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()


def test_demo_record_inspect_repeat(window, app):
    w = window
    w.show()
    assert w.start_button.isEnabled()
    w.start_session()
    first = w.session
    w.start_session()
    assert w.session is first
    until(app, lambda: len(w.latest) == 2)
    w.inspect_latest()
    assert w.dialogs
    w.dialogs[0].close()
    until(app, lambda: not first.is_alive())
    w.poll()
    assert first.state == 'complete'
    assert not first.transmitters
    assert w.capture_list.count() > 0
    w.open_saved_capture(w.capture_list.item(0))
    assert w.dialogs
    w.dialogs[0].close()
    assert w.start_button.isEnabled()
    w.start_session()
    assert w.session is not first
    until(app, lambda: not w.session.is_alive())
    w.poll()


def test_no_receiver_and_compare_readiness(window):
    w = window
    for row in w.device_rows:
        row['check'].setChecked(False)
    assert not w.start_button.isEnabled()
    w.start_session()
    assert w.session is None
    w.device_rows[0]['check'].setChecked(True)
    w.task.setCurrentIndex(2)
    assert not w.start_button.isEnabled()
    assert 'two receivers' in w.plan.text()
    w.device_rows[1]['check'].setChecked(True)
    assert w.start_button.isEnabled()


def test_normal_close_waits_for_stop(window, app):
    w = window
    w.duration.setCurrentIndex(1)
    w.show()
    w.start_session()
    until(app, lambda: len(w.latest) == 2)
    w.close()
    until(app, lambda: not w.isVisible())
    assert not w.session.is_alive()


def test_demo_never_transmits_and_preserves_mode(window):
    w = window
    w.mode.setCurrentIndex(1)
    w.task.setCurrentIndex(1)
    assert w.task.currentData() == 'listen'
    w.start_session()
    assert not w.session.transmitters
    assert all(r.demo and r.settings['mode'] == 'raw' for r in w.session.receivers)
    assert w.mode.currentData() == 'DETPIPE1'


def test_devices_explicit_transmitter_and_selection(window, monkeypatch):
    w = window
    devices = [
        Device('receiver', '/dev/a', '/dev/a', 'RX', 'A', 'same', 1, 1),
        Device('receiver', '/dev/b', '/dev/b', 'RX', 'B', 'same', 1, 1),
        Device('transmitter', '/dev/c', '/dev/c', 'TX', 'C', 'txid', 1, 1),
    ]
    monkeypatch.setattr('sdr_research.studio_gui.discover_devices', lambda: devices)
    w.demo.setChecked(False)
    w.task.setCurrentIndex(1)
    assert not w.start_button.isEnabled()
    assert not w.device_rows[2]['check'].isChecked()
    w.device_rows[2]['check'].setChecked(True)
    assert w.start_button.isEnabled()
    w.device_rows[0]['check'].setChecked(False)
    w.refresh_devices()
    assert not w.device_rows[0]['check'].isChecked()
    assert w.device_rows[1]['check'].isChecked()
    w.task.setCurrentIndex(0)
    assert not w.device_rows[2]['card'].isVisible()


def test_unwritable_output_is_visible_error(window, app, tmp_path):
    path = tmp_path / 'not-directory'
    path.write_text('x')
    window.output.setText(str(path))
    window.start_session()
    until(app, lambda: not window.session.is_alive())
    window.poll()
    assert 'attention' in window.banner.text().lower()
    assert window.start_button.isEnabled()


def test_stale_plot_status(app):
    view = ReceiverView('RX', '#00ffff')
    view.update_capture(None, {})
    assert 'Waiting' in view.status.text()
    view.last_received = time.monotonic() - 10
    view.update_capture(None, {})
    assert '10.' in view.status.text()
    view.close()
    view.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()


def test_settings_import_atomic_and_no_start(window, app):
    import json

    w = window
    original = w.current_settings()
    w.settings_text.setPlainText(json.dumps(original | {'frequency_mhz': 2501}))
    w.apply_pasted_settings()
    assert w.current_settings() == original
    assert 'Not applied' in w.settings_feedback.text()
    d = original | {
        'frequency_mhz': 2460,
        'gain': None,
        'receiver_mode': 'DETPIPE1',
        'duration_s': 30,
        'background_policy': 2,
    }
    w.settings_text.setPlainText(json.dumps(d))
    w.apply_pasted_settings()
    assert w.current_settings() == d
    assert w.session is None
    w.show_current_settings()
    assert json.loads(w.settings_text.toPlainText()) == d
    w.copy_settings_prompt()
    prompt = app.clipboard().text()
    assert '2460' in prompt and 'JSON schema' in prompt
    assert w.output.text() not in prompt


def test_settings_transmitter_import_requires_selection(window, monkeypatch):
    import json

    w = window
    devices = [
        Device('receiver', '/dev/a', '/dev/a', 'RX', 'A', 'same', 1, 1),
        Device('transmitter', '/dev/c', '/dev/c', 'TX', 'C', 'txid', 1, 1),
    ]
    monkeypatch.setattr('sdr_research.studio_gui.discover_devices', lambda: devices)
    d = w.current_settings() | {'task': 'test', 'duration_s': 10}
    w.settings_text.setPlainText(json.dumps(d))
    w.apply_pasted_settings()
    assert 'Not applied' in w.settings_feedback.text()
    w.demo.setChecked(False)
    w.device_rows[1]['check'].setChecked(True)
    w.apply_pasted_settings()
    assert w.task.currentData() == 'test'
    assert not w.device_rows[1]['check'].isChecked()
    assert not w.start_button.isEnabled()
    assert w.session is None


def test_memory_only_until_stopped(window, app, tmp_path):
    w = window
    w.save.setChecked(False)
    w.duration.setCurrentIndex(w.duration.findData(None))
    w.start_session()
    until(app, lambda: len(w.latest) == 2)
    assert w.session.is_alive() and w.session.duration_s is None
    assert w.last_output is None
    assert not list(tmp_path.iterdir())
    w.stop_session()
    until(app, lambda: not w.session.is_alive())
    w.poll()
    assert w.session.state == 'stopped'
    assert not list(tmp_path.iterdir())
    assert not w.folder_button.isEnabled()


def test_import_until_stopped_and_no_save(window):
    import json

    w = window
    d = w.current_settings() | {'duration_s': None, 'save_captures': False}
    w.settings_text.setPlainText(json.dumps(d))
    w.apply_pasted_settings()
    assert w.current_settings() == d and w.session is None


def test_combined_individual_both_views(window, app):
    w = window
    w.show()
    w.start_session()
    until(app, lambda: len(w.latest) == 2)
    w.poll()
    assert w.combined.isVisible()
    assert all(not v.isVisible() for v in w.views.values())
    assert 'Receiver' in w.combined.metrics.text()
    w.display_mode.setCurrentIndex(1)
    assert not w.combined.isVisible()
    assert all(v.isVisible() for v in w.views.values())
    w.display_mode.setCurrentIndex(2)
    assert w.combined.isVisible() and all(v.isVisible() for v in w.views.values())


def test_stream_controls_and_import(window):
    import json

    w = window
    w.demo.setChecked(False)
    w.mode.setCurrentIndex(w.mode.findData('DSTREAMIQ'))
    assert w.rate.currentData() == 16000000 and w.samples.value() == 16380
    assert not w.rate.isEnabled() and not w.samples.isEnabled() and not w.run_ms.isEnabled()
    assert w.policy.isEnabled() and 'sparse' in w.agc_note.text()
    d = w.current_settings() | {'duration_s': 10, 'sample_rate_hz': 40000000}
    w.settings_text.setPlainText(json.dumps(d))
    w.apply_pasted_settings()
    assert 'Not applied' in w.settings_feedback.text()


def test_four_receiver_demo_visible_health_repeat_and_stop(window, app):
    w = window
    w.demo_count.setCurrentIndex(1)
    assert len(w.device_rows) == 4
    assert '4 simulated receivers' in w.device_hint.text()
    w.show()
    w.start_session()
    first = w.session
    until(app, lambda: len(w.latest) == 4)
    assert len(w.views) == len(w.receiver_statuses) == w.rx_select.count() == 4
    # All four connections remain visible in combined-only mode.
    assert all(status.isVisible() for status in w.receiver_statuses.values())
    assert all(not view.isVisible() for view in w.views.values())
    w.display_mode.setCurrentIndex(2)
    assert all(view.isVisible() for view in w.views.values())
    for index, view in enumerate(w.views.values()):
        assert w.views_layout.getItemPosition(w.views_layout.indexOf(view))[:2] == (
            1 + index // 2,
            index % 2,
        )
    w.stop_session()
    until(app, lambda: not first.is_alive())
    w.poll()
    assert all('historical' in status.text() for status in w.receiver_statuses.values())
    old_statuses = list(w.receiver_statuses.values())
    w.start_session()
    assert w.session is not first
    # Before DeferredDelete is delivered, retired labels must already be hidden.
    assert all(not status.isVisible() for status in old_statuses)
    assert w.receiver_health_layout.count() == 4
    app.processEvents()
    visible_statuses = [
        child for child in w.receiver_health.findChildren(QtWidgets.QLabel) if child.isVisible()
    ]
    assert len(visible_statuses) == 4
    until(app, lambda: len(w.latest) == 4)
    assert len(w.receiver_statuses) == 4


def test_four_duplicate_serials_stay_distinct_and_rescan_preserves_selection(window, monkeypatch):
    devices = [
        Device(
            'receiver',
            f'/dev/path-{i}',
            f'/dev/ttyUSB{i}',
            'RX',
            f'usb-{i}',
            '0001',
            0x10C4,
            0xEA60,
        )
        for i in range(4)
    ]
    monkeypatch.setattr('sdr_research.studio_gui.discover_devices', lambda: devices)
    window.demo.setChecked(False)
    assert len(window.device_rows) == 4
    window.device_rows[2]['check'].setChecked(False)
    window.refresh_devices()
    assert [row['check'].isChecked() for row in window.device_rows] == [True, True, False, True]
    assert len({row['port'] for row in window.device_rows}) == 4


def test_receiver_failure_not_hidden_by_recent_plot(window, app):
    window.start_session()
    until(app, lambda: len(window.latest) == 2)
    window.session.stop()
    window.session.join(6)
    worker = window.session.workers['Receiver 2']
    worker.error = RuntimeError('USB disconnected')
    window.poll()
    status = window.receiver_statuses['Receiver 2'].text()
    assert 'USB disconnected' in status
    assert 'connection unverified' in window.views['Receiver 2'].status.text()
    assert 'no contributors' in window.combined.metrics.text()
