import copy
import io
import json
import zlib

import pytest

from scripts.four_receiver_packets import configuration
from scripts.packet_only_campaign import packet_recovery, run, validate_source
from sdr_research.packet_only import (
    FIELDS,
    INFO,
    air_crc,
    collect,
    known_payload,
    validate_lines,
)
from sdr_research.protocol import ProtocolError


def objects(with_packets=True):
    begin = dict(
        kind='BEGIN', count=3, period_us=10000, cap=16, hz=240000000, core=1, start_us=100000
    )
    result = [begin]
    for slot in (0, 2):
        result.append(
            dict(
                kind='WINDOW',
                slot=slot,
                trigger_us=100020 + slot * 10000,
                scheduled_us=100000 + slot * 10000,
                capture_us=1024,
                decode_us=6244,
                cycles=1498560,
                packets=int(with_packets),
                output_drops=0,
                busy=0,
                incomplete=1,
            )
        )
        if with_packets:
            result.append(
                dict(
                    kind='PACKET',
                    slot=slot,
                    source_sequence=5,
                    address_sample=40,
                    phase=0,
                    polarity=1,
                    address='efcdab89c3',
                    air_crc='db49',
                    payload='52465458050000000d0e0f1011121314',
                )
            )
    result.append(
        dict(
            kind='END',
            status=0,
            completed=2,
            decoded=2,
            decode_errors=0,
            decoder_status=0,
            faults=0,
            skipped=1,
            cancelled=0,
            packets=2 * int(with_packets),
            output_drops=0,
            busy=0,
            incomplete=2,
            tx_failed=0,
            decode_max_us=6244,
            cycles_max=1498560,
            decode_total_us=12488,
            cycles_total=2997120,
            gap_ns=18976250,
            max_gap_ns=18976250,
            session_us=50000,
        )
    )
    return result


def wire(values):
    lines = []
    for seq, obj in enumerate(values):
        kind = obj['kind']
        body = f'PONLY {seq} {kind}' + (' 1' if kind == 'BEGIN' else '')
        body += ''.join(f' {key}={obj[key]}' for key in FIELDS[kind])
        lines.append(body + f' *{zlib.crc32(body.encode()):08x}')
    return lines


def source(**changes):
    value = dict(
        configuration(0),
        hop_list=[],
        payload_hex='',
        version='0.2.2',
        healthy=True,
        errors=0,
        timing_saturated=False,
        running=False,
        uptime_ms=1000,
        attempted=10,
        completed=10,
        scheduled=12,
        missed_slots=2,
        elapsed_us=10000,
        first_end_us=500,
        last_end_us=9000,
    )
    value.update(changes)
    return value


def fresh_source():
    return source(running=True, attempted=0, completed=0, scheduled=0, missed_slots=0, elapsed_us=7)


def test_complete_contract_skips_and_duplicates():
    result = validate_lines(wire(objects()), 3, 10000, 16)
    assert result['unique_sequences'] == [5]
    assert result['accepted_observations'] == 2
    assert result['skipped_slots'] == 1
    assert result['incomplete_candidates'] == 2
    assert air_crc(known_payload(5)) == 0xDB49


@pytest.mark.parametrize(
    'field,value',
    [
        ('payload', '00' * 16),
        ('air_crc', 'ffff'),
        ('address', '00' * 5),
        ('phase', 8),
        ('polarity', 0),
        ('source_sequence', 4294967296),
        ('address_sample', 16379),
    ],
)
def test_packet_forgery_or_bad_geometry(field, value):
    data = objects()
    data[2][field] = value
    with pytest.raises(ProtocolError):
        validate_lines(wire(data), 3, 10000, 16)


@pytest.mark.parametrize(
    'field,value',
    [
        ('status', 3),
        ('decoded', 1),
        ('completed', 1),
        ('skipped', 0),
        ('packets', 1),
        ('decode_errors', 1),
        ('decoder_status', 1),
        ('faults', 1),
        ('cancelled', 1),
        ('tx_failed', 1),
        ('decode_max_us', 1),
        ('cycles_max', 1),
        ('decode_total_us', 1),
        ('cycles_total', 1),
        ('gap_ns', 1),
        ('max_gap_ns', 1),
    ],
)
def test_terminal_failure_or_accounting(field, value):
    data = objects()
    data[-1][field] = value
    with pytest.raises(ProtocolError):
        validate_lines(wire(data), 3, 10000, 16)


