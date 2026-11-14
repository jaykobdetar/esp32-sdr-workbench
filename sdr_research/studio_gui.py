"""RF Studio: a task-first local interface for receivers and test transmitters."""

from __future__ import annotations

import argparse
import json
import queue
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui
from PySide6 import QtWidgets as W

from .analysis import endpoint_counts, spectrum
from .diversity import combine_spectra
from .gui import InspectionWindow
from .lab_devices import discover_devices
from .lab_session import LabSession, ReceiverConfig, TransmitterConfig
from .recording import load_capture
from .studio_model import TASKS, describe_result, readiness, session_history
from .studio_settings import llm_prompt, parse_settings

COLORS = ('#39d5ce', '#e9b968', '#b9a1ff', '#f391b5')


def label(text: str, name: str = '', wrap: bool = False) -> W.QLabel:
    result = W.QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    result.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    return result


def button(text: str, fn, name: str = '') -> W.QPushButton:
    b = W.QPushButton(text)
    b.setObjectName(name)
    b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(fn)
    return b


def spin(low: int, high: int, value: int, suffix: str = '') -> W.QSpinBox:
    s = W.QSpinBox()
    s.setRange(low, high)
    s.setValue(value)
    s.setSuffix(suffix)
    s.setButtonSymbols(W.QAbstractSpinBox.ButtonSymbols.PlusMinus)
    return s


def combo(values: list[tuple[str, object]]) -> W.QComboBox:
    c = W.QComboBox()
    for text, value in values:
        c.addItem(text, value)
    return c


class ReceiverView(W.QFrame):
    def __init__(self, name: str, color: str) -> None:
        super().__init__()
        self.setObjectName('card')
        self.setMaximumHeight(430)
        self.color = color
        self.last_capture = None
        self.last_received = None
        self.waterfall = np.full((60, 512), -100.0)
        layout = W.QVBoxLayout(self)
        header = W.QHBoxLayout()
        title = label(name, 'subtitle')
        title.setStyleSheet(f'color: {color}')
        header.addWidget(title)
        self.status = label('Waiting for data', 'muted')
        header.addWidget(self.status, 1, QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)
        self.plot = pg.PlotWidget()
        self.plot.setLabel('bottom', 'Frequency', units='MHz')
        self.plot.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot.setLabel('left', 'Power', units='dBFS')
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.curve = self.plot.plot(pen=pg.mkPen(color, width=1.5))
        self.plot.setMinimumHeight(150)
        self.plot.setMaximumHeight(190)
        layout.addWidget(self.plot, 2)
        self.water = pg.PlotWidget()
        self.water.setLabel('bottom', 'Frequency', units='MHz')
        self.water.getAxis('bottom').enableAutoSIPrefix(False)
        self.water.setLabel('left', 'Capture index')
        self.water.setMouseEnabled(x=False, y=False)
        self.image = pg.ImageItem(axisOrder='row-major')
        self.image.setLookupTable(pg.colormap.get('viridis').getLookupTable())
        self.water.addItem(self.image)
        self.water.setMinimumHeight(80)
        self.water.setMaximumHeight(110)
        layout.addWidget(self.water, 1)
        self.metrics = label('No captures yet', 'muted', True)
        layout.addWidget(self.metrics)
        self.health = label('', 'warning', True)
        layout.addWidget(self.health)

    def update_capture(self, capture, stats: dict) -> None:
        captures = stats.get('count', 0)
        retained = stats.get('retained', captures)
        duty = 100 * stats.get('nominal_duty', 0)
        self.metrics.setText(
            f'{captures:,} captures  ·  {retained:,} retained  ·  {duty:.2f}% estimated receiver duty'
        )
        if capture is None:
            self.refresh_age()
            return
        if self.last_capture is capture:
            return
        self.last_capture = capture
        self.last_received = time.monotonic()
        self.refresh_age()
        offsets, power = spectrum(capture.iq, capture.sample_rate_hz, 512)
        frequency = offsets / 1e6 + capture.frequency_hz / 1e6
        self.curve.setData(frequency, power)
        if self.waterfall.shape[1] != len(power):
            self.waterfall = np.full((60, len(power)), -100.0)
        self.waterfall = np.roll(self.waterfall, -1, axis=0)
        self.waterfall[-1] = power
        self.image.setImage(self.waterfall, levels=(-100, -10), autoLevels=False)
        self.image.setRect(
            QtCore.QRectF(float(frequency[0]), -59, float(frequency[-1] - frequency[0]), 60)
        )
        endpoint = endpoint_counts(capture.iq, capture.bits)['either_component_endpoint_percent']
        self.health.setText(
            f'{endpoint:.2f}% ADC endpoints: possible clipping. Try lower manual gain.'
            if endpoint > 1
            else f'{endpoint:.2f}% ADC endpoints · no packet identity inferred'
        )

    def refresh_age(self) -> None:
        if self.last_received is None:
            self.status.setText('Waiting for a retained capture')
        else:
            age = time.monotonic() - self.last_received
            self.status.setText(f'Last capture {age:.1f}s ago')


