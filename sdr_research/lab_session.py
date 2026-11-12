"""Finite multi-receiver / transmitter sessions with one owner per serial connection.

This is host orchestration, NOT hardware synchronization or a coverage measurement.
"""

from __future__ import annotations

import copy
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .acquisition import AcquisitionWorker
from .recording import atomic_write_json


def default_receiver_settings() -> dict:
    return dict(
        mode='DETPIPE1',
        frequency_mhz=2440,
        rate_hz=16_000_000,
        bandwidth_mhz=12,
        gain=40,
        bits=10,
        samples=16380,
        det_ms=1000,
        ratio_milli=4000,
        background_policy=1,
        candidate_count=1,
        threshold_db=10,
        autosave=True,
        record_all=True,
        scan=False,
    )


def default_transmitter_settings() -> dict:
    return dict(
        frequency_mhz=2440,
        mode_mbps=2,
        power_dbm=-20,
        length=64,
        interval_us=2000,
        jitter_us=0,
        seed=52840,
        payload_hex='off',
        hop_list='off',
        hop_every=1,
        burst_count=0,
        burst_gap_us=0,
    )


def _integer(settings: dict, key: str, low: int, high: int) -> None:
    value = settings[key]
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{key} must be an integer in {low}..{high}')


def validate_receiver(settings: dict, demo: bool) -> None:
    s = default_receiver_settings() | settings
    if s['mode'] not in ('raw', 'DET1', 'DETPIPE1'):
        raise ValueError('Unsupported receiver mode')
    if demo and s['mode'] != 'raw':
        raise ValueError('Synthetic input supports raw mode only')
    for key, low, high in (
        ('frequency_mhz', 2400, 2500),
        ('bandwidth_mhz', 0, 67),
        ('samples', 256, 16380),
        ('det_ms', 1, 5000),
        ('ratio_milli', 1000, 1000000),
    ):
        _integer(s, key, low, high)
    if s['gain'] is not None:
        _integer(s, 'gain', 0, 81)
    if s['rate_hz'] not in (16_000_000, 40_000_000, 80_000_000):
        raise ValueError('Unsupported receiver sample rate')
    if s['bits'] not in (8, 10) or (s['mode'] != 'raw' and s['bits'] != 10):
        raise ValueError('Detector modes require 10-bit samples')
    if s['background_policy'] not in (None, 1, 2):
        raise ValueError('Unsupported background policy')
    if s['candidate_count'] not in (1, 3) or (
        s['candidate_count'] == 3 and s['mode'] != 'DETPIPE1'
    ):
        raise ValueError('Three candidates require DETPIPE1')
    if s['scan']:
        raise ValueError('Shared lab sessions use fixed per-receiver frequencies')


def validate_transmitter(settings: dict, serial_number: str) -> None:
    s = default_transmitter_settings() | settings
    if not re.fullmatch(r'[0-9A-F]{16}', serial_number):
        raise ValueError('Transmitter needs its exact uppercase USB serial')
    if set(s) - (set(default_transmitter_settings()) | {'count'}):
        raise ValueError('Unknown transmitter setting')
    s.setdefault('count', 0)
    for key, low, high in (
        ('frequency_mhz', 2402, 2480),
        ('length', 8, 252),
        ('interval_us', 1000, 1000000),
        ('jitter_us', 0, 500000),
        ('seed', 1, 2000000000),
        ('burst_count', 0, 20000),
        ('burst_gap_us', 0, 1000000),
        ('hop_every', 1, 20000),
        ('count', 0, 20000),
    ):
        _integer(s, key, low, high)
    if type(s['mode_mbps']) is not int or s['mode_mbps'] not in (1, 2):
        raise ValueError('Transmitter mode must be 1 or 2 Mbps')
    if type(s['power_dbm']) is not int or s['power_dbm'] not in (-40, -20, -16, -12, -8, -4, 0):
        raise ValueError('Unsupported transmitter power')
    if s['interval_us'] < (s['length'] + 10) * 8 // s['mode_mbps'] + 300:
        raise ValueError('Packet interval too short for packet length and mode')
    if s['jitter_us'] > s['interval_us'] // 2:
        raise ValueError('Jitter exceeds half the packet interval')
    payload = s['payload_hex']
    if payload != 'off' and (
        not isinstance(payload, str)
        or not re.fullmatch(r'(?:[0-9A-Fa-f]{2})+', payload)
        or len(payload) // 2 > s['length'] - 8
    ):
        raise ValueError('Invalid payload hex or payload too long')
    hops = s['hop_list']
    if hops != 'off':
        if not isinstance(hops, str) or not re.fullmatch(r'[0-9]+(?:,[0-9]+)*', hops):
            raise ValueError('Invalid hopping list')
        values = list(map(int, hops.split(',')))
        if len(values) > 16 or any(not 2402 <= value <= 2480 for value in values):
            raise ValueError('Hopping list must contain at most 16 frequencies in 2402..2480')


