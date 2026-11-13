"""Experimental sparse-I/Q worker. Independent receivers, never continuous IQ."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from datetime import datetime, timezone

from .acquisition import AcquisitionWorker
from .analysis import endpoint_counts
from .detector_stream import APERTURE_US, run_stream
from .dual_timing import clock_probe
from .pipeline import select_background_policy
from .protocol import Capture, Radio, decode_iq
from .recording import atomic_write_json, save_capture


class StreamAcquisitionWorker(AcquisitionWorker):
    """Persistent telemetry in bounded600s chunks, with sparse complete IQ buffers.

    Rendering and saving queues are bounded. Slow disk fails the session instead
    of dropping a capture silently. No-save never creates a writer or path.
    """

    def run(self) -> None:
        radio = None
        writer = None
        pending = queue.Queue(maxsize=4)
        writer_errors = []
        writer_done = threading.Event()
        latest = None
        last_emit = 0.0
        self.started_ns = time.monotonic_ns()
        s = self.settings

        def write_loop():
            while not writer_done.is_set() or not pending.empty():
                try:
                    capture = pending.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    path = save_capture(capture, self.output_dir / f'{uuid.uuid4().hex}-sparse-iq')
                    self.notice('record', str(path))
                except Exception as exc:
                    writer_errors.append(exc)
                    self.stop_requested.set()
                finally:
                    pending.task_done()

        def emit():
            elapsed = max((time.monotonic_ns() - self.started_ns) / 1e9, 1e-9)
            if len(self.frames) == self.frames.maxlen:
                self.render_drops += 1
            self.frames.append(
                (
                    latest,
                    {},
                    dict(
                        count=self.capture_count,
                        retained=self.retained_count,
                        candidates=self.candidate_count,
                        nominal_duty=self.nominal_rf_s / elapsed,
                        elapsed=elapsed,
                        mode='DSTREAMIQ',
                        sparse_iq=True,
                    ),
                )
            )

        def record(record):
            nonlocal last_emit
            if writer_errors:
                raise RuntimeError(f'Sparse recording failed: {writer_errors[0]}')
            self.capture_count += 1
            self.candidate_count += bool(record['flags'] & 1)
            self.nominal_rf_s += APERTURE_US / 1e6
            now = time.monotonic()
            if now - last_emit >= 0.2:
                emit()
                last_emit = now

        def snapshot(item):
            nonlocal latest
            now = time.monotonic_ns()
            iq = decode_iq(item['payload'], item['samples'], item['bits'])
            metadata = {k: v for k, v in item.items() if k != 'payload'}
            metadata.update(
                sparse_iq=True,
                device=self.port,
                timestamp_reference='host completed snapshot arrival; trigger_us is independent device uptime, not synchronized RF time',
            )
            metadata['endpoint_counts'] = endpoint_counts(iq, item['bits'])
            latest = Capture(
                iq,
                item['sample_rate'],
                item['frequency_mhz'] * 1000000,
                datetime.now(timezone.utc).isoformat(),
                now,
                now,
                round(APERTURE_US),
                bits=item['bits'],
                crc_ok=item['transport_crc_valid'],
                metadata=metadata,
            )
            self.retained_count += 1
            if s['autosave']:
                try:
                    pending.put_nowait(latest)
                except queue.Full:
                    raise RuntimeError(
                        'Sparse recording queue full; stopping instead of silently losing IQ'
                    ) from None
            emit()

        try:
            if self.demo:
                raise ValueError(
                    'DSTREAMIQ requires compatible experimental hardware; simulation remains raw'
                )
            radio = Radio(self.port, baud=1_000_000)
            self.notice('info', radio.connect())
            if not {'DSTREAM', 'DSTREAMIQ'} <= set(radio.info.get('caps', [])):
                raise ValueError(
                    'Receiver lacks experimental DSTREAMIQ firmware; nothing was flashed'
                )
            radio.configure(
                frequency_mhz=s['frequency_mhz'],
                rate_hz=16000000,
                bandwidth_mhz=s['bandwidth_mhz'],
                gain=s['gain'],
                bits=10,
            )
            select_background_policy(radio, s.get('background_policy'))
            if s['autosave']:
                writer = threading.Thread(target=write_loop, name='Sparse IQ recorder', daemon=True)
                writer.start()
            self.notice(
                'state',
                'Experimental persistent telemetry + sparse IQ; independent receiver timing',
            )
            while not self.stop_requested.is_set():
                clock = clock_probe(radio, samples=3)
                start = round(time.monotonic_ns() / 1000 + clock['offset_us'] + 250000)
                result = run_stream(
                    radio,
                    start_us=start,
                    milliseconds=600000,
                    period_ns=1875000,
                    yield_phase=32,
                    ratio_milli=s['ratio_milli'],
                    stop=self.stop_requested,
                    on_record=record,
                    keep_records=False,
                    snapshot_every=2667,
                    snapshot_phase=0,
                    on_snapshot=snapshot,
                )
                self.run_count += 1
                if s['autosave']:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    atomic_write_json(
                        self.output_dir / f'{uuid.uuid4().hex}.dstreamiq.json', result
                    )
                emit()
                if not self.stop_requested.is_set():
                    self.notice('state', 'Restarting bounded stream chunk; this introduces a gap')
            if writer_errors:
                raise RuntimeError(f'Sparse recording failed: {writer_errors[0]}')
        except Exception as exc:
            self.error = exc
            self.notice('error', str(exc))
        finally:
            if radio is not None:
                try:
                    radio.close()
                except Exception as exc:
                    self.error = self.error or exc
            writer_done.set()
            if writer:
                writer.join(5)
                if writer.is_alive():
                    self.error = self.error or RuntimeError(
                        'Sparse recording did not finish within5seconds'
                    )
                elif writer_errors:
                    self.error = self.error or writer_errors[0]
            if self.error:
                self.notice('error', str(self.error))
            self.notice('state', 'Stopped')