class CombinedView(ReceiverView):
    def __init__(self) -> None:
        super().__init__('Combined diversity spectrum', '#77ded1')
        self.signature = None
        self.water.setLabel('left', 'Display update')

    def update_inputs(self, inputs: dict) -> None:
        sparse = bool(inputs) and all(c.metadata.get('sparse_iq') for c, _ in inputs.values())
        result = combine_spectra(inputs, time.monotonic(), max_age_s=8.0 if sparse else 2.0)
        self.status.setText(
            f'Oldest input {result.max_age_s:.1f}s'
            if result.contributors
            else 'Waiting for fresh usable captures'
        )
        self.metrics.setText(
            f'{result.mode} · ' + (', '.join(result.contributors) or 'no contributors')
        )
        excluded = '; '.join(f'{name}: {reason}' for name, reason in result.excluded.items())
        self.health.setText(
            ('Sparse snapshot display (8s freshness limit). ' if sparse else '')
            + 'Noncoherent, asynchronous power display. Not continuous I/Q, calibrated RF power or packet recall.'
            + ('\nExcluded: ' + excluded if excluded else '')
            + (
                '\nAll usable inputs have possible clipping.'
                if result.mode == 'least-clipped fallback'
                else ''
            )
        )
        signature = (
            tuple((name, id(inputs[name][0])) for name in result.contributors),
            result.mode,
        )
        if not result.contributors:
            self.curve.clear()
            self.image.clear()
            self.waterfall = np.full((60, 512), -100.0)
            self.signature = signature
            return
        if signature == self.signature:
            return
        self.signature = signature
        self.curve.setData(result.frequency_mhz, result.power_dbfs)
        if self.waterfall.shape[1] != len(result.power_dbfs):
            self.waterfall = np.full((60, len(result.power_dbfs)), -100.0)
        self.waterfall = np.roll(self.waterfall, -1, axis=0)
        self.waterfall[-1] = result.power_dbfs
        self.image.setImage(self.waterfall, levels=(-100, -10), autoLevels=False)
        self.image.setRect(
            QtCore.QRectF(
                float(result.frequency_mhz[0]),
                -59,
                float(result.frequency_mhz[-1] - result.frequency_mhz[0]),
                60,
            )
        )


