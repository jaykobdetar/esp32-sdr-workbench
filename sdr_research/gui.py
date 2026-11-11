"""Native Ubuntu research viewer; serial acquisition never runs on the GUI thread."""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .analysis import NoiseCalibration, detect_event, spectrum
from .detector import run_detection
from .pipeline import run_pipeline, select_acquisition_policy
from .protocol import Capture, Radio
from .recording import load_capture, save_capture

DETECTOR_MODES = ('DET1', 'DETPIPE1')


class AcquisitionWorker(QtCore.QThread):
    """One owner per serial connection; bounded rendering and event-notice queues."""

    def __init__(self, port, settings, output_dir, demo=False):
        super().__init__()
        self.port, self.settings, self.output_dir = port, dict(settings), Path(output_dir)
        self.demo = demo
        self.stop_requested = threading.Event()
        self.frames = deque(maxlen=2)
        self.notices = queue.Queue(maxsize=256)
        self.render_drops = 0
        self.event_notices_dropped = 0
        self.capture_count = 0
        self.run_count = 0
        self.candidate_count = 0
        self.retained_count = 0
        self.analyzed_s = 0.0
        self.decision_s = 0.0
        self.nominal_rf_s = 0.0
        self.started_ns = 0
        self.last_end_ns = None
        self.occupancy_counts = {}
        self.rng = np.random.default_rng()

    def notice(self, kind, value):
        try:
            self.notices.put_nowait((kind, value))
        except queue.Full:
            self.event_notices_dropped += 1

    def stop(self):
        self.stop_requested.set()

    def demo_capture(self, frequency):
        s = self.settings
        n, rate = s['samples'], s['rate_hz']
        start = time.monotonic_ns()
        iq = (self.rng.normal(0, 0.008, n) + 1j * self.rng.normal(0, 0.008, n)).astype(np.complex64)
        if self.capture_count % 5 in (0, 1):
            left, right = n // 4, 3 * n // 4
            t = np.arange(right - left) / rate
            iq[left:right] += 0.16 * np.exp(2j * np.pi * 1_500_000 * t)
        self.stop_requested.wait(0.09)
        end = time.monotonic_ns()
        return Capture(
            iq=iq,
            sample_rate_hz=rate,
            frequency_hz=frequency * 1e6,
            timestamp=datetime.now(timezone.utc).isoformat(),
            monotonic_start_ns=start,
            monotonic_end_ns=end,
            firmware_capture_us=round(n / rate * 1e6),
            bits=s['bits'],
            crc_ok=True,
            metadata={'synthetic': True, 'device': self.port},
        )

    def detector_run(self, radio, frequency):
        """One bounded run; JSON is preserved even when no IQ was retained."""
        s = self.settings
        mode = s.get('mode', 'DET1')
        if mode == 'DETPIPE1':
            summary, capture = run_pipeline(
                radio,
                milliseconds=s['det_ms'],
                samples=s['samples'],
                rate_hz=s['rate_hz'],
                ratio_milli=s['ratio_milli'],
                retain=True,
                kernel=3,
                optimized=True,
                copy_option=1 if 'PIPECOPY' in radio.info.get('caps', []) else None,
            )
        else:
            policies = select_acquisition_policy(radio, False)
            summary, capture = run_detection(
                radio,
                milliseconds=s['det_ms'],
                samples=s['samples'],
                rate_hz=s['rate_hz'],
                ratio_milli=s['ratio_milli'],
                retain=True,
            )
            summary['acquisition_policies'] = policies
        self.run_count += 1
        self.capture_count += summary['captures']
        self.candidate_count += summary.get('detections', 0)
        self.retained_count += int(capture is not None)
        rate = summary['sample_rate_hz']
        self.nominal_rf_s += summary['total_samples'] / rate
        self.analyzed_s += summary['analyzed_samples'] / rate
        decided = max(
            0, summary['captures'] - summary.get('warmup_captures', min(summary['captures'], 16))
        )
        self.decision_s += decided * (s['samples'] // 64) * 64 / rate
        hits, observations = self.occupancy_counts.get(frequency, (0, 0))
        self.occupancy_counts[frequency] = (
            hits + summary.get('detections', 0),
            observations + decided,
        )
        meta_path = None
        if capture is not None:
            # Exact event time is not supplied by DET1. This is a run-start reference.
            capture.metadata['timestamp_reference'] = (
                'detector run host start; exact event time unavailable'
            )
            capture.metadata['settings'] = dict(s)
        elapsed = max((time.monotonic_ns() - self.started_ns) / 1e9, 1e-9)
        summary = dict(summary)
        summary['gui_mode'] = mode
        summary['candidate_count_semantics'] = 'candidate-positive captures, not unique packets'
        summary['retained_semantics'] = 'at most one strongest candidate capture per finite run'
        summary['timestamp_reference'] = 'host run request time; exact event time unavailable'
        summary['host_session_nominal_rf_duty_percent'] = 100 * self.nominal_rf_s / elapsed
        summary['host_session_nominal_analyzed_duty_percent'] = 100 * self.analyzed_s / elapsed
        summary['host_session_nominal_decision_duty_percent'] = 100 * self.decision_s / elapsed
        if s['autosave']:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            base = (
                self.output_dir
                / f'{stamp}-{self.port.replace("/", "_")}-{mode}-{uuid.uuid4().hex[:8]}'
            )
            # Write summary first, so an IQ-save failure never discards this run.
            summary_path = Path(str(base) + f'.{mode.lower()}.json')
            summary['retained_sigmf'] = None
            with summary_path.open('x') as output:
                json.dump(summary, output, indent=2)
            try:
                if capture is not None:
                    meta_path = str(save_capture(capture, base))
                    summary['retained_sigmf'] = Path(meta_path).name
            except Exception as exc:
                summary['recording_error'] = str(exc)
                raise
            finally:
                recorded_elapsed = max((time.monotonic_ns() - self.started_ns) / 1e9, 1e-9)
                summary['host_session_elapsed_through_recording_s'] = recorded_elapsed
                summary['host_session_nominal_rf_duty_percent'] = (
                    100 * self.nominal_rf_s / recorded_elapsed
                )
                summary['host_session_nominal_analyzed_duty_percent'] = (
                    100 * self.analyzed_s / recorded_elapsed
                )
                summary['host_session_nominal_decision_duty_percent'] = (
                    100 * self.decision_s / recorded_elapsed
                )
                temporary = Path(str(summary_path) + '.tmp')
                with temporary.open('x') as output:
                    json.dump(summary, output, indent=2)
                temporary.replace(summary_path)
            self.notice('record', str(summary_path))
        elapsed = max((time.monotonic_ns() - self.started_ns) / 1e9, 1e-9)
        stats = {
            'mode': mode,
            'summary': summary,
            'count': self.capture_count,
            'runs': self.run_count,
            'candidates': self.candidate_count,
            'retained': self.retained_count,
            'nominal_duty': self.nominal_rf_s / elapsed,
            'analyzed_duty': self.analyzed_s / elapsed,
            'decision_duty': self.decision_s / elapsed,
            'elapsed': elapsed,
            'render_drops': self.render_drops,
            'occupancy': dict(self.occupancy_counts),
            'has_capture': capture is not None,
            'host_updated_ns': time.monotonic_ns(),
            'nominal_rf_s': self.nominal_rf_s,
            'analyzed_s': self.analyzed_s,
            'decision_s': self.decision_s,
        }
        if capture is not None:
            result = detect_event(
                capture.iq, capture.sample_rate_hz, threshold_db=s['threshold_db']
            )
            ratio = summary.get('best_ratio_milli')
            result['snr_db'] = (
                float(10 * np.log10(ratio / 1000)) if ratio and ratio > 0 else float('nan')
            )
            result.update(
                detector=f'{mode} strongest candidate/run',
                detected=True,
                timestamp_reference='host run start; exact event time unavailable',
            )
            self.notice('event', (capture, result, meta_path))
        if len(self.frames) == self.frames.maxlen:
            self.render_drops += 1
        self.frames.append((capture, summary, stats))
        if summary.get('status') or summary.get('errors') or summary.get('errors_received'):
            raise RuntimeError(
                f'{mode} ended with status {summary.get("status")}; summary recorded if recording enabled. Reconnect before retry.'
            )

    def run(self):
        radio = None
        self.started_ns = time.monotonic_ns()
        self.notice('state', 'SIMULATED input' if self.demo else 'Connecting…')
        try:
            s = self.settings
            if self.demo and s.get('mode') in DETECTOR_MODES:
                raise ValueError(
                    f'{s["mode"]} needs experimental hardware firmware. Demo is raw simulated IQ only; no fabricated {s["mode"]} performance is shown.'
                )
            if not self.demo:
                radio = Radio(self.port, baud=1_000_000)
                self.notice('info', radio.connect())
            frequencies = (
                list(range(s['scan_low'], s['scan_high'] + 1, s['scan_step']))
                if s['scan']
                else [s['frequency_mhz']]
            )
            previous_frequency = None
            self.started_ns = (
                time.monotonic_ns()
            )  # exclude connection negotiation from acquisition duty
            while not self.stop_requested.is_set():
                frequency = frequencies[self.run_count % len(frequencies)]
                if radio is not None and previous_frequency != frequency:
                    radio.configure(
                        frequency_mhz=frequency,
                        rate_hz=s['rate_hz'],
                        bandwidth_mhz=s['bandwidth_mhz'],
                        gain=s['gain'],
                        bits=s['bits'],
                    )
                    previous_frequency = frequency
                if s.get('mode') in DETECTOR_MODES:
                    self.detector_run(radio, frequency)
                    continue
                self.run_count += 1
                capture = self.demo_capture(frequency) if self.demo else radio.capture(s['samples'])
                self.capture_count += 1
                self.nominal_rf_s += len(capture.iq) / capture.sample_rate_hz
                elapsed = max((capture.monotonic_end_ns - self.started_ns) / 1e9, 1e-9)
                gap = (
                    None
                    if self.last_end_ns is None
                    else max(0.0, (capture.monotonic_start_ns - self.last_end_ns) / 1e6)
                )
                self.last_end_ns = capture.monotonic_end_ns
                result = detect_event(
                    capture.iq, capture.sample_rate_hz, threshold_db=s['threshold_db']
                )
                hits, observations = self.occupancy_counts.get(frequency, (0, 0))
                self.occupancy_counts[frequency] = (
                    hits + int(result.get('detected', False)),
                    observations + 1,
                )
                meta_path = None
                if result.get('detected'):
                    if s['autosave']:
                        self.output_dir.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                        safe_port = self.port.replace('/', '_')
                        meta_path = str(
                            save_capture(capture, self.output_dir / f'{stamp}-{safe_port}')
                        )
                    self.notice('event', (capture, result, meta_path))
                item = (
                    capture,
                    result,
                    {
                        'count': self.capture_count,
                        'nominal_duty': self.nominal_rf_s / elapsed,
                        'elapsed': elapsed,
                        'gap_ms': gap,
                        'render_drops': self.render_drops,
                        'occupancy': dict(self.occupancy_counts),
                    },
                )
                if len(self.frames) == self.frames.maxlen:
                    self.render_drops += 1
                self.frames.append(item)
        except Exception as exc:
            message = f'{type(exc).__name__}: {exc}'
            if self.settings.get('mode') in DETECTOR_MODES:
                message += ' · Detector mode requires compatible experimental firmware; nothing was flashed. Select Raw I/Q for existing firmware.'
            self.notice('error', message)
        finally:
            if radio is not None:
                try:
                    radio.close()
                except Exception as exc:
                    self.notice('error', f'Close: {exc}')
            self.notice('state', 'Stopped')


class InspectionWindow(QtWidgets.QDialog):
    def __init__(self, capture, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Capture inspection · no transmitter attribution')
        self.resize(1100, 760)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(
            f'{capture.timestamp} · {capture.frequency_hz / 1e6:.3f} MHz · '
            f'{capture.sample_rate_hz / 1e6:g} MS/s · {len(capture.iq):,} samples'
        )
        layout.addWidget(label)
        if capture.metadata.get('detector_summary'):
            layout.addWidget(
                QtWidgets.QLabel(
                    'Detector strongest retained capture. Timestamp is host run start, NOT exact RF event time.'
                )
            )
        plots = pg.GraphicsLayoutWidget()
        layout.addWidget(plots)
        iq = np.asarray(capture.iq)
        # Bound drawing cost for unusually large replay recordings.
        stride = max(1, len(iq) // 30000)
        t = np.arange(len(iq))[::stride] / capture.sample_rate_hz * 1e6
        p = plots.addPlot(title='Raw I/Q')
        p.setLabel('bottom', 'Time', units='µs')
        p.addLegend()
        p.plot(t, iq.real[::stride], pen='#58b9ff', name='I')
        p.plot(t, iq.imag[::stride], pen='#ffb454', name='Q')
        p = plots.addPlot(title='Power versus time')
        p.setLabel('bottom', 'Time', units='µs')
        p.setLabel('left', 'Power', units='dBFS')
        p.plot(t, 10 * np.log10(np.maximum(np.abs(iq[::stride]) ** 2, 1e-14)), pen='#83e1ab')
        plots.nextRow()
        p = plots.addPlot(title='FFT (mean DC removed)')
        p.setLabel('bottom', 'Frequency offset', units='MHz')
        p.setLabel('left', 'Power', units='dBFS')
        offsets, power = spectrum(
            iq, capture.sample_rate_hz, nfft=min(1024, len(iq)), remove_dc=True
        )
        p.plot(offsets / 1e6, power, pen='#58b9ff')
        p = plots.addPlot(title='Constellation · not a decoded modulation')
        p.setLabel('bottom', 'I')
        p.setLabel('left', 'Q')
        p.plot(
            iq.real[::stride],
            iq.imag[::stride],
            pen=None,
            symbol='o',
            symbolSize=2,
            symbolBrush='#58b9ff80',
        )
        p.setAspectLocked()
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(self.accept)
        layout.addWidget(close)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.setWindowTitle('ESP32 RF Research · burst receiver')
        self.resize(1420, 950)
        self.workers = {}
        self.worker_errors = {}
        self.latest = {}
        self.stats = {}
        self.averages, self.peaks, self.waterfalls = {}, {}, {}
        self.events = deque(maxlen=200)
        self.occupancy = {}  # frequency -> (hits, observations), never unsampled=quiet
        self.dialogs = []
        self.noise_baselines = {}
        self.noise_calibrations = {}
        self.occupancy_histories = {}
        self.replay_paths = []
        self.replay_index = 0
        self.closing = False
        self.output_dir = Path.cwd() / 'records'
        self.build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.replay_timer = QtCore.QTimer(self)
        self.replay_timer.setInterval(250)
        self.replay_timer.timeout.connect(self.replay_tick)
        if demo:
            self.demo.setChecked(True)

    def build_ui(self):
        outer = QtWidgets.QWidget()
        self.setCentralWidget(outer)
        root = QtWidgets.QVBoxLayout(outer)
        heading = QtWidgets.QLabel('ESP32 RF Research')
        light_theme = self.palette().color(QtGui.QPalette.ColorRole.Window).lightness() > 128
        heading.setStyleSheet(
            'font-size: 24px; font-weight: 600; color: '
            + ('#075985' if light_theme else '#7dd3fc')
            + ';'
        )
        root.addWidget(heading)
        warning = QtWidgets.QLabel(
            'Burst sampling, not continuous capture. RF events are unclassified. dBFS is not calibrated dBm; nominal RF duty is an estimate, not measured detector coverage.'
        )
        warning.setWordWrap(True)
        warning.setStyleSheet('color: ' + ('#855309' if light_theme else '#e3bd78') + ';')
        root.addWidget(warning)
        controls = QtWidgets.QGroupBox('Acquisition · settings apply on Start')
        root.addWidget(controls)
        grid = QtWidgets.QGridLayout(controls)
        self.port = QtWidgets.QLineEdit('/dev/ttyUSB0')
        self.port.setPlaceholderText('Ports separated by commas; optional @MHz per device')
        self.port.setToolTip(
            'One acquisition worker per port. Example: /dev/ttyUSB0@2440,/dev/ttyUSB1@2480. A frequency suffix pins that receiver even if survey is enabled. No synchronized timing is claimed.'
        )
        grid.addWidget(QtWidgets.QLabel('Ports'), 0, 0)
        grid.addWidget(self.port, 0, 1, 1, 3)
        self.demo = QtWidgets.QCheckBox('SIMULATED demo')
        grid.addWidget(self.demo, 0, 4)
        self.start_button = QtWidgets.QPushButton('Start')
        self.start_button.clicked.connect(self.start_acquisition)
        grid.addWidget(self.start_button, 0, 5)
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.stop_button.clicked.connect(self.stop_acquisition)
        self.stop_button.setEnabled(False)
        grid.addWidget(self.stop_button, 0, 6)
        self.frequency = QtWidgets.QSpinBox()
        self.frequency.setRange(2400, 2500)
        self.frequency.setValue(2440)
        self.frequency.setSuffix(' MHz')
        self.rate = QtWidgets.QComboBox()
        for rate in (16, 40, 80):
            self.rate.addItem(f'{rate} MS/s', rate * 1_000_000)
        self.bandwidth = QtWidgets.QSpinBox()
        self.bandwidth.setRange(0, 67)
        self.bandwidth.setValue(0)
        self.bandwidth.setSuffix(' MHz')
        self.bandwidth.setToolTip(
            '0 = widest; firmware validates available analog bandwidth values.'
        )
        self.gain = QtWidgets.QSpinBox()
        self.gain.setRange(-1, 81)
        self.gain.setValue(-1)
        self.gain.setSpecialValueText('Hardware AGC')
        self.gain.setToolTip(
            'Manual gain is a PHY table index, not dB. Unsupported indices are rejected by firmware.'
        )
        self.bits = QtWidgets.QComboBox()
        self.bits.addItem('8-bit I/Q (CAP16)', 8)
        self.bits.addItem('10-bit I/Q (CAP20)', 10)
        self.samples = QtWidgets.QSpinBox()
        self.samples.setRange(256, 16380)
        self.samples.setValue(16380)
        self.samples.setSingleStep(256)
        fields = [
            ('Center', self.frequency),
            ('Rate', self.rate),
            ('Bandwidth', self.bandwidth),
            ('Gain index', self.gain),
            ('Format', self.bits),
            ('Samples', self.samples),
        ]
        for col, (name, widget) in enumerate(fields):
            grid.addWidget(QtWidgets.QLabel(name), 1, col)
            grid.addWidget(widget, 2, col)
        self.scan = QtWidgets.QCheckBox('Frequency survey')
        grid.addWidget(self.scan, 3, 0)
        self.scan_low = QtWidgets.QSpinBox()
        self.scan_low.setRange(2400, 2500)
        self.scan_low.setValue(2402)
        self.scan_low.setPrefix('From ')
        self.scan_high = QtWidgets.QSpinBox()
        self.scan_high.setRange(2400, 2500)
        self.scan_high.setValue(2480)
        self.scan_high.setPrefix('To ')
        self.scan_step = QtWidgets.QSpinBox()
        self.scan_step.setRange(1, 100)
        self.scan_step.setValue(4)
        self.scan_step.setSuffix(' MHz step')
        grid.addWidget(self.scan_low, 3, 1)
        grid.addWidget(self.scan_high, 3, 2)
        grid.addWidget(self.scan_step, 3, 3)
        self.threshold = QtWidgets.QDoubleSpinBox()
        self.threshold.setRange(1, 60)
        self.threshold.setValue(10)
        self.threshold.setSuffix(' dB')
        self.threshold.setToolTip(
            'Heuristic within-capture SNR threshold, not a calibrated sensitivity guarantee.'
        )
        grid.addWidget(QtWidgets.QLabel('Event threshold'), 3, 4)
        grid.addWidget(self.threshold, 3, 5)
        self.autosave = QtWidgets.QCheckBox('Save detected events')
        grid.addWidget(self.autosave, 3, 6)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem('Raw I/Q', 'raw')
        self.mode.addItem('DET1 autonomous detector', 'DET1')
        self.mode.addItem('Experimental optimized pipeline', 'DETPIPE1')
        self.det_ms = QtWidgets.QSpinBox()
        self.det_ms.setRange(1, 5000)
        self.det_ms.setValue(1000)
        self.det_ms.setSuffix(' ms / run')
        self.det_ratio = QtWidgets.QDoubleSpinBox()
        self.det_ratio.setRange(1, 1000)
        self.det_ratio.setDecimals(3)
        self.det_ratio.setValue(4)
        self.det_ratio.setSuffix(' × power')
        self.det_ratio.setToolTip(
            'Detector power/background ratio, not amplitude or dB. Background warms up for 16 captures at each run.'
        )
        grid.addWidget(QtWidgets.QLabel('Mode'), 4, 0)
        grid.addWidget(self.mode, 4, 1, 1, 2)
        grid.addWidget(self.det_ms, 4, 3)
        grid.addWidget(self.det_ratio, 4, 4)
        det_note = QtWidgets.QLabel('Detector: one strongest IQ/run; exact event time unavailable')
        det_note.setWordWrap(True)
        grid.addWidget(det_note, 4, 5, 1, 2)
        self.autosave.setText('Record events / detector runs')
        self.autosave.setToolTip(
            'Raw: save candidate IQ. Detector: save every run summary, including no event, and strongest retained IQ when present.'
        )
        self.mode.currentIndexChanged.connect(self.update_mode_controls)
        self.update_mode_controls()
        display = QtWidgets.QHBoxLayout()
        root.addLayout(display)
        self.device_view = QtWidgets.QComboBox()
        self.device_view.currentTextChanged.connect(self.redraw_selected)
        display.addWidget(QtWidgets.QLabel('Display device'))
        display.addWidget(self.device_view)
        self.avg = QtWidgets.QSpinBox()
        self.avg.setRange(1, 100)
        self.avg.setValue(4)
        display.addWidget(QtWidgets.QLabel('FFT EMA depth'))
        display.addWidget(self.avg)
        self.peak_hold = QtWidgets.QCheckBox('Peak hold')
        display.addWidget(self.peak_hold)
        self.remove_dc = QtWidgets.QCheckBox('Remove mean DC')
        self.remove_dc.setChecked(True)
        display.addWidget(self.remove_dc)
        calibrate = QtWidgets.QPushButton('Set idle reference')
        calibrate.clicked.connect(self.calibrate_noise)
        display.addWidget(calibrate)
        self.relative_noise = QtWidgets.QCheckBox('Above reference')
        display.addWidget(self.relative_noise)
        reset = QtWidgets.QPushButton('Reset display')
        reset.clicked.connect(self.reset_display)
        display.addWidget(reset)
        actions = QtWidgets.QHBoxLayout()
        root.addLayout(actions)
        actions.addStretch()
        save = QtWidgets.QPushButton('Save latest IQ')
        save.clicked.connect(self.save_latest)
        actions.addWidget(save)
        inspect = QtWidgets.QPushButton('Inspect latest')
        inspect.clicked.connect(self.inspect_latest)
        actions.addWidget(inspect)
        load = QtWidgets.QPushButton('Replay SigMF…')
        load.clicked.connect(self.open_replay)
        actions.addWidget(load)
        self.replay_button = QtWidgets.QPushButton('Pause replay')
        self.replay_button.clicked.connect(self.toggle_replay)
        actions.addWidget(self.replay_button)
        folder = QtWidgets.QPushButton('Recording folder…')
        folder.clicked.connect(self.choose_folder)
        actions.addWidget(folder)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        root.addWidget(splitter, 1)
        plot_area = pg.GraphicsLayoutWidget()
        splitter.addWidget(plot_area)
        self.spectrum_plot = plot_area.addPlot(title='Spectrum')
        self.spectrum_plot.setLabel('left', 'Power', 'dBFS')
        self.spectrum_plot.setLabel('bottom', 'Frequency', 'MHz')
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.2)
        self.spectrum_curve = self.spectrum_plot.plot(pen=pg.mkPen('#72d3ff', width=1.5))
        self.peak_curve = self.spectrum_plot.plot(pen='#ffbf69')
        plot_area.nextRow()
        self.waterfall_plot = plot_area.addPlot(
            title='Waterfall · one row per displayed capture, NOT uniform RF time'
        )
        self.waterfall_plot.setLabel('left', 'Displayed capture history')
        self.waterfall_plot.setLabel('bottom', 'Frequency', 'MHz')
        self.waterfall_image = pg.ImageItem(axisOrder='row-major')
        self.waterfall_plot.addItem(self.waterfall_image)
        self.waterfall_image.setLookupTable(pg.colormap.get('viridis').getLookupTable())
        self.waterfall_plot.setXLink(self.spectrum_plot)
        for plot in (self.spectrum_plot, self.waterfall_plot):
            axis = plot.getAxis('bottom')
            # pyqtgraph 0.14 retains a stale scale when merely disabling auto-SI.
            if hasattr(axis, 'setSIPrefixEnableRanges'):
                axis.setSIPrefixEnableRanges(())
            axis.enableAutoSIPrefix(False)
        tabs = QtWidgets.QTabWidget()
        splitter.addWidget(tabs)
        self.event_table = QtWidgets.QTableWidget(0, 7)
        self.event_table.setHorizontalHeaderLabels(
            [
                'Host UTC reference¹',
                'Device',
                'MHz',
                'Peak dBFS',
                'Ratio dB²',
                'BW kHz',
                'Saved capture',
            ]
        )
        self.event_table.horizontalHeaderItem(0).setToolTip(
            'Raw: host capture request time. Detector: host finite-run start, not exact event arrival.'
        )
        self.event_table.horizontalHeaderItem(4).setToolTip(
            'Uncalibrated power ratio: raw within-capture peak/floor; Detector strongest local background ratio. Not calibrated RF SNR.'
        )
        self.event_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.event_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.event_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.event_table.cellDoubleClicked.connect(self.inspect_event)
        tabs.addTab(self.event_table, 'RF events · double-click to inspect')
        occupancy_widget = pg.PlotWidget(
            title='Observed event fraction by tuned center frequency · blank = not sampled'
        )
        occupancy_widget.setLabel('bottom', 'Center frequency (MHz)')
        occupancy_widget.setLabel('left', 'Detected / observed')
        occupancy_widget.setYRange(0, 1)
        self.occupancy_plot = occupancy_widget
        self.occupancy_bars = pg.BarGraphItem(x=[], height=[], width=0.8, brush='#7dd3fc')
        occupancy_widget.addItem(self.occupancy_bars)
        occupancy_tab = QtWidgets.QWidget()
        occupancy_layout = QtWidgets.QVBoxLayout(occupancy_tab)
        occupancy_layout.addWidget(occupancy_widget)
        self.occupancy_map = pg.PlotWidget(
            title='Cumulative occupancy heatmap · blank = unobserved, not quiet'
        )
        self.occupancy_map.setLabel('bottom', 'Center frequency (MHz)')
        self.occupancy_map.setLabel('left', 'Display update history')
        self.occupancy_image = pg.ImageItem(axisOrder='row-major')
        self.occupancy_image.setLookupTable(pg.colormap.get('viridis').getLookupTable())
        self.occupancy_map.addItem(self.occupancy_image)
        occupancy_layout.addWidget(self.occupancy_map)
        tabs.addTab(occupancy_tab, 'Frequency occupancy (heuristic)')
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        tabs.addTab(self.log, 'Session log')
        splitter.setSizes([560, 220])
        self.status_label = QtWidgets.QLabel('Idle. No hardware modified.')
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def update_mode_controls(self):
        det = self.mode.currentData() in DETECTOR_MODES
        self.det_ms.setEnabled(det)
        self.det_ratio.setEnabled(det)
        self.bits.setEnabled(not det)
        self.threshold.setEnabled(not det)
        if det:
            self.bits.setCurrentIndex(1)

    def settings(self):
        return dict(
            mode=self.mode.currentData(),
            det_ms=self.det_ms.value(),
            ratio_milli=round(self.det_ratio.value() * 1000),
            frequency_mhz=self.frequency.value(),
            rate_hz=self.rate.currentData(),
            bandwidth_mhz=self.bandwidth.value(),
            gain=None if self.gain.value() < 0 else self.gain.value(),
            bits=self.bits.currentData(),
            samples=self.samples.value(),
            threshold_db=self.threshold.value(),
            autosave=self.autosave.isChecked(),
            scan=self.scan.isChecked(),
            scan_low=self.scan_low.value(),
            scan_high=self.scan_high.value(),
            scan_step=self.scan_step.value(),
        )

    def start_acquisition(self):
        if any(w.isRunning() for w in self.workers.values()):
            return
        self.replay_timer.stop()
        self.replay_paths = []
        s = self.settings()
        if s['scan'] and s['scan_low'] > s['scan_high']:
            self.show_error('Scan start must not exceed scan end.')
            return
        ports = (
            ['SIMULATED']
            if self.demo.isChecked()
            else list(dict.fromkeys(p.strip() for p in self.port.text().split(',') if p.strip()))
        )
        if not ports:
            self.show_error('Enter at least one serial port.')
            return
        self.workers.clear()
        self.worker_errors.clear()
        self.noise_baselines.clear()
        self.noise_calibrations.clear()
        self.occupancy_histories.clear()
        self.latest.clear()
        self.stats.clear()
        self.device_view.clear()
        self.reset_display()
        assignments = []
        for entry in ports:
            port = entry
            local_settings = dict(s)
            if not self.demo.isChecked() and '@' in entry:
                port, frequency = entry.rsplit('@', 1)
                try:
                    frequency = int(frequency)
                    if not 2400 <= frequency <= 2500:
                        raise ValueError()
                except ValueError:
                    self.show_error(
                        'Per-device center frequencies must be whole MHz from 2400 to 2500.'
                    )
                    return
                local_settings['frequency_mhz'] = frequency
                local_settings['scan'] = False
            if not port or any(existing[0] == port for existing in assignments):
                self.show_error('Each physical serial port may appear only once.')
                return
            assignments.append((port, local_settings))
        for port, local_settings in assignments:
            worker = AcquisitionWorker(port, local_settings, self.output_dir, self.demo.isChecked())
            self.workers[port] = worker
            self.device_view.addItem(port)
            worker.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.log.appendPlainText(
            f'Starting {len(ports)} independent receiver(s). Output: {self.output_dir}'
        )
        self.status_label.setText(
            f'Starting {s["mode"]} · live statistics refresh after each {s["det_ms"]} ms finite run plus retained transfer. No auto-flash.'
            if s['mode'] in DETECTOR_MODES
            else 'Starting raw I/Q acquisition…'
        )

    def stop_acquisition(self):
        self.replay_timer.stop()
        for worker in self.workers.values():
            worker.stop()
        self.stop_button.setEnabled(False)
        det = [
            w.settings.get('det_ms', 0)
            for w in self.workers.values()
            if w.settings.get('mode') in DETECTOR_MODES and w.isRunning()
        ]
        self.status_label.setText(
            f'Stopping after current {self.mode.currentData()} run (up to {max(det) / 1000:g} s), retained transfer and bounded serial timeout; no mid-run abort…'
            if det
            else 'Stopping after current bounded serial operation…'
        )

    def poll(self):
        for port, worker in list(self.workers.items()):
            while True:
                try:
                    kind, value = worker.notices.get_nowait()
                except queue.Empty:
                    break
                if kind == 'event':
                    self.add_event(port, *value)
                else:
                    self.log.appendPlainText(f'{port}: {kind}: {value}')
                    if kind == 'error':
                        self.worker_errors[port] = value
            newest = None
            while worker.frames:
                try:
                    newest = worker.frames.popleft()
                except IndexError:
                    break
            if newest is not None:
                capture, result, stats = newest
                self.stats[port] = stats
                if capture is not None:
                    self.latest[port] = capture
                if self.device_view.currentText() == port:
                    if capture is not None:
                        self.render(port, capture)
                    if stats.get('mode') in DETECTOR_MODES and capture is None:
                        self.render_detector_status(port, stats, False)
            if worker.event_notices_dropped:
                self.status_label.setToolTip(
                    f'{worker.event_notices_dropped} UI event notices dropped; autosave occurred before notice enqueue.'
                )
        if self.workers and not any(w.isRunning() for w in self.workers.values()):
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            if self.worker_errors:
                self.status_label.setText(
                    'Stopped · ' + '; '.join(f'{p}: {e}' for p, e in self.worker_errors.items())
                )
            elif not self.status_label.text().startswith('Stopped') and not self.replay_paths:
                self.status_label.setText('Stopped · ' + self.status_label.text())
            if self.closing:
                self.close()

    def render_detector_status(self, port, stats, has_capture=False):
        summary = stats['summary']
        mode = stats.get('mode', 'DET1')
        policy = ' · Experimental K3 / ACQ3 / CLEAR1' if mode == 'DETPIPE1' else ''
        if mode == 'DETPIPE1':
            cp = summary.get('copy_policy', {})
            policy += (
                f' / COPY{cp["returned"]} (fused {summary.get("fused_active", 0)})'
                if cp.get('returned') is not None
                else ' / copy legacy (not selected)'
            )
        self.spectrum_plot.setTitle(
            f'{mode} · last retained strongest IQ, NOT live samples'
            if port in self.latest
            else f'{mode} · no retained IQ yet; monitoring summaries'
        )
        self.render_occupancy(stats, port)
        self.occupancy_plot.setTitle(
            f'{mode} candidate-positive / post-warmup captures · NOT packet occupancy'
        )
        self.status_label.setText(
            f'{port} · {mode}{policy} run {stats["runs"]} · {summary["frequency_mhz"]} MHz · '
            f'local nominal RF/analyzed/post-warmup decision duty {summary["nominal_rf_duty_percent"]:.2f}% / {summary["nominal_analyzed_duty_percent"]:.2f}% / {summary["nominal_decision_duty_percent"]:.2f}% · '
            f'host-session duty {stats["nominal_duty"] * 100:.2f}% / {stats["analyzed_duty"] * 100:.2f}% / {stats["decision_duty"] * 100:.2f}% (includes transfer/recording/gaps) · '
            f'{stats["candidates"]} candidate-positive captures, {stats["retained"]} retained strongest/run; NOT unique packets · '
            f'last run: {summary.get("detections", 0)} candidates, {"IQ retained" if has_capture else "no IQ retained"} · exact event time unknown'
        )

    def spectrum_key(self, port, capture, nfft):
        settings = getattr(capture, 'metadata', {}).get('settings', {})
        return (
            port,
            capture.frequency_hz,
            capture.sample_rate_hz,
            nfft,
            self.remove_dc.isChecked(),
            capture.bits,
            settings.get('gain'),
            settings.get('bandwidth_mhz'),
        )

    def render(self, port, capture):
        nfft = min(1024, len(capture.iq))
        offsets, power = spectrum(
            capture.iq, capture.sample_rate_hz, nfft=nfft, remove_dc=self.remove_dc.isChecked()
        )
        key = self.spectrum_key(port, capture, nfft)
        # Bound retained per-frequency graphics state for lengthy scans.
        if len(self.averages) > 128:
            self.averages.clear()
            self.peaks.clear()
            self.waterfalls.clear()
        linear = 10 ** (power / 10)
        average = self.averages.get(key, linear)
        average = average + (linear - average) / self.avg.value()
        self.averages[key] = average
        shown = 10 * np.log10(np.maximum(average, 1e-14))
        peak = np.maximum(self.peaks.get(key, power), power)
        self.peaks[key] = peak
        freqs = (offsets + capture.frequency_hz) / 1e6
        baseline = self.noise_baselines.get(key)
        relative = self.relative_noise.isChecked() and baseline is not None
        if relative:
            shown = shown - baseline
            peak = peak - baseline
        self.spectrum_plot.setLabel(
            'left', 'Above idle reference' if relative else 'Power', 'dB' if relative else 'dBFS'
        )
        self.spectrum_curve.setData(freqs, shown)
        self.peak_curve.setData(
            freqs, peak if self.peak_hold.isChecked() else np.full_like(peak, np.nan)
        )
        history = self.waterfalls.setdefault(key, deque(maxlen=100))
        history.append(power)
        data = np.asarray(history)
        self.waterfall_image.setImage(data, autoLevels=False, levels=(-100, 0))
        spacing = capture.sample_rate_hz / nfft / 1e6
        self.waterfall_image.setRect(
            QtCore.QRectF(
                float(freqs[0] - spacing / 2), -len(history), float(spacing * nfft), len(history)
            )
        )
        self.waterfall_plot.setYRange(-100, 0, padding=0)
        # Linked empty ImageItem ranges can disable x auto-ranging before data arrives.
        # Always establish the physical capture span explicitly, not the startup range.
        low = (capture.frequency_hz - capture.sample_rate_hz / 2) / 1e6
        high = (capture.frequency_hz + capture.sample_rate_hz / 2) / 1e6
        self.spectrum_plot.setXRange(low, high, padding=0)
        self.waterfall_plot.setXRange(low, high, padding=0)
        stats = self.stats.get(port)
        self.render_occupancy(stats, port)
        synthetic = bool(getattr(capture, 'metadata', {}).get('synthetic'))
        if stats and stats.get('mode') in DETECTOR_MODES:
            self.render_detector_status(port, stats, stats.get('has_capture', False))
        elif stats:
            self.occupancy_plot.setTitle(
                'Raw within-capture candidate fraction · blank = not sampled'
            )
            nominal_us = len(capture.iq) / capture.sample_rate_hz * 1e6
            transaction_ms = (capture.monotonic_end_ns - capture.monotonic_start_ns) / 1e6
            # Firmware duration can include setup, not simply RF sampling.
            self.status_label.setText(
                f'{"SIMULATED · " if synthetic else ""}{port} · {stats["count"]:,} captures · '
                f'nominal RF window {nominal_us:.1f} µs · firmware trigger-to-done {capture.firmware_capture_us:,} µs · '
                f'host transaction {transaction_ms:.1f} ms · nominal RF duty {stats["nominal_duty"] * 100:.3f}% · '
                f'cycle dead-time estimate {max(0, stats["elapsed"] * 1000 / stats["count"] - nominal_us / 1000):.1f} ms · '
                f'{stats["render_drops"]} render skips (not RF loss count) · CRC {"OK" if capture.crc_ok else "NOT VERIFIED"}'
            )
        else:
            self.status_label.setText(
                f'{"SIMULATED · " if synthetic else ""}Offline replay · {capture.timestamp} · {capture.frequency_hz / 1e6:g} MHz · No continuous timing inferred'
            )

    def render_occupancy(self, stats, port):
        if stats and stats.get('occupancy'):
            points = sorted(stats['occupancy'].items())
            self.occupancy_bars.setOpts(
                x=[x for x, _ in points],
                height=[hits / max(total, 1) for _, (hits, total) in points],
            )
            row = np.full(101, np.nan)
            for frequency, (hits, total) in points:
                if 2400 <= frequency <= 2500:
                    row[frequency - 2400] = hits / max(total, 1)
            history = self.occupancy_histories.setdefault(port, deque(maxlen=100))
            history.append(row)
            self.occupancy_image.setImage(np.asarray(history), autoLevels=False, levels=(0, 1))
            self.occupancy_image.setRect(QtCore.QRectF(2399.5, -len(history), 101, len(history)))
            self.occupancy_map.setYRange(-100, 0, padding=0)
            self.occupancy_map.setXRange(2399.5, 2500.5, padding=0)

    def add_event(self, port, capture, result, meta_path):
        self.events.appendleft((capture, result, meta_path))
        self.event_table.insertRow(0)
        reference = capture.timestamp + (
            ' [detector run start, NOT event time]' if result.get('timestamp_reference') else ''
        )
        values = [
            reference,
            port,
            f'{capture.frequency_hz / 1e6:.3f}',
            f'{result.get("peak_dbfs", float("nan")):.1f}',
            f'{result.get("snr_db", float("nan")):.1f}',
            f'{result.get("bandwidth_hz", float("nan")) / 1000:.1f}',
            meta_path or 'Memory only',
        ]
        for col, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            self.event_table.setItem(0, col, item)
        if self.event_table.rowCount() > 200:
            self.event_table.removeRow(200)

    def redraw_selected(self, *args):
        port = self.device_view.currentText()
        if port in self.latest:
            self.render(port, self.latest[port])
        elif self.stats.get(port, {}).get('mode') in DETECTOR_MODES:
            self.spectrum_curve.clear()
            self.peak_curve.clear()
            self.waterfall_image.clear()
            self.render_detector_status(port, self.stats[port], False)

    def reset_display(self):
        self.averages.clear()
        self.peaks.clear()
        self.waterfalls.clear()
        self.occupancy.clear()
        self.occupancy_histories.clear()
        if hasattr(self, 'spectrum_curve'):
            self.spectrum_curve.clear()
            self.peak_curve.clear()
            self.waterfall_image.clear()
            self.occupancy_bars.setOpts(x=[], height=[])
            self.occupancy_image.clear()
            self.spectrum_plot.setTitle('Spectrum')

    def calibrate_noise(self):
        port = self.device_view.currentText()
        capture = self.latest.get(port)
        if capture is None:
            self.show_error('Acquire an idle reference capture first.')
            return
        nfft = min(1024, len(capture.iq))
        _, power = spectrum(
            capture.iq, capture.sample_rate_hz, nfft=nfft, remove_dc=self.remove_dc.isChecked()
        )
        key = self.spectrum_key(port, capture, nfft)
        calibration = self.noise_calibrations.setdefault(key, NoiseCalibration())
        self.noise_baselines[key] = calibration.add(key, power)
        self.log.appendPlainText(
            'Saved current spectrum as user-selected idle reference. This adjusts only the display, not detector thresholds or dBm calibration. Recalibrate after receiver setting changes.'
        )
        self.relative_noise.setChecked(True)

    def inspect_capture(self, capture):
        dialog = InspectionWindow(capture, self)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.dialogs.append(dialog)
        dialog.finished.connect(
            lambda _: self.dialogs.remove(dialog) if dialog in self.dialogs else None
        )
        dialog.show()

    def inspect_latest(self):
        capture = self.latest.get(self.device_view.currentText())
        if capture is not None:
            self.inspect_capture(capture)

    def inspect_event(self, row, column):
        if row < len(self.events):
            self.inspect_capture(self.events[row][0])

    def save_latest(self):
        capture = self.latest.get(self.device_view.currentText())
        if capture is None:
            self.show_error('No capture to save yet.')
            return
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            'Save capture',
            str(self.output_dir / 'manual-capture'),
            'SigMF metadata (*.sigmf-meta)',
        )
        if filename:
            try:
                path = Path(filename)
                if path.suffix == '.sigmf-meta':
                    path = path.with_suffix('')
                result = save_capture(capture, path)
                self.log.appendPlainText(f'Saved {result}')
            except Exception as exc:
                self.show_error(str(exc))

    def choose_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Recording folder', str(self.output_dir)
        )
        if folder:
            self.output_dir = Path(folder)
            self.log.appendPlainText(f'Future sessions save to {folder}')

    def open_replay(self):
        if any(w.isRunning() for w in self.workers.values()):
            self.show_error('Stop acquisition before offline replay.')
            return
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            'Replay captures in file order',
            str(self.output_dir),
            'SigMF metadata (*.sigmf-meta)',
        )
        if not paths:
            return
        self.workers.clear()
        self.worker_errors.clear()
        self.replay_paths = sorted(paths)
        self.replay_index = 0
        self.device_view.clear()
        self.device_view.addItem('Replay')
        self.reset_display()
        self.replay_tick()
        if len(paths) > 1:
            self.replay_timer.start()
        self.replay_button.setText('Pause replay')

    def replay_tick(self):
        if self.replay_index >= len(self.replay_paths):
            self.replay_timer.stop()
            self.replay_button.setText('Replay again')
            return
        try:
            capture = load_capture(self.replay_paths[self.replay_index])
            self.replay_index += 1
            self.latest['Replay'] = capture
            self.stats.pop('Replay', None)
            self.render('Replay', capture)
        except Exception as exc:
            self.replay_timer.stop()
            self.show_error(f'Replay: {exc}')

    def toggle_replay(self):
        if not self.replay_paths:
            return
        if self.replay_timer.isActive():
            self.replay_timer.stop()
            self.replay_button.setText('Resume replay')
        else:
            if self.replay_index >= len(self.replay_paths):
                self.replay_index = 0
            self.replay_timer.start()
            self.replay_button.setText('Pause replay')

    def show_error(self, text):
        self.log.appendPlainText(f'ERROR: {text}')
        QtWidgets.QMessageBox.warning(self, 'ESP32 RF Research', text)

    def closeEvent(self, event):
        if any(w.isRunning() for w in self.workers.values()):
            self.closing = True
            self.stop_acquisition()
            event.ignore()
        else:
            self.timer.stop()
            self.replay_timer.stop()
            event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--demo',
        action='store_true',
        help='Use conspicuously labelled synthetic data; never touches serial',
    )
    args = parser.parse_args(argv)
    pg.setConfigOptions(antialias=False, background='#101820', foreground='#dbe8f3')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor('#17212b'))
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor('#e4edf5'))
    palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor('#101820'))
    palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor('#e4edf5'))
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor('#253644'))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor('#e4edf5'))
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor('#286c94'))
    app.setPalette(palette)
    window = MainWindow(demo=args.demo)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
