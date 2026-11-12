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