class StudioWindow(W.QMainWindow):
    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self.setWindowTitle('RF Studio')
        self.resize(1320, 900)
        self.setMinimumSize(980, 720)
        self.session = None
        self.finished_session = None
        self.closing = False
        self.devices = []
        self.device_rows = []
        self.latest = {}
        self.arrivals = {}
        self.combined = None
        self.views = {}
        self.dialogs = []
        self.last_output = None
        self.history = []
        self.build_ui()
        self.demo.setChecked(demo)
        self.refresh_devices()
        self.refresh_history()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)

    def build_ui(self) -> None:
        body = W.QWidget()
        self.setCentralWidget(body)
        root = W.QVBoxLayout(body)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        top = W.QHBoxLayout()
        name = W.QVBoxLayout()
        name.addWidget(label('RF Studio', 'title'))
        name.addWidget(label('A clearer view of your radios', 'muted'))
        top.addLayout(name)
        top.addStretch()
        self.banner = label('Idle · no radio activity started', 'status')
        top.addWidget(self.banner)
        root.addLayout(top)
        self.tabs = W.QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        self.setup_page = W.QWidget()
        self.live_page = W.QWidget()
        self.history_page = W.QWidget()
        self.tabs.addTab(self.setup_page, '1  Set up')
        self.tabs.addTab(self.live_page, '2  Watch live')
        self.tabs.addTab(self.history_page, '3  Recordings')
        self.build_setup()
        self.build_live()
        self.build_history()
        footer = W.QHBoxLayout()
        self.plan = label('', 'muted', True)
        footer.addWidget(self.plan, 1)
        self.start_button = button('Start listening', self.start_session, 'primary')
        self.start_button.setMinimumSize(190, 46)
        self.stop_button = button('Stop all devices', self.stop_session, 'danger')
        self.stop_button.setMinimumSize(170, 46)
        self.stop_button.setEnabled(False)
        footer.addWidget(self.start_button)
        footer.addWidget(self.stop_button)
        root.addLayout(footer)

    def build_setup(self) -> None:
        page = W.QVBoxLayout(self.setup_page)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.Shape.NoFrame)
        page.addWidget(scroll)
        self.setup = W.QWidget()
        scroll.setWidget(self.setup)
        grid = W.QGridLayout(self.setup)
        grid.setContentsMargins(4, 14, 4, 4)
        grid.setHorizontalSpacing(22)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        left = W.QVBoxLayout()
        left.addWidget(label('What would you like to do?', 'heading'))
        self.task = combo([(v[0], k) for k, v in TASKS.items()])
        self.task.setMinimumHeight(42)
        self.task.currentIndexChanged.connect(self.update_plan)
        left.addWidget(self.task)
        self.task_help = label('', 'muted', True)
        left.addWidget(self.task_help)
        row = W.QHBoxLayout()
        row.addWidget(label('Your devices', 'heading'))
        row.addStretch()
        self.refresh_button = button('Rescan USB', self.refresh_devices)
        row.addWidget(self.refresh_button)
        left.addLayout(row)
        self.device_container = W.QWidget()
        self.device_layout = W.QVBoxLayout(self.device_container)
        self.device_layout.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.device_container)
        self.device_hint = label('', 'muted', True)
        left.addWidget(self.device_hint)
        self.demo = W.QCheckBox('Explore with simulated data · no hardware used')
        self.demo.toggled.connect(self.refresh_devices)
        left.addWidget(self.demo)
        self.paste_toggle = W.QCheckBox('Paste settings / ask an LLM')
        left.addWidget(self.paste_toggle)
        self.paste_panel = W.QGroupBox('Portable settings · JSON')
        paste_layout = W.QVBoxLayout(self.paste_panel)
        paste_layout.addWidget(
            label(
                'Copy a prompt for your LLM, describe your goal, then paste its JSON here. Nothing runs until you separately press Start.',
                'muted',
                True,
            )
        )
        self.settings_text = W.QPlainTextEdit()
        self.settings_text.setPlaceholderText('Paste the complete JSON settings object here…')
        self.settings_text.setMinimumHeight(180)
        self.settings_text.setMaximumHeight(260)
        paste_layout.addWidget(self.settings_text)
        buttons = W.QHBoxLayout()
        buttons.addWidget(button('Copy LLM prompt', self.copy_settings_prompt))
        buttons.addWidget(button('Use current settings', self.show_current_settings))
        buttons.addWidget(button('Validate & apply', self.apply_pasted_settings))
        paste_layout.addLayout(buttons)
        self.settings_feedback = label(
            'Device choices, simulation and recording folder stay local. Applying settings deselects transmitters.',
            'muted',
            True,
        )
        paste_layout.addWidget(self.settings_feedback)
        left.addWidget(self.paste_panel)
        self.paste_panel.hide()
        self.paste_toggle.toggled.connect(self.paste_panel.setVisible)
        left.addStretch()
        grid.addLayout(left, 0, 0)
        right = W.QVBoxLayout()
        settings = W.QGroupBox('Session settings')
        form = W.QFormLayout(settings)
        form.setVerticalSpacing(16)
        self.frequency = spin(2402, 2480, 2440, ' MHz')
        self.frequency.valueChanged.connect(self.update_plan)
        self.duration = combo(
            [('5 seconds', 5), ('10 seconds', 10), ('30 seconds', 30), ('60 seconds', 60)]
        )
        self.duration.setCurrentIndex(1)
        self.duration.currentIndexChanged.connect(self.update_plan)
        self.duration.addItem('Until I stop · receive only', None)
        self.save = W.QCheckBox('Save session and captures')
        self.save.setChecked(True)
        self.save.toggled.connect(self.update_plan)
        form.addRow('Shared frequency', self.frequency)
        form.addRow('Session length', self.duration)
        form.addRow(self.save)
        form.addRow(
            label(
                'All selected radios use this frequency. Timed sessions stop automatically. Uncheck Save for memory-only use.',
                'muted',
                True,
            )
        )
        right.addWidget(settings)
        self.test_box = W.QGroupBox('Test signal')
        form = W.QFormLayout(self.test_box)
        self.tx_power = combo(
            [
                (f'{p} dBm' + (' · low power' if p == -20 else ''), p)
                for p in (-40, -20, -16, -12, -8, -4, 0)
            ]
        )
        self.tx_power.setCurrentIndex(1)
        self.tx_power.currentIndexChanged.connect(self.update_plan)
        form.addRow('Transmit power', self.tx_power)
        form.addRow(
            label(
                'The transmitter starts only after receivers deliver data. Default: known 2 Mbps packets, 16 bytes, every 2 ms.',
                'muted',
                True,
            )
        )
        self.tx_advanced_toggle = W.QCheckBox('Customize test packets')
        form.addRow(self.tx_advanced_toggle)
        self.tx_advanced = W.QWidget()
        packet_form = W.QFormLayout(self.tx_advanced)
        self.tx_mode = combo([('2 Mbps', 2), ('1 Mbps', 1)])
        self.tx_length = spin(8, 252, 16, ' bytes')
        self.tx_interval = spin(1000, 1000000, 2000, ' µs')
        packet_form.addRow('Radio mode', self.tx_mode)
        packet_form.addRow('Packet length', self.tx_length)
        packet_form.addRow('Packet interval', self.tx_interval)
        packet_form.addRow(
            label(
                'Known payload and sequence numbers. Hop patterns and custom payloads remain in the transmitter CLI.',
                'muted',
                True,
            )
        )
        form.addRow(self.tx_advanced)
        self.tx_advanced.hide()
        self.tx_advanced_toggle.toggled.connect(self.tx_advanced.setVisible)
        right.addWidget(self.test_box)
        self.advanced_toggle = W.QCheckBox('Show advanced radio settings')
        self.advanced_toggle.toggled.connect(lambda on: self.advanced.setVisible(on))
        right.addWidget(self.advanced_toggle)
        self.advanced = W.QGroupBox('Advanced · shared receiver settings')
        form = W.QFormLayout(self.advanced)
        self.mode = combo(
            [
                ('Live spectrum · raw I/Q', 'raw'),
                ('Event detector · optimized pipeline', 'DETPIPE1'),
                ('Event detector · DET1', 'DET1'),
                ('Experimental persistent telemetry + sparse I/Q', 'DSTREAMIQ'),
            ]
        )
        self.rate = combo(
            [('16 MS/s', 16_000_000), ('40 MS/s', 40_000_000), ('80 MS/s', 80_000_000)]
        )
        self.gain_mode = combo(
            [('Manual · comparable energy', 'manual'), ('Automatic gain (AGC)', 'agc')]
        )
        self.gain = spin(0, 81, 40)
        self.samples = spin(256, 16380, 16380)
        self.bandwidth = spin(0, 67, 12, ' MHz')
        self.run_ms = spin(1, 5000, 500, ' ms')
        self.ratio = W.QDoubleSpinBox()
        self.ratio.setRange(1, 1000)
        self.ratio.setDecimals(2)
        self.ratio.setValue(4)
        self.ratio.setSuffix(' × background')
        self.policy = combo([('Firmware default', None), ('Legacy', 1), ('Adaptive', 2)])
        for text, widget in [
            ('Receive mode', self.mode),
            ('Sample rate', self.rate),
            ('Gain control', self.gain_mode),
            ('Manual gain', self.gain),
            ('Bandwidth', self.bandwidth),
            ('Samples per capture', self.samples),
            ('Detector window', self.run_ms),
            ('Event threshold', self.ratio),
            ('Background policy', self.policy),
        ]:
            form.addRow(text, widget)
        self.agc_note = label('', 'warning', True)
        form.addRow(self.agc_note)
        self.output = W.QLineEdit(str(Path.home() / 'rf-studio-recordings'))
        form.addRow('Recording folder', self.output)
        right.addWidget(self.advanced)
        self.advanced.hide()
        self.mode.currentIndexChanged.connect(self.update_plan)
        self.gain_mode.currentIndexChanged.connect(self.update_plan)
        right.addWidget(
            label(
                'Default live I/Q mode favors visible waveforms over listening duty. These radios receive short bursts, with gaps. Shared control does not mean synchronized or continuous coverage.',
                'muted',
                True,
            )
        )
        right.addStretch()
        grid.addLayout(right, 0, 1)

    def current_settings(self) -> dict:
        return dict(
            schema_version=1,
            task=self.task.currentData(),
            frequency_mhz=self.frequency.value(),
            duration_s=self.duration.currentData(),
            save_captures=self.save.isChecked(),
            receiver_mode=self.mode.currentData(),
            sample_rate_hz=self.rate.currentData(),
            gain=None if self.gain_mode.currentData() == 'agc' else self.gain.value(),
            bandwidth_mhz=self.bandwidth.value(),
            samples=self.samples.value(),
            detector_window_ms=self.run_ms.value(),
            ratio_milli=round(self.ratio.value() * 1000),
            background_policy=self.policy.currentData(),
            tx_power_dbm=self.tx_power.currentData(),
            tx_mode_mbps=self.tx_mode.currentData(),
            tx_length_bytes=self.tx_length.value(),
            tx_interval_us=self.tx_interval.value(),
        )

    def copy_settings_prompt(self) -> None:
        W.QApplication.clipboard().setText(llm_prompt(self.current_settings()))
        self.settings_feedback.setText(
            'Prompt copied. Paste it into your LLM and replace the goal placeholder. No device identifiers or recording paths are included.'
        )

    def show_current_settings(self) -> None:
        self.settings_text.setPlainText(json.dumps(self.current_settings(), indent=2))
        self.settings_feedback.setText(
            'Current portable settings loaded into the editor. Edit or replace them, then Validate & apply.'
        )

    def apply_pasted_settings(self) -> None:
        if self.session and self.session.is_alive():
            self.settings_feedback.setText('Stop the current session before applying settings.')
            return
        try:
            d = parse_settings(self.settings_text.toPlainText())
            if self.demo.isChecked() and d['task'] == 'test':
                raise ValueError('Turn off simulation before applying a physical transmitter test.')
        except ValueError as error:
            self.settings_feedback.setText(f'Not applied: {error}')
            return
        widgets = [
            self.task,
            self.frequency,
            self.duration,
            self.save,
            self.mode,
            self.rate,
            self.gain_mode,
            self.gain,
            self.bandwidth,
            self.samples,
            self.run_ms,
            self.ratio,
            self.policy,
            self.tx_power,
            self.tx_mode,
            self.tx_length,
            self.tx_interval,
        ]
        blockers = [QtCore.QSignalBlocker(w) for w in widgets]
        for widget, key in [
            (self.task, 'task'),
            (self.duration, 'duration_s'),
            (self.mode, 'receiver_mode'),
            (self.rate, 'sample_rate_hz'),
            (self.policy, 'background_policy'),
            (self.tx_power, 'tx_power_dbm'),
            (self.tx_mode, 'tx_mode_mbps'),
        ]:
            widget.setCurrentIndex(widget.findData(d[key]))
        for widget, key in [
            (self.frequency, 'frequency_mhz'),
            (self.bandwidth, 'bandwidth_mhz'),
            (self.samples, 'samples'),
            (self.run_ms, 'detector_window_ms'),
            (self.tx_length, 'tx_length_bytes'),
            (self.tx_interval, 'tx_interval_us'),
        ]:
            widget.setValue(d[key])
        self.save.setChecked(d['save_captures'])
        self.gain_mode.setCurrentIndex(
            self.gain_mode.findData('agc' if d['gain'] is None else 'manual')
        )
        if d['gain'] is not None:
            self.gain.setValue(d['gain'])
        self.ratio.setValue(d['ratio_milli'] / 1000)
        del blockers
        for row in self.device_rows:
            if row['kind'] == 'transmitter':
                row['check'].setChecked(False)
        self.update_plan()
        self.settings_feedback.setText(
            'Applied to controls only. Review the settings and selected receivers. For a test, explicitly select the transmitter, then press Start. No hardware was opened.'
        )

    def build_live(self) -> None:
        layout = W.QVBoxLayout(self.live_page)
        self.live_title = label('Ready when you are', 'heading')
        self.live_hint = label(
            'Choose a task and devices in Set up, then start a session.', 'muted', True
        )
        layout.addWidget(self.live_title)
        layout.addWidget(self.live_hint)
        self.progress = W.QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat('Not running')
        layout.addWidget(self.progress)
        display_row = W.QHBoxLayout()
        display_row.addWidget(label('Display', 'muted'))
        self.display_mode = combo(
            [('Combined', 'combined'), ('Individual', 'individual'), ('Both', 'both')]
        )
        self.display_mode.currentIndexChanged.connect(self.update_display_mode)
        display_row.addWidget(self.display_mode)
        display_row.addWidget(
            label(
                'Combined averages compatible receiver powers, not their I/Q phases.', 'muted', True
            ),
            1,
        )
        layout.addLayout(display_row)
        self.views_container = W.QWidget()
        self.views_layout = W.QGridLayout(self.views_container)
        self.views_layout.setContentsMargins(0, 0, 0, 0)
        plots_scroll = W.QScrollArea()
        plots_scroll.setWidgetResizable(True)
        plots_scroll.setFrameShape(W.QFrame.Shape.NoFrame)
        plots_scroll.setWidget(self.views_container)
        layout.addWidget(plots_scroll, 1)
        self.empty_plot = label(
            'Your receivers will appear here\nEach has its own spectrum and capture-history waterfall.',
            'empty',
            True,
        )
        self.empty_plot.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.views_layout.addWidget(self.empty_plot)
        self.tx_status = label('No transmission requested', 'status', True)
        layout.addWidget(self.tx_status)
        row = W.QHBoxLayout()
        self.rx_select = W.QComboBox()
        self.inspect_button = button('Inspect latest capture', self.inspect_latest)
        self.inspect_button.setEnabled(False)
        self.folder_button = button('Open this session folder', self.open_recordings)
        self.folder_button.setEnabled(False)
        row.addWidget(self.rx_select)
        row.addWidget(self.inspect_button)
        row.addStretch()
        row.addWidget(self.folder_button)
        layout.addLayout(row)
        layout.addWidget(
            label(
                'The waterfall shows successive retained captures, not uninterrupted time. Energy is not proof of a decoded packet.',
                'muted',
                True,
            )
        )
        self.details_toggle = W.QCheckBox('Show diagnostic log')
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(500)
        self.log.setMaximumHeight(140)
        self.details_toggle.toggled.connect(self.log.setVisible)
        layout.addWidget(self.details_toggle)
        layout.addWidget(self.log)
        self.log.hide()

    def build_history(self) -> None:
        layout = W.QVBoxLayout(self.history_page)
        row = W.QHBoxLayout()
        row.addWidget(label('Saved sessions', 'heading'))
        row.addStretch()
        row.addWidget(button('Refresh list', self.refresh_history))
        row.addWidget(button('Choose recordings folder…', self.choose_history))
        layout.addLayout(row)
        self.history_root = Path.home() / 'rf-studio-recordings'
        self.history_path = label(str(self.history_root), 'muted')
        layout.addWidget(self.history_path)
        split = W.QSplitter()
        self.history_list = W.QListWidget()
        self.history_list.setMinimumWidth(250)
        self.history_list.currentRowChanged.connect(self.select_history)
        split.addWidget(self.history_list)
        panel = W.QWidget()
        right = W.QVBoxLayout(panel)
        self.history_summary = label('No session selected', 'subtitle', True)
        right.addWidget(self.history_summary)
        right.addWidget(
            label(
                'Recorded captures · double-click to inspect I/Q, power and spectrum', 'muted', True
            )
        )
        self.capture_list = W.QListWidget()
        self.capture_list.itemDoubleClicked.connect(self.open_saved_capture)
        right.addWidget(self.capture_list, 1)
        self.history_open = button('Open session folder', self.open_history_folder)
        right.addWidget(self.history_open)
        split.addWidget(panel)
        split.setSizes([350, 800])
        layout.addWidget(split, 1)

    def refresh_devices(self) -> None:
        if self.session and self.session.is_alive():
            return
        selected = {d['port']: d['check'].isChecked() for d in self.device_rows}
        while self.device_layout.count():
            item = self.device_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.device_rows = []
        demo = self.demo.isChecked()
        try:
            self.devices = [] if demo else discover_devices()
        except Exception as error:
            self.device_hint.setText(
                f'USB discovery failed: {error}. Reconnect devices and rescan.'
            )
            self.update_plan()
            return
        entries = (
            [
                ('receiver', 'demo-a', '', 'Simulated radio A'),
                ('receiver', 'demo-b', '', 'Simulated radio B'),
            ]
            if demo
            else [
                (d.kind, d.port, d.serial_number, f'USB {d.location or d.device}')
                for d in self.devices
                if d.kind in ('receiver', 'transmitter')
            ]
        )
        counts = {'receiver': 0, 'transmitter': 0}
        for kind, port, serial, location in entries:
            counts[kind] += 1
            name = f'{"Receiver" if kind == "receiver" else "Transmitter"} {counts[kind]}'
            card = W.QFrame()
            card.setObjectName('card')
            line = W.QVBoxLayout(card)
            top = W.QHBoxLayout()
            check = W.QCheckBox(name)
            check.setChecked(selected.get(port, kind == 'receiver'))
            check.toggled.connect(self.update_plan)
            top.addWidget(check)
            top.addStretch()
            top.addWidget(label('SIMULATED' if demo else 'USB detected', 'muted'))
            line.addLayout(top)
            line.addWidget(label(location, 'muted'))
            detail = label(port, 'muted', True)
            detail.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            detail.hide()
            toggle = W.QCheckBox('Connection details')
            toggle.toggled.connect(detail.setVisible)
            line.addWidget(toggle)
            line.addWidget(detail)
            self.device_layout.addWidget(card)
            self.device_rows.append(
                dict(kind=kind, port=port, serial=serial, label=name, check=check, card=card)
            )
        self.device_hint.setText(
            'No supported USB radios detected. Plug in an ESP32 receiver, then rescan. You can explore the interface with simulated data.'
            if not entries
            else 'Two simulated receivers; no USB devices will be opened.'
            if demo
            else 'USB detected is not a health check. Connection is verified when the session starts. Ports are kept separate even when serial labels match.'
        )
        self.update_plan()

    def update_plan(self) -> None:
        if not hasattr(self, 'start_button'):
            return
        task = self.task.currentData()
        demo = self.demo.isChecked()
        if demo and task == 'test':
            self.task.setCurrentIndex(0)
            return
        self.task_help.setText(TASKS[task][1])
        self.test_box.setVisible(task == 'test')
        rx, tx = 0, 0
        for d in self.device_rows:
            if d['kind'] == 'transmitter':
                d['card'].setVisible(task == 'test' and not demo)
            if d['check'].isChecked():
                rx += d['kind'] == 'receiver'
                tx += d['kind'] == 'transmitter' and task == 'test' and not demo
        error = readiness(task, rx, tx, demo)
        if task == 'test' and self.duration.currentData() is None:
            error = (
                'Test signals need a timed session (5–60 seconds). Until stopped is receive-only.'
            )
        mode = 'raw' if demo else self.mode.currentData()
        detector = mode != 'raw'
        streaming = mode == 'DSTREAMIQ'
        if streaming:
            self.rate.setCurrentIndex(self.rate.findData(16000000))
            self.samples.setValue(16380)
        self.rate.setEnabled(not streaming)
        self.samples.setEnabled(not streaming)
        for control in (self.run_ms, self.ratio, self.policy):
            control.setEnabled(detector)
        self.run_ms.setEnabled(detector and not streaming)
        self.mode.setEnabled(not demo)
        agc = self.gain_mode.currentData() == 'agc'
        self.gain.setEnabled(not agc)
        self.agc_note.setText(
            'AGC changes gain during capture; detector energies cannot be compared across gain changes.'
            if detector and agc
            else ''
        )
        if streaming:
            self.agc_note.setText(
                self.agc_note.text()
                + '\nExperimental: independent telemetry streams; sparse I/Q roughly every5s, fixed16MS/s. No clock alignment or continuous I/Q;600s restarts introduce gaps.'
            )
        seconds = self.duration.currentData()
        verb = (
            'Start test signal'
            if task == 'test'
            else 'Compare receivers'
            if task == 'compare'
            else 'Start listening'
        )
        self.start_button.setText('Start simulation' if demo else verb)
        if self.session and self.session.is_alive():
            return
        self.start_button.setEnabled(error is None)
        save = 'session saved' if self.save.isChecked() else 'memory only · no files'
        duration_text = 'until stopped' if seconds is None else f'{seconds}s'
        self.plan.setText(
            error
            or f'{"SIMULATION · " if demo else ""}{rx} receiver(s) · {self.frequency.value()} MHz · {duration_text} · {save}'
            + (
                f' · {tx} transmitter(s), {self.tx_power.currentData()} dBm'
                if tx
                else ' · receive only'
            )
        )
        if task == 'test' and tx > 1 and not error:
            self.plan.setText(
                self.plan.text()
                + '\nMultiple transmitters may interfere; results are not source attribution.'
            )

    def start_session(self) -> None:
        if self.session and self.session.is_alive():
            return
        self.update_plan()
        if not self.start_button.isEnabled():
            return
        demo = self.demo.isChecked()
        task = self.task.currentData()
        rx, tx = [], []
        for d in self.device_rows:
            if not d['check'].isChecked():
                continue
            if d['kind'] == 'receiver':
                s = dict(
                    mode='raw' if demo else self.mode.currentData(),
                    frequency_mhz=self.frequency.value(),
                    rate_hz=self.rate.currentData(),
                    gain=None if self.gain_mode.currentData() == 'agc' else self.gain.value(),
                    bandwidth_mhz=self.bandwidth.value(),
                    samples=self.samples.value(),
                    bits=10,
                    det_ms=self.run_ms.value(),
                    ratio_milli=round(self.ratio.value() * 1000),
                    background_policy=self.policy.currentData(),
                    candidate_count=1,
                    threshold_db=10,
                    autosave=self.save.isChecked(),
                    record_all=True,
                    scan=False,
                )
                rx.append(ReceiverConfig(d['label'], d['port'], s, demo))
            elif task == 'test' and not demo:
                tx.append(
                    TransmitterConfig(
                        d['label'],
                        d['port'],
                        d['serial'],
                        dict(
                            frequency_mhz=self.frequency.value(),
                            power_dbm=self.tx_power.currentData(),
                            mode_mbps=self.tx_mode.currentData(),
                            length=self.tx_length.value(),
                            interval_us=self.tx_interval.value(),
                            count=0,
                        ),
                    )
                )
        folder = Path(self.output.text()).expanduser() / datetime.now(timezone.utc).strftime(
            '%Y%m%dT%H%M%S%fZ'
        )
        try:
            session = LabSession(
                rx, tx, folder, self.duration.currentData(), persist=self.save.isChecked()
            )
        except Exception as error:
            self.banner.setText(f'Could not start: {error}')
            return
        self.session = session
        self.finished_session = None
        self.last_output = folder if self.save.isChecked() else None
        self.latest.clear()
        self.arrivals.clear()
        self.views.clear()
        self.rx_select.clear()
        self.log.clear()
        while self.views_layout.count():
            item = self.views_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.combined = CombinedView()
        self.views_layout.addWidget(self.combined, 0, 0, 1, 2)
        for i, receiver in enumerate(rx):
            view = ReceiverView(receiver.label, COLORS[i % len(COLORS)])
            self.views_layout.addWidget(view, 1 + i // 2, i % 2)
            self.views[receiver.label] = view
            self.rx_select.addItem(receiver.label)
        self.update_display_mode()
        self.live_title.setText('Simulated session' if demo else TASKS[task][0])
        self.live_hint.setText(
            f'{self.frequency.value()} MHz · {self.duration.currentText()} · {"synthetic data, no hardware" if demo else ("independent sparse I/Q · experimental, not continuous" if self.mode.currentData() == "DSTREAMIQ" else "independent burst receivers")}'
        )
        self.banner.setText('Connecting receivers…')
        self.tx_status.setText(
            'Waiting for receivers before transmitting'
            if tx
            else 'No transmission requested · receive-only session'
        )
        self.progress.setValue(0)
        self.progress.setFormat('Connecting…')
        self.setup.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.folder_button.setEnabled(False)
        self.inspect_button.setEnabled(False)
        self.tabs.setCurrentIndex(1)
        session.start()

    def stop_session(self) -> None:
        if self.session and self.session.is_alive():
            self.session.stop()
            self.banner.setText('Stopping · waiting for device acknowledgements')
            self.stop_button.setEnabled(False)

    def poll(self) -> None:
        session = self.session
        if not session:
            return
        for _ in range(200):
            try:
                kind, value = session.notices.get_nowait()
            except queue.Empty:
                break
            self.log.appendPlainText(f'{kind}: {value}')
            if kind == 'transmitter':
                status = value['status']
                self.tx_status.setText(
                    f'{value["label"]}: {"transmitting" if status.get("running") else "not transmitting"} · {status.get("completed", 0):,} completed packets'
                )
        for name, frames in list(session.frames.items()):
            if not frames:
                continue
            capture, _, stats = frames.pop()
            frames.clear()
            if capture is not None:
                if self.latest.get(name) is not capture:
                    self.arrivals[name] = time.monotonic()
                self.latest[name] = capture
            self.views[name].update_capture(capture, stats)
        if self.combined and self.finished_session is not session:
            self.combined.update_inputs(
                {name: (capture, self.arrivals[name]) for name, capture in self.latest.items()}
            )
        self.inspect_button.setEnabled(bool(self.latest))
        if session.is_alive():
            for view in self.views.values():
                view.refresh_age()
            start = session.manifest.get('run_started_monotonic_ns')
            if start and session.state == 'running':
                elapsed = max(0, (time.monotonic_ns() - start) / 1e9)
                if session.duration_s is None:
                    self.progress.setValue(0)
                    self.progress.setFormat(f'{elapsed:.0f}s elapsed · runs until stopped')
                else:
                    self.progress.setValue(min(1000, round(1000 * elapsed / session.duration_s)))
                    self.progress.setFormat(
                        f'{max(0, session.duration_s - elapsed):.1f}s remaining'
                    )
                self.banner.setText(
                    'Running · transmitter enabled'
                    if session.transmitters
                    else 'Running · listening only'
                )
            elif session.state == 'stopping':
                self.banner.setText('Stopping · waiting for device acknowledgements')
                self.progress.setFormat('Finishing and saving…')
            return
        if self.finished_session is not session:
            self.finished_session = session
            title, detail = describe_result(session.manifest)
            self.banner.setText(title)
            self.live_title.setText(title)
            self.tx_status.setText(detail)
            self.progress.setFormat(title)
            if session.state == 'complete':
                self.progress.setValue(1000)
            self.setup.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.folder_button.setEnabled(bool(self.last_output and self.last_output.exists()))
            self.history_root = Path(self.output.text()).expanduser()
            self.refresh_history()
            self.update_plan()
            for view in self.views.values():
                view.status.setText('Stopped · last capture')
            if self.combined:
                self.combined.status.setText('Stopped · last combined display')
        if self.closing:
            self.close()

    def update_display_mode(self) -> None:
        mode = self.display_mode.currentData()
        if self.combined:
            self.combined.setVisible(mode in ('combined', 'both'))
        for view in self.views.values():
            view.setVisible(mode in ('individual', 'both'))

    def inspect_latest(self) -> None:
        capture = self.latest.get(self.rx_select.currentText())
        if capture is not None:
            self.inspect(capture)

    def inspect(self, capture) -> None:
        dialog = InspectionWindow(capture, self)
        self.dialogs.append(dialog)
        dialog.finished.connect(
            lambda: self.dialogs.remove(dialog) if dialog in self.dialogs else None
        )
        dialog.show()

    def refresh_history(self) -> None:
        self.history = session_history(self.history_root)
        self.history_list.clear()
        self.history_path.setText(str(self.history_root))
        for folder, doc in self.history:
            title, _ = describe_result(doc)
            receivers = doc.get('receivers', [])
            if not isinstance(receivers, list) or any(not isinstance(r, dict) for r in receivers):
                mode = 'Unknown device data'
            elif any(r.get('demo') is True for r in receivers):
                mode = 'Simulation'
            else:
                mode = 'Hardware'
            self.history_list.addItem(f'{folder.name}\n{mode} · {title}')
        if self.history:
            self.history_list.setCurrentRow(0)
        else:
            self.history_summary.setText(
                'No sessions here yet. Start a session, or choose an existing RF Bench recordings folder.'
            )
            self.capture_list.clear()

    def choose_history(self) -> None:
        path = W.QFileDialog.getExistingDirectory(
            self, 'Choose recordings folder', str(self.history_root)
        )
        if path:
            self.history_root = Path(path)
            self.refresh_history()

    def select_history(self, index: int) -> None:
        self.capture_list.clear()
        if not 0 <= index < len(self.history):
            return
        folder, doc = self.history[index]
        title, detail = describe_result(doc)
        results = doc.get('receiver_results', {})

        def count(value) -> str:
            return f'{value:,}' if type(value) is int and value >= 0 else 'unknown'

        if not isinstance(results, dict):
            text = 'Receiver results unavailable: invalid session data.'
        else:
            lines = []
            for name, result in results.items():
                if not isinstance(result, dict):
                    lines.append(f'{name}: receiver results unavailable')
                    continue
                lines.append(
                    f'{name}: {count(result.get("captures"))} captures, '
                    f'{count(result.get("retained"))} detector events retained'
                )
            text = '\n'.join(lines)
        files = sorted(folder.glob('rx-*/*.sigmf-meta'))[:1000]
        self.history_summary.setText(
            f'{title}\n{detail}\n{text}\n{len(files)} saved I/Q files shown (up to 1,000).'
        )
        for path in files:
            item = W.QListWidgetItem(f'{path.parent.name}  ·  {path.stem}')
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
            self.capture_list.addItem(item)
        if not files:
            self.capture_list.addItem(
                'No saved I/Q in this session. Run summaries may still be available in its folder.'
            )

    def open_saved_capture(self, item) -> None:
        path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if path:
            try:
                self.inspect(load_capture(path))
            except Exception as error:
                self.history_summary.setText(f'Cannot read capture: {error}')

    def open_recordings(self) -> None:
        if self.last_output and self.last_output.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.last_output)))

    def open_history_folder(self) -> None:
        index = self.history_list.currentRow()
        if 0 <= index < len(self.history):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.history[index][0])))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.session and self.session.is_alive():
            self.closing = True
            self.stop_session()
            event.ignore()
        else:
            for dialog in list(self.dialogs):
                dialog.close()
            event.accept()