def test_cap_loss_is_not_salvaged():
    data = objects()
    data[1]['output_drops'] = data[-1]['output_drops'] = 1
    with pytest.raises(ProtocolError, match='output-cap'):
        validate_lines(wire(data), 3, 10000, 16)


@pytest.mark.parametrize('mutation', ['crc', 'missing-end', 'missing-packet', 'reorder', 'unknown'])
def test_transport_and_message_order_rejection(mutation):
    data = objects()
    lines = wire(data)
    if mutation == 'crc':
        lines[1] = lines[1].replace('trigger_us=100020', 'trigger_us=100021')
    elif mutation == 'missing-end':
        lines.pop()
    elif mutation == 'missing-packet':
        data.pop(2)
        lines = wire(data)
    elif mutation == 'reorder':
        data[1], data[2] = data[2], data[1]
        lines = wire(data)
    else:
        lines[0] = lines[0].replace('BEGIN', 'OTHER')
    with pytest.raises(ProtocolError):
        validate_lines(lines, 3, 10000, 16)


class Serial(io.BytesIO):
    def flush(self):
        pass


class FakeRadio:
    failed = False

    def __init__(self, lines):
        self.lines = iter(lines)
        self.serial = Serial()

    def command(self, command):
        assert command == 'PKTONLY 3 10000 16'
        return next(self.lines)

    def _line(self, deadline):
        try:
            return next(self.lines)
        except StopIteration:
            raise TimeoutError('missing terminal') from None


def test_collect_preserves_bad_line_and_poisoned_framing():
    lines = wire(objects())
    lines[2] = lines[2][:-1] + ('0' if lines[2][-1] != '0' else '1')
    r, saved = FakeRadio(lines), []
    with pytest.raises(ProtocolError):
        collect(r, 3, 10000, 16, on_line=saved.append)
    assert saved == lines[:3]
    assert r.failed is True
    assert r.serial.getvalue() == b'STOP\n'


def test_stop_terminal_rejected_not_recall():
    data = objects()
    data[-1]['status'] = 3
    r, saved = FakeRadio(wire(data)), []
    with pytest.raises(ProtocolError):
        collect(r, 3, 10000, 16, on_line=saved.append, stop_after_windows=1)
    assert len(saved) == len(data)
    assert r.serial.getvalue() == b'STOP\n'
    assert r.failed is True


def test_packet_denominator_and_source_off_control():
    off = dict(condition='OFF', stream=validate_lines(wire(objects(False)), 3, 10000, 16))
    on = dict(condition='ON', stream=validate_lines(wire(objects()), 3, 10000, 16))
    result = packet_recovery([off, on], fresh_source(), source(), configuration(0))
    assert result['unique_packets'] == 1
    assert result['duplicate_observations'] == 1
    assert result['recovery_percent'] == 10
    with pytest.raises(ValueError, match='denominator'):
        packet_recovery([off, on], fresh_source(), source(completed=9), configuration(0))
    bad = copy.deepcopy(off)
    bad['stream'] = on['stream']
    with pytest.raises(ValueError, match='OFF'):
        packet_recovery([bad, on], fresh_source(), source(), configuration(0))


@pytest.mark.parametrize(
    'changes',
    [
        dict(running=False),
        dict(attempted=1),
        dict(completed=1),
        dict(scheduled=1),
        dict(missed_slots=1),
        dict(elapsed_us=-1),
    ],
)
def test_source_reset_and_timing_required(changes):
    start = fresh_source()
    start.update(changes)
    with pytest.raises(ValueError):
        validate_source(start, source(), configuration(0))


