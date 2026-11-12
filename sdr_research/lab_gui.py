"""Shared local RF bench: independent receivers and bounded test transmitters."""

from __future__ import annotations

import argparse
import queue
from datetime import datetime, timezone
from pathlib import Path

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .analysis import endpoint_counts, spectrum
from .gui import InspectionWindow
from .lab_devices import discover_devices
from .lab_session import LabSession, ReceiverConfig, TransmitterConfig

COLORS = ('#42c8ed', '#ffbd69', '#b29bff', '#80d5a3')


def spin(low: int, high: int, value: int, suffix: str = '') -> QtWidgets.QSpinBox:
    widget = QtWidgets.QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    widget.setSuffix(suffix)
    return widget


def choice(items: list[tuple[str, object]]) -> QtWidgets.QComboBox:
    widget = QtWidgets.QComboBox()
    for label, value in items:
        widget.addItem(label, value)
    return widget


class LabWindow(QtWidgets.QMainWindow):
    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self.setWindowTitle('RF Bench · transmitters + receivers')
        self.resize(1440, 980)
        self.session = None
        self.latest = {}
        self.stats = {}
        self.curves = {}
        self.dialogs = []
        self.closing = False
        self.last_output = None
        self.devices = []
        self.tx_rows = {}
        self.build_ui()
        self.demo.setChecked(demo)
        self.refresh_devices()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def build_ui(self) -> None:
        body = QtWidgets.QWidget()
        self.setCentralWidget(body)
        root = QtWidgets.QVBoxLayout(body)
        root.setContentsMargins(22, 16, 22, 16)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel('RF BENCH')
        title.setStyleSheet('font-size: 27px; font-weight: 700; color: #42c8ed')
        header.addWidget(title)
        header.addWidget(QtWidgets.QLabel('TRANSMIT  /  OBSERVE  /  RECORD'), 1)
        self.state_label = QtWidgets.QLabel('IDLE · RF is not started automatically')
        self.state_label.setStyleSheet('font-weight: 600; color: #80d5a3')
        header.addWidget(self.state_label)
        root.addLayout(header)
        warning = QtWidgets.QLabel(
            'Burst reception has gaps. Per-receiver duty is not combined coverage or packet recall. '
            'Multiple transmitters may interfere. No flashing is performed here.'
        )
        warning.setWordWrap(True)
        root.addWidget(warning)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        controls_scroll = QtWidgets.QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(controls)
        controls_scroll.setWidget(controls)
        split.addWidget(controls_scroll)
        self.setup = controls
        row = QtWidgets.QHBoxLayout()
        self.refresh = QtWidgets.QPushButton('Refresh USB devices')
        self.refresh.clicked.connect(self.refresh_devices)
        self.demo = QtWidgets.QCheckBox('Demo · no hardware')
        self.demo.toggled.connect(self.refresh_devices)
        row.addWidget(self.refresh)
        row.addWidget(self.demo)
        left.addLayout(row)
        self.device_table = QtWidgets.QTableWidget(0, 4)
        self.device_table.setHorizontalHeaderLabels(
            ['Use', 'Device / USB location', 'Role', 'RX MHz']
        )
        self.device_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.device_table.setColumnWidth(0, 42)
        self.device_table.setColumnWidth(2, 78)
        self.device_table.setColumnWidth(3, 85)
        self.device_table.setMinimumHeight(180)
        left.addWidget(self.device_table)
        self.device_note = QtWidgets.QLabel(
            'Select receivers; transmitters are opt-in. Discovery does not open serial ports.'
        )
        self.device_note.setWordWrap(True)
        left.addWidget(self.device_note)
        rx_box = QtWidgets.QGroupBox('RECEIVERS · independent acquisition')
        form = QtWidgets.QFormLayout(rx_box)
        self.mode = choice(
            [('Optimized pipeline · DETPIPE1', 'DETPIPE1'), ('DET1', 'DET1'), ('Raw I/Q', 'raw')]
        )
        self.rate = choice(
            [('16 MS/s', 16_000_000), ('40 MS/s', 40_000_000), ('80 MS/s', 80_000_000)]
        )
        self.gain_mode = choice([('Manual gain', 'manual'), ('Hardware AGC', 'agc')])
        self.gain = spin(0, 81, 60)
        gain_row = QtWidgets.QHBoxLayout()
        gain_row.addWidget(self.gain_mode)
        gain_row.addWidget(self.gain)
        self.samples = spin(256, 16380, 16380)
        self.bandwidth = spin(0, 67, 12, ' MHz')
        self.run_ms = spin(1, 5000, 1000, ' ms')
        self.ratio = spin(1000, 1000000, 4000)
        self.policy = choice(
            [('Firmware default', None), ('Legacy background', 1), ('Adaptive Q16', 2)]
        )
        form.addRow('Acquisition', self.mode)
        form.addRow('Sample rate', self.rate)
        form.addRow('Gain', gain_row)
        form.addRow('Bandwidth', self.bandwidth)
        form.addRow('Samples / buffer', self.samples)
        form.addRow('Detector run', self.run_ms)
        form.addRow('Threshold ×1000', self.ratio)
        form.addRow('Background rule', self.policy)
        left.addWidget(rx_box)
        self.agc_note = QtWidgets.QLabel()
        self.agc_note.setWordWrap(True)
        self.agc_note.setStyleSheet('color: #ffbd69')
        left.addWidget(self.agc_note)
        self.gain_mode.currentIndexChanged.connect(self.update_warnings)
        self.mode.currentIndexChanged.connect(self.update_warnings)
        tx_box = QtWidgets.QGroupBox('TRANSMITTERS · finite test packets only')
        form = QtWidgets.QFormLayout(tx_box)
        self.tx_frequency = spin(2402, 2480, 2440, ' MHz')
        self.tx_mode = choice([('2 Mbps GFSK', 2), ('1 Mbps GFSK', 1)])
        self.tx_power = choice([(f'{n} dBm', n) for n in (-40, -20, -16, -12, -8, -4, 0)])
        self.tx_power.setCurrentIndex(1)
        self.tx_length = spin(8, 252, 16, ' bytes')
        self.tx_interval = spin(1000, 1000000, 2000, ' µs')
        self.tx_count = spin(0, 20000, 0)
        form.addRow('Frequency', self.tx_frequency)
        form.addRow('Modulation', self.tx_mode)
        form.addRow('Power', self.tx_power)
        form.addRow('Payload size', self.tx_length)
        form.addRow('Packet interval', self.tx_interval)
        form.addRow('Packet cap (0 = time limit)', self.tx_count)
        left.addWidget(tx_box)
        note = QtWidgets.QLabel(
            'Receivers must produce data before selected transmitters start. TX stops on session end, Stop, or receiver failure. USB failure may prevent acknowledgement; RF has a finite deadline.'
        )
        note.setWordWrap(True)
        left.addWidget(note)
        session_box = QtWidgets.QGroupBox('SESSION')
        form = QtWidgets.QFormLayout(session_box)
        self.duration = spin(1, 60, 10, ' s')
        self.output = QtWidgets.QLineEdit(str(Path.home() / 'rf-bench-recordings'))
        self.save = QtWidgets.QCheckBox('Save raw I/Q and run summaries')
        self.save.setChecked(True)
        form.addRow('Observation after readiness', self.duration)
        form.addRow('Output folder', self.output)
        form.addRow(self.save)
        left.addWidget(session_box)
        left.addStretch()
        panel = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(panel)
        split.addWidget(panel)
        split.setSizes([470, 920])
        self.metrics = QtWidgets.QTableWidget(0, 6)
        self.metrics.setHorizontalHeaderLabels(
            ['Receiver', 'Runs', 'Captures', 'Retained', 'Session duty*', 'ADC endpoints']
        )
        self.metrics.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.metrics.setMaximumHeight(145)
        right.addWidget(self.metrics)
        self.plot = pg.PlotWidget(title='Latest received spectrum · mean DC removed')
        self.plot.setLabel('bottom', 'Frequency', units='MHz')
        self.plot.setLabel('left', 'Power', units='dBFS')
        self.plot.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot.addLegend()
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        right.addWidget(self.plot, 3)
        self.tx_status = QtWidgets.QLabel('TRANSMITTERS · idle / not selected')
        self.tx_status.setWordWrap(True)
        right.addWidget(self.tx_status)
        inspect_row = QtWidgets.QHBoxLayout()
        self.rx_select = QtWidgets.QComboBox()
        inspect = QtWidgets.QPushButton('Inspect latest I/Q')
        inspect.clicked.connect(self.inspect_latest)
        open_folder = QtWidgets.QPushButton('Open recordings')
        open_folder.clicked.connect(self.open_recordings)
        inspect_row.addWidget(self.rx_select, 1)
        inspect_row.addWidget(inspect)
        inspect_row.addWidget(open_folder)
        right.addLayout(inspect_row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(300)
        right.addWidget(self.log, 1)
        right.addWidget(
            QtWidgets.QLabel(
                '* Session duty includes acquisition/transfer gaps for that receiver. It cannot be added to infer union coverage.'
            )
        )
        footer = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton('Start selected devices')
        self.start_button.setMinimumHeight(42)
        self.start_button.setStyleSheet('background: #126a7e; font-weight: 600')
        self.start_button.clicked.connect(self.start_session)
        self.stop_button = QtWidgets.QPushButton('STOP ALL')
        self.stop_button.setMinimumHeight(42)
        self.stop_button.setStyleSheet('background: #833c36; font-weight: 700')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_session)
        footer.addWidget(self.start_button, 1)
        footer.addWidget(self.stop_button, 1)
        root.addLayout(footer)
        self.update_warnings()

    def update_warnings(self) -> None:
        agc = self.gain_mode.currentData() == 'agc'
        self.gain.setEnabled(not agc)
        self.agc_note.setText(
            'AGC changes gain: detector energies and candidate rates are not comparable across gain steps.'
            if agc and self.mode.currentData() != 'raw'
            else ''
        )

    def refresh_devices(self) -> None:
        if self.session is not None and self.session.is_alive():
            return
        if self.demo.isChecked():
            self.mode.setCurrentIndex(self.mode.findData('raw'))
        self.device_table.setRowCount(0)
        self.devices = [] if self.demo.isChecked() else discover_devices()
        rows = (
            [
                ('Demo RX A', 'receiver', 'SIMULATED-A', ''),
                ('Demo RX B', 'receiver', 'SIMULATED-B', ''),
            ]
            if self.demo.isChecked()
            else [(d.label, d.kind, d.port, d.serial_number) for d in self.devices]
        )
        self.rows = rows
        for label, kind, port, _serial in rows:
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            check = QtWidgets.QCheckBox()
            check.setChecked(kind == 'receiver')
            check.setEnabled(kind in ('receiver', 'transmitter'))
            self.device_table.setCellWidget(row, 0, check)
            item = QtWidgets.QTableWidgetItem(label)
            item.setToolTip(port)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.device_table.setItem(row, 1, item)
            item = QtWidgets.QTableWidgetItem(kind.upper())
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.device_table.setItem(row, 2, item)
            frequency = spin(2400, 2483, 2440)
            frequency.setEnabled(kind == 'receiver')
            self.device_table.setCellWidget(row, 3, frequency)
        self.device_note.setText(
            'Demo generates two independent synthetic raw-I/Q streams; no ports or RF transmitter opened.'
            if self.demo.isChecked()
            else 'Select receivers; transmitters are opt-in. USB location distinguishes duplicate serial labels.'
        )

    def start_session(self) -> None:
        if self.session is not None and self.session.is_alive():
            return
        try:
            rx, tx = [], []
            demo = self.demo.isChecked()
            mode = 'raw' if demo else self.mode.currentData()
            for row, (_label, kind, port, serial) in enumerate(self.rows):
                if not self.device_table.cellWidget(row, 0).isChecked():
                    continue
                if kind == 'receiver':
                    settings = dict(
                        mode=mode,
                        frequency_mhz=self.device_table.cellWidget(row, 3).value(),
                        rate_hz=self.rate.currentData(),
                        gain=None if self.gain_mode.currentData() == 'agc' else self.gain.value(),
                        bandwidth_mhz=self.bandwidth.value(),
                        samples=self.samples.value(),
                        bits=10,
                        det_ms=self.run_ms.value(),
                        ratio_milli=self.ratio.value(),
                        background_policy=self.policy.currentData(),
                        candidate_count=1,
                        threshold_db=10,
                        autosave=self.save.isChecked(),
                        record_all=True,
                        scan=False,
                    )
                    rx.append(
                        ReceiverConfig(
                            label=f'RX {len(rx) + 1}', port=port, settings=settings, demo=demo
                        )
                    )
                elif kind == 'transmitter':
                    settings = dict(
                        frequency_mhz=self.tx_frequency.value(),
                        mode_mbps=self.tx_mode.currentData(),
                        power_dbm=self.tx_power.currentData(),
                        length=self.tx_length.value(),
                        interval_us=self.tx_interval.value(),
                        count=self.tx_count.value(),
                    )
                    tx.append(
                        TransmitterConfig(
                            label=f'TX {len(tx) + 1}',
                            port=port,
                            serial_number=serial,
                            settings=settings,
                        )
                    )
            if not rx:
                raise ValueError('Select at least one receiver.')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            folder = Path(self.output.text()).expanduser() / stamp
            self.session = LabSession(rx, tx, folder, duration_s=self.duration.value())
            self.last_output = folder
            self.tx_rows.clear()
            self.latest.clear()
            self.stats.clear()
            self.plot.clear()
            self.plot.setTitle(
                'SYNTHETIC DEMO · no RF hardware'
                if demo
                else 'Latest received spectrum · mean DC removed'
            )
            self.curves.clear()
            self.rx_select.clear()
            for index, receiver in enumerate(rx):
                self.curves[receiver.label] = self.plot.plot(
                    [],
                    [],
                    pen=pg.mkPen(COLORS[index % len(COLORS)], width=1.5),
                    name=receiver.label,
                )
                self.rx_select.addItem(receiver.label)
            self.setup.setEnabled(False)
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.state_label.setText('CONNECTING · transmitter waits for receivers')
            self.tx_status.setText(
                'TRANSMITTERS · waiting for receiver readiness'
                if tx
                else 'TRANSMITTERS · not selected'
            )
            self.log.appendPlainText(
                f'Session: {folder}\nMode: {"SYNTHETIC DEMO" if demo else mode}'
            )
            self.session.start()
        except Exception as error:
            self.log.appendPlainText(f'Cannot start: {error}')
            self.state_label.setText('NOT STARTED · check log')
            self.setup.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

    def stop_session(self) -> None:
        if self.session is not None and self.session.is_alive():
            self.session.stop()
            self.state_label.setText('STOPPING · awaiting device cleanup')
            self.stop_button.setEnabled(False)

    def poll(self) -> None:
        session = self.session
        if session is None:
            return
        for _ in range(100):
            try:
                kind, value = session.notices.get_nowait()
            except queue.Empty:
                break
            if kind == 'receiver':
                if value['kind'] in ('error', 'state', 'record'):
                    self.log.appendPlainText(f'{value["label"]} {value["kind"]}: {value["value"]}')
            elif kind != 'transmitter':
                self.log.appendPlainText(f'{kind}: {value}')
            if kind == 'transmitter':
                status = value['status']
                self.tx_rows[value['label']] = (
                    f'{value["label"]} · running {status.get("running", "?")} · completed {status.get("completed", "?")} · attempted {status.get("attempted", "?")}'
                )
                self.tx_status.setText('\n'.join(self.tx_rows.values()))
        for label, frames in list(session.frames.items()):
            if not frames:
                continue
            capture, _, stats = frames.pop()
            frames.clear()
            self.stats[label] = stats
            if capture is not None:
                self.latest[label] = capture
                offsets, power = spectrum(capture.iq, capture.sample_rate_hz)
                self.curves[label].setData(offsets / 1e6 + capture.frequency_hz / 1e6, power)
        self.metrics.setRowCount(len(self.stats))
        for row, (label, stats) in enumerate(self.stats.items()):
            cap = self.latest.get(label)
            endpoint = (
                f'{endpoint_counts(cap.iq, cap.bits)["either_component_endpoint_percent"]:.2f}%'
                if cap is not None
                else 'No retained I/Q'
            )
            values = [
                label,
                stats.get('runs', stats.get('count', 0)),
                stats.get('count', 0),
                stats.get('retained', stats.get('count', 0)),
                f'{100 * stats.get("nominal_duty", 0):.2f}%',
                endpoint,
            ]
            for col, value in enumerate(values):
                self.metrics.setItem(row, col, QtWidgets.QTableWidgetItem(str(value)))
        if session.is_alive():
            if not self.closing and self.stop_button.isEnabled():
                self.state_label.setText(f'{session.state.upper()} · finite session')
        else:
            self.state_label.setText(
                f'{session.state.upper()}'
                + (f' · {session.error}' if session.error else ' · session finished')
            )
            results = session.manifest.get('transmitter_results', {})
            if results:
                self.tx_status.setText(
                    '\n'.join(
                        f'{label} · {"STOP CONFIRMED" if item.get("stop", {}).get("running") is False else "STOP UNCONFIRMED"} · completed {item.get("stop", {}).get("completed", "?")}'
                        for label, item in results.items()
                    )
                )
            self.setup.setEnabled(True)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            if self.closing:
                self.close()

    def inspect_latest(self) -> None:
        capture = self.latest.get(self.rx_select.currentText())
        if capture is None:
            self.log.appendPlainText('No retained capture for that receiver yet.')
            return
        dialog = InspectionWindow(capture, self)
        self.dialogs.append(dialog)
        dialog.finished.connect(lambda: self.dialogs.remove(dialog))
        dialog.show()

    def open_recordings(self) -> None:
        path = self.last_output or Path(self.output.text()).expanduser()
        if path.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.session is not None and self.session.is_alive():
            self.closing = True
            self.stop_session()
            event.ignore()
        else:
            for dialog in list(self.dialogs):
                dialog.close()
            event.accept()


def apply_theme(app: QtWidgets.QApplication) -> None:
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    for role, color in [
        (QtGui.QPalette.ColorRole.Window, '#131d29'),
        (QtGui.QPalette.ColorRole.WindowText, '#dfe9f3'),
        (QtGui.QPalette.ColorRole.Base, '#0c1520'),
        (QtGui.QPalette.ColorRole.AlternateBase, '#182536'),
        (QtGui.QPalette.ColorRole.Text, '#dfe9f3'),
        (QtGui.QPalette.ColorRole.Button, '#243447'),
        (QtGui.QPalette.ColorRole.ButtonText, '#dfe9f3'),
        (QtGui.QPalette.ColorRole.Highlight, '#126a7e'),
    ]:
        palette.setColor(role, QtGui.QColor(color))
    app.setPalette(palette)
    pg.setConfigOptions(background='#0c1520', foreground='#c6d5e4', antialias=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args(argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(app)
    window = LabWindow(args.demo)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
