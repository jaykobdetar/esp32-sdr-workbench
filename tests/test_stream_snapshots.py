import struct
import zlib

import pytest

from sdr_research.protocol import ProtocolError
from sdr_research.stream_snapshots import SnapshotAssembler


def framed(data):
    return data + struct.pack('<I', zlib.crc32(data))


def fixture_frames():
    payload = bytes(i % 251 for i in range(40950))
    record = {
        1024: dict(trigger_us=123456, gain_register_at_completion=55, completion_observed_us=1024)
    }
    meta = framed(
        struct.pack(
            '<4sIQIIIIIII',
            b'DSI1',
            1024,
            123456,
            16380,
            len(payload),
            zlib.crc32(payload),
            55,
            1024,
            2440,
            0,
        )
    )
    chunks = [
        framed(
            struct.pack(
                '<4sIII28s',
                b'DSQ1',
                1024,
                off,
                len(payload[off : off + 28]),
                payload[off : off + 28],
            )
        )
        for off in range(0, len(payload), 28)
    ]
    return payload, record, meta, chunks


def test_complete_snapshot_and_transport_validation():
    payload, records, meta, chunks = fixture_frames()
    a = SnapshotAssembler()
    assert a.feed(meta, records) is None
    for chunk in chunks[:-1]:
        assert a.feed(chunk, records) is None
    result = a.feed(chunks[-1], records)
    assert result['payload'] == payload
    assert result['transport_crc_valid']
    assert a.pending is None and a.completed == 1
    with pytest.raises(ProtocolError):
        a.feed(meta, records)  # replay


@pytest.mark.parametrize(
    'failure', ['crc', 'missing', 'duplicate', 'metadata', 'timing', 'fullcrc', 'padding']
)
def test_reject_invalid_snapshots(failure):
    _, records, meta, chunks = fixture_frames()
    a = SnapshotAssembler()
    if failure == 'timing':
        records[1024]['trigger_us'] += 1
    if failure == 'fullcrc':
        meta = framed(meta[:24] + struct.pack('<I', 0) + meta[28:44])
    if failure == 'metadata':
        meta = framed(meta[:20] + struct.pack('<I', 1000000000) + meta[24:44])
    with pytest.raises(ProtocolError):
        a.feed(meta, records)
        if failure == 'crc':
            a.feed(chunks[0][:-1] + bytes([chunks[0][-1] ^ 1]), records)
        elif failure == 'missing':
            a.feed(chunks[1], records)
        elif failure == 'duplicate':
            a.feed(chunks[0], records)
            a.feed(chunks[0], records)
        else:
            for chunk in chunks[:-1]:
                a.feed(chunk, records)
            if failure == 'padding':
                chunk = chunks[-1]
                a.feed(framed(chunk[:43] + b'X'), records)
            else:
                a.feed(chunks[-1], records)


def test_stream_integration_callback_and_final_count():
    from test_detector_stream_client import START, fake_radio, set_summary

    from sdr_research.detector_stream import run_stream

    radio, frames, summary = fake_radio(count=1024)
    radio.info['caps'].append('DSTREAMIQ')
    radio.command.return_value += ' 1024 0'
    payload, _, meta, chunks = fixture_frames()
    trigger = START + 1024 * 1875
    meta = framed(
        meta[:8] + struct.pack('<Q', trigger) + meta[16:28] + struct.pack('<I', 40) + meta[32:44]
    )
    frames[-1:-1] = [meta, *chunks]
    radio._read.side_effect = frames
    summary.update(iq_produced=1, iq_sent=1, iq_busy_skips=0)
    set_summary(radio, summary)
    received = []
    result = run_stream(
        radio, start_us=START, snapshot_every=1024, on_snapshot=received.append, keep_records=False
    )
    assert result['snapshots_received'] == 1 and not result['records']
    assert received[0]['payload'] == payload
    assert radio.command.call_args.args[0].startswith('DSTREAMIQ ')