def test_campaign_source_off_smoke_and_cleanup_failure(tmp_path, monkeypatch):
    import scripts.packet_only_campaign as campaign

    class RX:
        info = {
            'version': 'VERSION '
            + json.dumps({'firmware_variant': 'esp32-packet-only-bounded-v1'}),
            'caps': ['PKTONLY', 'CALHASH'],
        }
        closed = False

        def connect(self):
            return self.info

        def command(self, command):
            assert command == 'PKTONLY?'
            return INFO

        def configure(self, *_):
            pass

        def close(self):
            self.closed = True

    class TX:
        stops = 0

        def stop(self):
            self.stops += 1
            if self.stops == 2:
                raise RuntimeError('STOP failed')
            return source()

        def status(self):
            return source()

        def configure(self, **_):
            return source()

    monkeypatch.setattr(
        campaign, 'calibration', lambda *args: [{'sha256': 'a' * 64, 'bytes': 1904, 'device_us': 1}]
    )

    def reader(radio, count, period, cap, on_line):
        for line in wire(objects(False)):
            on_line(line)
        return validate_lines(wire(objects(False)), count, period, cap)

    monkeypatch.setattr(campaign, 'collect', reader)
    rx, tx = RX(), TX()
    result = run(rx, tx, tmp_path, count=3, off_only=True)
    assert result['status'] == 'failed'
    assert result['cleanup_errors'] == ["RuntimeError('STOP failed')"]
    assert (tmp_path / 'off.wire.txt').read_text().startswith('PONLY 0 BEGIN')
    assert rx.closed
    assert 'analysis' not in result


def test_normal_collector_preserves_complete_transcript():
    lines = wire(objects())
    radio, saved = FakeRadio(lines), []
    result = collect(radio, 3, 10000, 16, on_line=saved.append)
    assert result['status'] == 'verified'
    assert saved == lines
    assert not radio.failed
    assert radio.serial.getvalue() == b''


def test_end_missing_keeps_partial_evidence():
    lines = wire(objects())[:-1]
    radio, saved = FakeRadio(lines), []
    with pytest.raises(TimeoutError):
        collect(radio, 3, 10000, 16, on_line=saved.append)
    assert saved == lines
    assert radio.failed
    assert radio.serial.getvalue() == b'STOP\n'


@pytest.mark.parametrize('method', ['write', 'flush'])
def test_collector_interrupt_cleanup_preserves_primary(method):
    radio = FakeRadio(['invalid frame'])

    def interrupt(*_):
        raise KeyboardInterrupt('STOP interrupted')

    setattr(radio.serial, method, interrupt)
    with pytest.raises(ProtocolError):
        collect(radio, 3, 10000, 16)
    assert radio.failed
    assert 'STOP interrupted' in radio.packet_only_cleanup_error


@pytest.mark.parametrize('failure', ['stop', 'close', 'receipt'])
def test_campaign_interrupt_cleanup_preserves_primary(tmp_path, monkeypatch, failure):
    import scripts.packet_only_campaign as campaign

    class RX:
        serial = Serial()
        closed = False

        def close(self):
            self.closed = True
            if failure == 'close':
                raise KeyboardInterrupt('RELEASE interrupted')

    class TX:
        calls = 0

        def stop(self):
            self.calls += 1
            if self.calls == 1:
                raise ValueError('primary failure')
            if failure == 'stop':
                raise KeyboardInterrupt('STOP interrupted')
            return {'running': False}

    if failure == 'receipt':

        def broken_save(*_):
            raise OSError('disk failed')

        monkeypatch.setattr(campaign, 'atomic_write_json', broken_save)
    rx = RX()
    with pytest.raises(ValueError, match='primary failure') as caught:
        run(rx, TX(), tmp_path, count=3, off_only=True)
    assert rx.closed and rx.serial.closed
    if failure == 'receipt':
        assert 'disk failed' in caught.value.__notes__[0]
    else:
        result = json.loads((tmp_path / 'results.json').read_text())
        assert result['status'] == 'failed'
        assert result['error'] == "ValueError('primary failure')"
        assert result['cleanup_errors']


def test_unqualified_core_rejected():
    data = objects()
    data[0]['core'] = 0
    with pytest.raises(ProtocolError, match='CPU/core'):
        validate_lines(wire(data), 3, 10000, 16)


def test_candidate_emitter_synthetic_interoperability():
    # Actual C emitter with fake hardware and synthetic decoded sequence42.
    # This is a wire interoperability fixture, never RF evidence.
    from pathlib import Path

    lines = (
        (Path(__file__).parent / 'fixtures/packet-only-synthetic-wire.txt').read_text().splitlines()
    )
    result = validate_lines(lines, 3, 10000, 16)
    assert result['accepted_observations'] == 3
    assert result['unique_sequences'] == [42]
