"""Experimental persistent detector telemetry. Not continuous raw I/Q or packet recall.

A valid record proves only delivery of that detector's timestamp/energy result.
Nominal sample aperture is derived from N/fs, not measured RF arrival timing.
"""

from __future__ import annotations

import json
import struct
import time
import zlib
from collections.abc import Callable
from threading import Event
from typing import Any

from .protocol import ProtocolError, Radio
from .stream_snapshots import SnapshotAssembler

WIRE = struct.Struct('<4sIQIIIIIIII')
MAGIC = b'DSV1'
END = 1 << 31
APERTURE_US = 16380 / 16


def decode_record(data: bytes) -> dict[str, int]:
    if len(data) != WIRE.size:
        raise ProtocolError('Invalid DSTREAM record length')
    magic, seq, trigger, mean, peak, background, events, flags, observed, gain, crc = WIRE.unpack(
        data
    )
    if magic != MAGIC or zlib.crc32(data[:-4]) != crc:
        raise ProtocolError('DSTREAM framing/CRC failure; coverage is unverified')
    if flags not in (0, 2, 3, END):
        raise ProtocolError('Invalid DSTREAM flags')
    return dict(
        wire_crc32=crc,
        sequence=seq,
        trigger_us=trigger,
        mean_adc2=mean,
        peak_adc2=peak,
        background_adc2=background,
        events_total=events,
        flags=flags,
        completion_observed_us=observed,
        gain_register_at_completion=gain,
    )


def validate_saved_record(record: dict[str, int]) -> None:
    """Reconstruct wire bytes and verify the original CRC, including terminal records.

    This detects accidental evidence corruption, not malicious alteration.
    Missing original CRCs cannot be retrospectively verified.
    """
    fields = (
        'sequence',
        'trigger_us',
        'mean_adc2',
        'peak_adc2',
        'background_adc2',
        'events_total',
        'flags',
        'completion_observed_us',
        'gain_register_at_completion',
        'wire_crc32',
    )
    try:
        values = [record[key] for key in fields]
        if any(type(value) is not int for value in values):
            raise ValueError('Wire fields must be integers')
        decode_record(WIRE.pack(MAGIC, *values))
    except (KeyError, ValueError, struct.error, ProtocolError) as exc:
        raise ValueError('Saved DSTREAM record lacks valid original wire CRC') from exc


