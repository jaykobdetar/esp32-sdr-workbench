"""No-hardware persistent detector transport regression tests."""

import json
import struct
import zlib
from threading import Event
from unittest.mock import Mock

import pytest

from sdr_research.detector_stream import END, MAGIC, WIRE, run_stream
from sdr_research.protocol import ProtocolError

START = 1_000_000


def record(seq, *, flags=0, events=0, trigger=None, status=0, peak=0, background=0):
    data = WIRE.pack(
        MAGIC,
        seq,
        trigger if trigger is not None else START + seq * 1875,
        status,
        peak,
        background,
        events,
        flags,
        1024,
        40,
        0,
    )
    return data[:-4] + struct.pack('<I', zlib.crc32(data[:-4]))


def fake_radio(count=18, status=0):
    radio = Mock()
    radio.failed = False
    radio.info = {'caps': ['DSTREAM']}
    radio.command.return_value = f'DSTREAM BEGIN 1 {START} 30000 1875000 0 4000 2440 2'
    frames = [
        record(i, flags=0 if i <= 16 else 3, events=max(0, i - 16)) for i in range(1, count + 1)
    ]
    terminal_time = START + (count + 1) * 1875
    frames.append(
        record(count, flags=END, events=max(0, count - 16), status=status, trigger=terminal_time)
    )
    summary = {
        'captures': count,
        'processed': count,
        'events': max(0, count - 16),
        'status': status,
        'overflow': 0,
        'first_trigger_us': START + 1875 if count else 0,
        'last_trigger_us': START + count * 1875 if count else 0,
        'end_us': terminal_time,
        'max_late_us': 0,
        'skipped': 0,
    }
    radio._read.side_effect = frames
    radio._line.return_value = 'DSTREAM END ' + json.dumps(summary)
    return radio, frames, summary


def set_summary(radio, summary):
    radio._line.return_value = 'DSTREAM END ' + json.dumps(summary)


def assert_failed(radio):
    assert radio.failed
    assert any(call.args == (b'STOP\n',) for call in radio.serial.write.call_args_list)


def test_complete_stream_and_callback_without_retention():
    radio, _, _ = fake_radio()
    callback = Mock()
    result = run_stream(radio, start_us=START, on_record=callback, keep_records=False)
    assert result['records'] == []
    assert callback.call_count == 18
    assert result['summary']['events'] == 2
    assert result['transport_crc_valid'] and not result['retention']
    assert not radio.failed
    radio.serial.write.assert_not_called()


def test_explicit_stop_once_then_clean_terminal():
    radio, _, _ = fake_radio(status=3)
    stop = Event()
    stop.set()
    result = run_stream(radio, start_us=START, stop=stop)
    assert result['stop_requested']
    radio.serial.write.assert_called_once_with(b'STOP\n')
    assert not radio.failed


@pytest.mark.parametrize('fault', ['crc', 'drop', 'duplicate', 'timestamp', 'events', 'warmup'])
def test_bad_capture_fails_closed(fault):
    radio, frames, _ = fake_radio()
    if fault == 'crc':
        frames[2] = frames[2][:-1] + bytes([frames[2][-1] ^ 1])
    elif fault == 'drop':
        del frames[2]
    elif fault == 'duplicate':
        frames[2] = frames[1]
    elif fault == 'timestamp':
        frames[2] = record(3, trigger=START)
    elif fault == 'events':
        frames[2] = record(3, events=1)
    else:
        frames[2] = record(3, flags=2)
    radio._read.side_effect = frames
    with pytest.raises(ProtocolError):
        run_stream(radio, start_us=START)
    assert_failed(radio)


@pytest.mark.parametrize(
    'field,value',
    [('captures', 17), ('processed', 17), ('events', 9), ('overflow', 1), ('status', 2)],
)
def test_inconsistent_summary_fails_closed(field, value):
    radio, _, summary = fake_radio()
    summary[field] = value
    set_summary(radio, summary)
    with pytest.raises(ProtocolError):
        run_stream(radio, start_us=START)
    assert_failed(radio)


@pytest.mark.parametrize('status', [1, 2, 4])
def test_firmware_error_status_rejected(status):
    radio, _, _ = fake_radio(status=status)
    with pytest.raises(ProtocolError):
        run_stream(radio, start_us=START)
    assert_failed(radio)