def apply_theme(app: W.QApplication) -> None:
    app.setStyle('Fusion')
    app.setFont(QtGui.QFont('DejaVu Sans', 10))
    palette = QtGui.QPalette()
    for role, color in [
        (QtGui.QPalette.ColorRole.Window, '#10191f'),
        (QtGui.QPalette.ColorRole.WindowText, '#e3eaed'),
        (QtGui.QPalette.ColorRole.Base, '#152229'),
        (QtGui.QPalette.ColorRole.AlternateBase, '#1b2c34'),
        (QtGui.QPalette.ColorRole.Text, '#e3eaed'),
        (QtGui.QPalette.ColorRole.Button, '#22333c'),
        (QtGui.QPalette.ColorRole.ButtonText, '#e3eaed'),
        (QtGui.QPalette.ColorRole.Highlight, '#277b78'),
    ]:
        palette.setColor(role, QtGui.QColor(color))
    app.setPalette(palette)
    app.setStyleSheet("""
        QLabel#title {font-size:28px; font-weight:700;} QLabel#heading {font-size:18px; font-weight:600; margin:8px 0;}
        QLabel#subtitle {font-size:16px; font-weight:600;} QLabel#muted {color:#a8bac3;}
        QLabel#status {color:#6fe0ce;} QLabel#warning {color:#edc37d;}
        QLabel#empty {font-size:18px; color:#8da6b2; padding:60px;}
        QFrame#card {background:#18272f; border:1px solid #2b414d; border-radius:10px; padding:8px;}
        QGroupBox {border:1px solid #2b414d; border-radius:10px; margin-top:14px; padding:18px 12px 12px; font-weight:600;}
        QGroupBox::title {subcontrol-origin:margin; left:12px; padding:0 6px;}
        QPushButton {padding:9px 16px; border:1px solid #38505d; border-radius:6px;}
        QPushButton:hover {background:#2c4652;} QPushButton:disabled {color:#647983; border-color:#263a43;}
        QPushButton#primary {background:#267f76; border-color:#37a494; font-weight:600;}
        QPushButton#primary:hover {background:#32988b;} QPushButton#primary:disabled {background:#22383b; color:#78908f;}
        QPushButton#danger:enabled {background:#803f45; border-color:#b6666c;}
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {padding:7px; min-height:22px; border:1px solid #38505d; border-radius:5px;}
        QTabBar::tab {padding:12px 22px; margin-right:8px; color:#93aab6;}
        QTabBar::tab:selected {color:#67dbcb; border-bottom:2px solid #67dbcb;}
        QProgressBar {border:1px solid #2b414d; border-radius:5px; height:24px; text-align:center;}
        QProgressBar::chunk {background:#267f76;}
        QListWidget::item {padding:10px;} QCheckBox {spacing:8px; padding:4px 0;}
    """)
    pg.setConfigOptions(background='#142028', foreground='#acbdc6', antialias=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args(argv)
    app = W.QApplication.instance() or W.QApplication([])
    apply_theme(app)
    window = StudioWindow(args.demo)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