def run_stream(
    radio: Radio,
    *,
    start_us: int,
    milliseconds: int = 30_000,
    period_ns: int = 1_875_000,
    yield_phase: int = 0,
    ratio_milli: int = 4000,
    stop: Event | None = None,
    on_record: Callable[[dict[str, int]], None] | None = None,
    keep_records: bool = True,
    snapshot_every: int = 0,
    snapshot_phase: int = 0,
    on_snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """One persistent, bounded, no-retention run. Stop is explicit and cooperative.

    Callbacks must not access the radio. Slow callbacks risk USB receive loss;
    firmware never blocks acquisition to wait for the host. CRC and sequence
    checks make any loss a failed measurement, never silently 100% coverage.
    """
    values = (start_us, milliseconds, period_ns, yield_phase, ratio_milli)
    if any(type(x) is not int for x in values):
        raise ValueError('DSTREAM parameters must be integers')
    if not (
        start_us > 0
        and 1 <= milliseconds <= 600_000
        and 1_600_000 <= period_ns <= 10_000_000
        and 0 <= yield_phase <= 34
        and 1000 <= ratio_milli <= 1_000_000
    ):
        raise ValueError('DSTREAM arguments outside supported limits')
    if yield_phase == 34 and 'DSTREAMIDLEWAKE' not in radio.info.get('caps', []):
        raise ProtocolError('Receiver lacks idle-wakeup stream firmware')
    if yield_phase == 33 and 'DSTREAMIDLE' not in radio.info.get('caps', []):
        raise ProtocolError('Receiver lacks cooperative-idle stream firmware')
    if 'DSTREAM' not in radio.info.get('caps', []):
        raise ProtocolError('Receiver lacks experimental DSTREAM firmware')
    if (
        type(snapshot_every) is not int
        or type(snapshot_phase) is not int
        or not (
            (snapshot_every == 0 and snapshot_phase == 0)
            or (1024 <= snapshot_every <= 1_000_000 and 0 <= snapshot_phase < snapshot_every)
        )
    ):
        raise ValueError('Invalid sparse snapshot interval/phase')
    if snapshot_every and 'DSTREAMIQ' not in radio.info.get('caps', []):
        raise ProtocolError('Receiver lacks sparse snapshot firmware')
    assembler = SnapshotAssembler() if snapshot_every else None
    recent = {}
    requested = f'DSTREAM {start_us} {milliseconds} {period_ns} {yield_phase} {ratio_milli}'
    if assembler:
        requested = (
            requested.replace('DSTREAM ', 'DSTREAMIQ ', 1) + f' {snapshot_every} {snapshot_phase}'
        )
    records = []
    count, events, first, last, stopped = 0, 0, 0, 0, False
    deadline = time.monotonic() + milliseconds / 1000 + 10
    started_host = time.monotonic()
    try:
        begin = radio.command(requested)
        fields = begin.split()
        if len(fields) != (12 if assembler is not None else 10) or fields[:3] != [
            'DSTREAM',
            'BEGIN',
            '1',
        ]:
            radio.failed = True
            raise ProtocolError('Invalid stream BEGIN')
        if list(map(int, fields[3:8])) != list(values):
            radio.failed = True
            raise ProtocolError('Stream BEGIN does not match request')
        try:
            frequency, policy = map(int, fields[8:10])
        except ValueError as error:
            raise ProtocolError('Invalid stream frequency/policy echo') from error
        if not 2300 <= frequency <= 2600 or policy not in (1, 2):
            raise ProtocolError('Invalid stream frequency/policy echo')
        settings = getattr(radio, 'settings', {})
        expected_frequency = settings.get('frequency_mhz')
        if expected_frequency is not None and frequency != expected_frequency:
            raise ProtocolError('Stream frequency does not match configured receiver')
        if assembler is not None:
            assembler.expected_frequency_mhz = frequency
        if assembler is not None and list(map(int, fields[10:])) != [
            snapshot_every,
            snapshot_phase,
        ]:
            raise ProtocolError('Snapshot BEGIN does not match request')
        while True:
            if stop and stop.is_set() and not stopped:
                radio.serial.write(b'STOP\n')
                radio.serial.flush()
                stopped = True
            # At least one frame per second even at the slowest supported period.
            frame = radio._read(WIRE.size, min(deadline, time.monotonic() + 7))
            if assembler is not None and frame[:4] in (b'DSI1', b'DSQ1'):
                snapshot = assembler.feed(frame, recent)
                if snapshot is not None and on_snapshot:
                    on_snapshot(snapshot)
                continue
            record = decode_record(frame)
            if record['flags'] == END:
                terminal = record
                break
            count += 1
            if record['sequence'] != count or record['trigger_us'] <= last:
                raise ProtocolError('Missing or non-monotonic stream records')
            if record['flags'] & 1:
                events += 1
            if record['events_total'] != events or bool(record['flags'] & 2) != (count > 16):
                raise ProtocolError('Invalid stream decision counters')
            if not first:
                first = record['trigger_us']
            last = record['trigger_us']
            if assembler is not None:
                recent[count] = record
                recent.pop(count - 4096, None)
            if keep_records:
                records.append(record)
            if on_record:
                on_record(record)
        line = radio._line(time.monotonic() + 5)
        if not line.startswith('DSTREAM END '):
            raise ProtocolError('Missing stream END summary')
        summary = json.loads(line[12:])
        if (
            summary['captures'] != count
            or summary['processed'] != count
            or summary['events'] != events
            or terminal['sequence'] != count
            or terminal['events_total'] != events
            or summary['status'] != terminal['mean_adc2']
            or summary['overflow']
            or summary['first_trigger_us'] != first
            or summary['last_trigger_us'] != last
            or summary['end_us'] != terminal['trigger_us']
            or summary['skipped'] != terminal['background_adc2']
            or summary['max_late_us'] != terminal['peak_adc2']
        ):
            raise ProtocolError('Stream final counters do not agree')
        if assembler is not None:
            if (
                assembler.pending
                or summary.get('iq_sent') != assembler.completed
                or summary.get('iq_produced') != assembler.completed
            ):
                raise ProtocolError('Incomplete sparse snapshot stream')
        if summary['status'] not in (0, 3):
            raise ProtocolError(f'Stream failed with status {summary["status"]}')
    except BaseException:
        # No further commands except stop: framing may already be uncertain.
        try:
            radio.serial.write(b'STOP\n')
            radio.serial.flush()
        finally:
            radio.failed = True
        raise
    return dict(
        begin=begin,
        summary=summary,
        records=records,
        terminal=terminal,
        transport_crc_valid=True,
        host_elapsed_s=time.monotonic() - started_host,
        stop_requested=stopped,
        nominal_aperture_us=APERTURE_US,
        retention=bool(snapshot_every),
        snapshots_received=assembler.completed if assembler else 0,
        timing_note='Device trigger plus nominal N/fs, not calibrated RF aperture or packet recall.',
    )