@pytest.mark.parametrize('fault', ['sequence', 'events', 'status'])
def test_terminal_counter_disagreement(fault):
    radio, frames, _ = fake_radio()
    frames[-1] = record(
        17 if fault == 'sequence' else 18,
        flags=END,
        events=1 if fault == 'events' else 2,
        status=3 if fault == 'status' else 0,
    )
    radio._read.side_effect = frames
    with pytest.raises(ProtocolError):
        run_stream(radio, start_us=START)
    assert_failed(radio)


def test_callback_exception_stops_device():
    radio, _, _ = fake_radio()
    with pytest.raises(RuntimeError, match='consumer failed'):
        run_stream(
            radio, start_us=START, on_record=Mock(side_effect=RuntimeError('consumer failed'))
        )
    assert_failed(radio)


@pytest.mark.parametrize('summary', ['garbage', 'DSTREAM END {', 'DSTREAM END {}'])
def test_malformed_end_stops_device(summary):
    radio, _, _ = fake_radio()
    radio._line.return_value = summary
    with pytest.raises((ProtocolError, ValueError, KeyError)):
        run_stream(radio, start_us=START)
    assert_failed(radio)


def test_read_timeout_stops_device():
    radio, _, _ = fake_radio()
    radio._read.side_effect = ProtocolError('timeout')
    with pytest.raises(ProtocolError, match='timeout'):
        run_stream(radio, start_us=START)
    assert_failed(radio)


@pytest.mark.parametrize(
    'kwargs',
    [
        {'milliseconds': 0},
        {'period_ns': 1},
        {'yield_phase': 34},
        {'ratio_milli': True},
        {'start_us': -1},
    ],
)
def test_invalid_request_never_reaches_device(kwargs):
    radio, _, _ = fake_radio()
    with pytest.raises(ValueError):
        run_stream(radio, **({'start_us': START} | kwargs))
    radio.command.assert_not_called()


def test_unsupported_firmware_never_gets_command():
    radio, _, _ = fake_radio()
    radio.info = {'caps': []}
    with pytest.raises(ProtocolError):
        run_stream(radio, start_us=START)
    radio.command.assert_not_called()


@pytest.mark.parametrize(
    'begin',
    [
        'DSTREAM BEGIN',
        f'DSTREAM BEGIN 2 {START} 30000 1875000 0 4000 2440 2',
        'DSTREAM BEGIN 1 nonsense 30000 1875000 0 4000 2440 2',
        f'DSTREAM BEGIN 1 {START + 1} 30000 1875000 0 4000 2440 2',
    ],
)
def test_invalid_begin_stops_active_stream(begin):
    radio, _, _ = fake_radio()
    radio.command.return_value = begin
    with pytest.raises((ProtocolError, ValueError)):
        run_stream(radio, start_us=START)
    assert_failed(radio)
    radio._read.assert_not_called()


@pytest.mark.parametrize(
    'field', ['first_trigger_us', 'last_trigger_us', 'end_us', 'skipped', 'max_late_us']
)
def test_summary_timing_disagreement_fails_closed(field):
    radio, _, summary = fake_radio()
    summary[field] += 1
    set_summary(radio, summary)
    with pytest.raises(ProtocolError):
        run_stream(radio, start_us=START)
    assert_failed(radio)


def test_empty_failed_run_has_zero_boundaries():
    radio, _, _ = fake_radio(count=0, status=1)
    with pytest.raises(ProtocolError, match='status 1'):
        run_stream(radio, start_us=START)
    assert_failed(radio)


def test_cooperative_idle_phase_requires_explicit_capability():
    radio, _, _ = fake_radio()
    with pytest.raises(ProtocolError, match='cooperative-idle'):
        run_stream(radio, start_us=START, yield_phase=34)
    radio.command.assert_not_called()
    radio.info['caps'].append('DSTREAMIDLE')
    radio.command.return_value = f'DSTREAM BEGIN 1 {START} 30000 1875000 33 4000 2440 2'
    assert run_stream(radio, start_us=START, yield_phase=34)['summary']['captures'] == 18
