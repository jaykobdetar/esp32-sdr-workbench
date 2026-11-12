"""Qt-free acquisition and recording with one serial owner and bounded queues."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .analysis import detect_event, endpoint_counts
from .detector import run_detection
from .pipeline import run_pipeline, run_pipeline_candidates, select_acquisition_policy
from .protocol import Capture, Radio
from .recording import atomic_write_json, save_capture

DETECTOR_MODES = ('DET1', 'DETPIPE1')


def receiver_settings(settings: dict, frequency_mhz: int) -> dict:
    """Host-requested receiver configuration, recorded with every detector-run summary."""
    gain = settings.get('gain')
    return {
        'frequency_mhz': frequency_mhz,
        'rate_hz': settings.get('rate_hz'),
        'bandwidth_mhz': settings.get('bandwidth_mhz'),
        'gain_mode': 'hardware_agc' if gain is None else 'manual',
        'gain_index': gain,
        'bits': settings.get('bits'),
        'samples': settings.get('samples'),
        'note': 'Host-requested settings. Legacy firmware lacks gain telemetry; newer raw '
        'start/end gain snapshots are reported separately and do not trace per-capture AGC.',
    }


class AcquisitionWorker(threading.Thread):
    """One owner per serial connection; bounded rendering and event-notice queues."""

    def __init__(
        self, port: str, settings: dict, output_dir: str | Path, demo: bool = False
    ) -> None:
        super().__init__()
        self.error = None
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

    def isRunning(self) -> bool:
        """Compatibility with the viewer's existing worker lifecycle."""
        return self.is_alive()

    def wait(self, milliseconds: int | None = None) -> bool:
        self.join(None if milliseconds is None else milliseconds / 1000)
        return not self.is_alive()

    def notice(self, kind: str, value: object) -> None:
        try:
            self.notices.put_nowait((kind, value))
        except queue.Full:
            self.event_notices_dropped += 1

    def stop(self) -> None:
        self.stop_requested.set()

    def demo_capture(self, frequency: int) -> Capture:
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

    def detector_run(self, radio: Radio, frequency: int) -> None:
        """One bounded run; JSON is preserved even when no IQ was retained."""
        s = self.settings
        mode = s.get('mode', 'DET1')
        multiple = s.get('candidate_count', 1) == 3
        # Passed only when chosen, so the clients' own default (the firmware default) applies.
        policy = (
            {'background_policy': s['background_policy']}
            if s.get('background_policy') is not None
            else {}
        )
        if mode == 'DETPIPE1':
            pipeline = run_pipeline_candidates if multiple else run_pipeline
            summary, retained = pipeline(
                radio,
                milliseconds=s['det_ms'],
                samples=s['samples'],
                rate_hz=s['rate_hz'],
                ratio_milli=s['ratio_milli'],
                retain=True,
                kernel=3,
                optimized=True,
                copy_option=1 if 'PIPECOPY' in radio.info.get('caps', []) else None,
                **policy,
            )
            captures = retained if multiple else ([retained] if retained is not None else [])
            capture = captures[0] if captures else None
        else:
            if multiple:
                raise ValueError('Multiple candidate crops require DETPIPE1 mode')
            policies = select_acquisition_policy(radio, False)
            summary, capture = run_detection(
                radio,
                milliseconds=s['det_ms'],
                samples=s['samples'],
                rate_hz=s['rate_hz'],
                ratio_milli=s['ratio_milli'],
                retain=True,
                **policy,
            )
            summary['acquisition_policies'] = policies
            captures = [capture] if capture is not None else []
        self.run_count += 1
        self.capture_count += summary['captures']
        self.candidate_count += summary.get('detections', 0)
        self.retained_count += len(captures)
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
        for retained_capture in captures:
            if retained_capture.metadata.get('trigger_device_us') is not None:
                retained_capture.metadata['timestamp_reference'] = (
                    'core datetime is host run start; trigger_device_us is device uptime '
                    'before the original acquisition trigger, not calibrated RF arrival'
                )
            else:
                retained_capture.metadata.setdefault(
                    'timestamp_reference', 'detector run host start; exact event time unavailable'
                )
            retained_capture.metadata['settings'] = dict(s)
            retained_capture.metadata['endpoint_counts'] = endpoint_counts(
                retained_capture.iq, retained_capture.bits
            )
        elapsed = max((time.monotonic_ns() - self.started_ns) / 1e9, 1e-9)
        summary = dict(summary)
        summary['receiver_settings'] = receiver_settings(s, frequency)
        if 'gain_register_start' in summary:
            summary['receiver_settings']['note'] = (
                'Host-requested settings; raw start/end gain-register snapshots are reported '
                'separately. These do not trace AGC changes within each run.'
            )
        # Saturation indicator for the retained capture only; other captures are not kept.
        summary['retained_endpoint_counts'] = (
            capture.metadata['endpoint_counts'] if capture is not None else None
        )
        summary['gui_mode'] = mode
        summary['candidate_count_semantics'] = 'candidate-positive captures, not unique packets'
        summary['retained_semantics'] = (
            'up to three candidate crops per finite run; strongest first, not unique packets'
            if multiple
            else 'at most one strongest candidate capture per finite run'
        )
        summary.setdefault(
            'timestamp_reference',
            (
                'host request datetime; device trigger uptime is not synchronized to UTC or calibrated RF arrival'
                if 'first_trigger_device_us' in summary
                else 'host run request time; exact event time unavailable'
            ),
        )
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
            # Publish once, after recording succeeds or its failure is described.
            summary_path = Path(str(base) + f'.{mode.lower()}.json')
            summary['retained_sigmf'] = None
            summary['retained_sigmf_candidates'] = []
            summary['recording_state'] = 'complete'
            try:
                for index, retained_capture in enumerate(captures):
                    candidate_base = base if index == 0 else Path(f'{base}-candidate-{index + 1}')
                    saved = save_capture(retained_capture, candidate_base)
                    summary['retained_sigmf_candidates'].append(saved.name)
                    if index == 0:
                        meta_path = str(saved)
                        summary['retained_sigmf'] = saved.name
            except Exception as exc:
                summary['recording_error'] = str(exc)
                summary['recording_state'] = 'error'
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
                atomic_write_json(summary_path, summary)
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
                endpoint_counts=capture.metadata['endpoint_counts'],
                timestamp_reference=capture.metadata['timestamp_reference'],
            )
            self.notice('event', (capture, result, meta_path))
        if len(self.frames) == self.frames.maxlen:
            self.render_drops += 1
        self.frames.append((capture, summary, stats))
        if summary.get('status') or summary.get('errors') or summary.get('errors_received'):
            raise RuntimeError(
                f'{mode} ended with status {summary.get("status")}; summary recorded if recording enabled. Reconnect before retry.'
            )

    def run(self) -> None:
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
            deadline = (time.monotonic() + s['duration_s']) if s.get('duration_s') else None
            while not self.stop_requested.is_set():
                if s.get('max_runs') and self.run_count >= s['max_runs']:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
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
                result['endpoint_counts'] = endpoint_counts(capture.iq, capture.bits)
                capture.metadata['endpoint_counts'] = result['endpoint_counts']
                hits, observations = self.occupancy_counts.get(frequency, (0, 0))
                self.occupancy_counts[frequency] = (
                    hits + int(result.get('detected', False)),
                    observations + 1,
                )
                meta_path = None
                if result.get('detected') or s.get('record_all', False):
                    if s['autosave']:
                        self.output_dir.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                        safe_port = self.port.replace('/', '_')
                        meta_path = str(
                            save_capture(capture, self.output_dir / f'{stamp}-{safe_port}')
                        )
                        self.notice('record', meta_path)
                    if result.get('detected'):
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
            self.error = exc
            message = f'{type(exc).__name__}: {exc}'
            if self.settings.get('mode') in DETECTOR_MODES:
                message += ' · Detector mode requires compatible experimental firmware; nothing was flashed. Select Raw I/Q for existing firmware.'
            self.notice('error', message)
        finally:
            if radio is not None:
                try:
                    radio.close()
                except Exception as exc:
                    self.error = self.error or exc
                    self.notice('error', f'Close: {exc}')
            self.notice('state', 'Stopped')
