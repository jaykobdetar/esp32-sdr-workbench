"""Shared console lifecycle. Synthetic IQ only, never accesses hardware."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import time

import pytest
from PySide6 import QtWidgets

from sdr_research.lab_gui import LabWindow


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def until(app, condition, timeout=6):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def test_demo_record_stop_restart_inspect(app, tmp_path):
    w = LabWindow(demo=True)
    w.output.setText(str(tmp_path))
    w.duration.setValue(1)
    w.show()
    try:
        assert len(w.rows) == 2
        w.start_session()
        first = w.session
        w.start_session()
        assert w.session is first
        until(app, lambda: len(w.latest) == 2)
        w.inspect_latest()
        assert w.dialogs
        w.dialogs[0].close()
        until(app, lambda: not w.session.is_alive())
        w.poll()
        result = json.loads((w.last_output / 'session.json').read_text())
        assert result['status'] == 'complete'
        assert not result['transmitters']
        assert len(list(w.last_output.rglob('*.sigmf-meta'))) > 0
        assert w.metrics.rowCount() == 2
        assert w.start_button.isEnabled()
        w.start_session()
        until(app, lambda: len(w.latest) == 2)
        w.stop_session()
        until(app, lambda: not w.session.is_alive())
    finally:
        if w.session and w.session.is_alive():
            w.session.stop()
            w.session.join(5)
        w.close()


def test_close_waits_for_cleanup(app, tmp_path):
    w = LabWindow(demo=True)
    w.output.setText(str(tmp_path))
    w.show()
    w.start_session()
    until(app, lambda: len(w.latest) == 2)
    w.close()
    until(app, lambda: not w.isVisible())
    assert not w.session.is_alive()


def test_no_receiver_is_rejected_without_thread(app, tmp_path):
    w = LabWindow(demo=True)
    for row in range(w.device_table.rowCount()):
        w.device_table.cellWidget(row, 0).setChecked(False)
    w.start_session()
    assert w.session is None
    assert 'Select at least one' in w.log.toPlainText()
    w.close()


def test_final_transmitter_states_are_not_stale(app):
    """Both sources remain visible, with uncertain STOP distinct from silence."""
    import queue
    from types import SimpleNamespace

    w = LabWindow(demo=True)
    w.tx_status.setText('TX 1 · running True')
    w.session = SimpleNamespace(
        notices=queue.Queue(),
        frames={},
        state='error',
        error='Cleanup incomplete',
        is_alive=lambda: False,
        manifest={
            'transmitter_results': {
                'TX 1': {'stop': {'running': False, 'completed': 20}},
                'TX 2': {'latest': {'running': True, 'completed': 18}},
            }
        },
    )
    w.poll()
    text = w.tx_status.text()
    assert 'TX 1 · STOP CONFIRMED' in text
    assert 'TX 2 · STOP UNCONFIRMED' in text
    assert 'running True' not in text
    assert 'Cleanup incomplete' in w.state_label.text()
    w.close()