@dataclass
class ReceiverConfig:
    label: str
    port: str
    settings: dict = field(default_factory=default_receiver_settings)
    demo: bool = False


@dataclass
class TransmitterConfig:
    label: str
    port: str
    serial_number: str
    settings: dict = field(default_factory=default_transmitter_settings)


class LabSession(threading.Thread):
    """Start receivers first; stop all TXs on failure, cancellation or finite deadline.

    Notices are (kind, value) pairs. Receiver notices have kind='receiver' and value
    {label, kind, value}; frames retain AcquisitionWorker's existing tuple format.
    Output must be a fresh directory. A failed STOP is explicitly reported, never
    presented as confirmed RF silence. Every TX also has a firmware duration limit.
    """

    def __init__(
        self,
        receivers: list[ReceiverConfig],
        transmitters: list[TransmitterConfig],
        output_dir: str | Path,
        duration_s: float | None = 10,
        persist: bool = True,
    ) -> None:
        super().__init__(name='RF lab session')
        if not receivers:
            raise ValueError('Select at least one receiver')
        if duration_s is not None and not 0.1 <= duration_s <= 60:
            raise ValueError('Session duration must be 0.1..60 seconds or None (until stopped)')
        if duration_s is None and transmitters:
            raise ValueError('Transmitter sessions must be bounded to 60 seconds or less')
        labels = [item.label for item in [*receivers, *transmitters]]
        if len(set(labels)) != len(labels):
            raise ValueError('Device labels must be unique')
        ports = [
            str(Path(item.port).resolve())
            for item in [*receivers, *transmitters]
            if not isinstance(item, ReceiverConfig) or not item.demo
        ]
        if len(set(ports)) != len(ports):
            raise ValueError('Each physical port can have only one session owner')
        if transmitters and any(item.demo for item in receivers):
            raise ValueError('Synthetic receivers cannot accompany real transmitters')
        for receiver in receivers:
            validate_receiver(receiver.settings, receiver.demo)
        for transmitter in transmitters:
            validate_transmitter(transmitter.settings, transmitter.serial_number)
        self.receivers = copy.deepcopy(receivers)
        self.transmitters = copy.deepcopy(transmitters)
        self.output_dir = Path(output_dir)
        self.duration_s = None if duration_s is None else float(duration_s)
        self.persist = bool(persist)
        self.state = 'ready'
        self.error: str | None = None
        self.stop_requested = threading.Event()
        self.notices: queue.Queue = queue.Queue(maxsize=1024)
        self.notices_dropped = 0
        self.workers: dict[str, AcquisitionWorker] = {}
        self.frames: dict[str, Any] = {}
        self.manifest: dict = dict(
            schema_version=1,
            status='ready',
            receivers=[asdict(r) for r in receivers],
            transmitters=[asdict(t) for t in transmitters],
            duration_s=duration_s,
            persist=self.persist,
            timing_note='Host coordinated independent receivers. Starts are not simultaneous; '
            'no shared clock, coverage union, or packet-recall claim.',
            transmitter_results={},
            receiver_results={},
            cleanup_errors=[],
        )
        self._tx: dict[str, Any] = {}
        self._original_tx: dict[str, dict] = {}

    def notice(self, kind: str, value: Any) -> None:
        try:
            self.notices.put_nowait((kind, value))
        except queue.Full:
            self.notices_dropped += 1

    def stop(self) -> None:
        self.stop_requested.set()

    def _state(self, state: str) -> None:
        self.state = state
        self.notice('state', state)

    def _drain_receivers(self) -> None:
        for label, worker in self.workers.items():
            while True:
                try:
                    kind, value = worker.notices.get_nowait()
                except queue.Empty:
                    break
                self.notice('receiver', dict(label=label, kind=kind, value=value))
            if worker.error is not None:
                raise RuntimeError(f'{label}: {worker.error}')

    def _save(self) -> None:
        if self.persist:
            atomic_write_json(self.output_dir / 'session.json', self.manifest)

    @staticmethod
    def _restorable(status: dict) -> dict:
        keys = (
            'frequency_mhz',
            'mode_mbps',
            'power_dbm',
            'interval_us',
            'jitter_us',
            'seed',
            'burst_count',
            'burst_gap_us',
            'hop_every',
            'payload_hex',
        )
        config = {key: status[key] for key in keys if key in status}
        if 'payload_len' in status:
            config['length'] = status['payload_len']
        if 'hop_list' in status:
            config['hop_list'] = ','.join(map(str, status['hop_list'])) or 'off'
        if config.get('payload_hex') == '':
            config['payload_hex'] = 'off'
        return config

    def run(self) -> None:
        created = False
        try:
            if self.persist:
                self.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
                created = True
            self.manifest['started_unix_ns'] = time.time_ns()
            self._state('starting receivers')
            self.manifest['status'] = self.state
            self._save()
            for index, config in enumerate(self.receivers):
                if self.stop_requested.is_set():
                    break
                settings = default_receiver_settings() | config.settings
                # Session owns the deadline; receivers continue through TX setup and cleanup.
                settings.pop('duration_s', None)
                settings.pop('max_runs', None)
                if not self.persist:
                    settings['autosave'] = False
                worker = AcquisitionWorker(
                    config.port, settings, self.output_dir / f'rx-{index + 1}', demo=config.demo
                )
                self.workers[config.label] = worker
                self.frames[config.label] = worker.frames
                worker.start()
            deadline = time.monotonic() + 20
            while not self.stop_requested.is_set():
                self._drain_receivers()
                if all(w.capture_count > 0 for w in self.workers.values()):
                    break
                if any(not w.is_alive() for w in self.workers.values()):
                    raise RuntimeError('Receiver stopped before its first successful acquisition')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Receivers did not become ready within 20 seconds')
                self.stop_requested.wait(0.05)
            if not self.stop_requested.is_set():
                self._state('starting transmitters')
                # Imported only when transmitting so receiver-only installs remain usable.
                if self.transmitters:
                    from nrf_tx.rf_tx import Transmitter
                for config in self.transmitters:
                    if self.stop_requested.is_set():
                        break
                    self._drain_receivers()
                    tx = Transmitter(config.port, serial_number=config.serial_number)
                    self._tx[config.label] = tx
                    hello = tx.hello()
                    original = tx.status()
                    if original.get('running'):
                        raise RuntimeError(
                            f'{config.label} was already transmitting; stopping for safety, not reconfiguring'
                        )
                    self._original_tx[config.label] = self._restorable(original)
                    settings = default_transmitter_settings() | config.settings
                    count = settings.pop('count', 0)
                    configured = tx.configure(**settings)
                    result = self.manifest['transmitter_results'][config.label] = dict(
                        hello=hello,
                        configured=configured,
                        original_config=self._original_tx[config.label],
                    )
                    result['start'] = tx.start(
                        count=count, duration_ms=round(self.duration_s * 1000)
                    )
                    self.notice('transmitter', dict(label=config.label, status=result['start']))
                self._state('running')
                self.manifest['status'] = self.state
                self.manifest['run_started_monotonic_ns'] = time.monotonic_ns()
                self._save()
                deadline = (
                    float('inf') if self.duration_s is None else time.monotonic() + self.duration_s
                )
                next_status = 0.0
                while not self.stop_requested.is_set() and time.monotonic() < deadline:
                    self._drain_receivers()
                    if any(not w.is_alive() for w in self.workers.values()):
                        raise RuntimeError('Receiver stopped unexpectedly')
                    if time.monotonic() >= next_status:
                        for label, tx in self._tx.items():
                            result = tx.status()
                            self.manifest['transmitter_results'][label]['latest'] = result
                            self.notice('transmitter', dict(label=label, status=result))
                            if result.get('errors', 0) or result.get('healthy') is False:
                                raise RuntimeError(f'{label}: transmitter health/counter error')
                        next_status = time.monotonic() + 0.5
                    self.stop_requested.wait(0.05)
        except Exception as error:
            self.error = f'{type(error).__name__}: {error}'
            self.notice('error', self.error)
        finally:
            self._state('stopping')
            for label, tx in self._tx.items():
                try:
                    stopped = tx.stop()
                    self.manifest['transmitter_results'].setdefault(label, {})['stop'] = stopped
                    self.notice('transmitter', dict(label=label, status=stopped))
                    if stopped.get('running') is not False:
                        raise RuntimeError('STOP did not confirm running=false')
                    if self._original_tx.get(label):
                        tx.configure(**self._original_tx[label])
                except Exception as error:
                    self.manifest['cleanup_errors'].append(f'{label}: {error}')
                    self.notice('error', f'{label}: STOP/restore unverified: {error}')
                finally:
                    try:
                        tx.close()
                    except Exception as error:
                        self.manifest['cleanup_errors'].append(f'{label} close: {error}')
            for worker in self.workers.values():
                worker.stop()
            for label, worker in self.workers.items():
                if worker.ident is not None:
                    worker.join()
                self.manifest['receiver_results'][label] = dict(
                    runs=worker.run_count,
                    captures=worker.capture_count,
                    candidates=worker.candidate_count,
                    retained=worker.retained_count,
                    nominal_rf_s=worker.nominal_rf_s,
                    error=str(worker.error) if worker.error else None,
                )
                if worker.error and self.error is None:
                    self.error = f'{label}: {worker.error}'
            if self.manifest['cleanup_errors'] and self.error is None:
                self.error = 'Cleanup incomplete; inspect transmitter status before reuse'
            self._state(
                'error' if self.error else 'stopped' if self.stop_requested.is_set() else 'complete'
            )
            self.manifest.update(
                status=self.state,
                error=self.error,
                ended_unix_ns=time.time_ns(),
                notices_dropped=self.notices_dropped,
            )
            if created:
                try:
                    self._save()
                except Exception as error:
                    self.error = f'Manifest write failed: {error}'
                    self._state('error')
                    self.notice('error', self.error)
