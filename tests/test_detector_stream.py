import struct
import zlib

import pytest

from sdr_research.detector_stream import END, WIRE, decode_record, run_stream
from sdr_research.protocol import ProtocolError


def record(seq=1, trigger=200, flags=0):
    data = WIRE.pack(b'DSV1', seq, trigger, 12, 40, 9, 0, flags, 1026, 123, 0)
    return data[:-4] + struct.pack('<I', zlib.crc32(data[:-4]))


def test_record():
    assert WIRE.size == 48
    assert decode_record(record())['trigger_us'] == 200
    assert decode_record(record(flags=END))['flags'] == END


@pytest.mark.parametrize('damage', ['short', 'crc', 'magic', 'flags'])
def test_reject_bad_record(damage):
    data = record()
    if damage == 'short':
        data = data[:-1]
    elif damage == 'crc':
        data = data[:-1] + bytes([data[-1] ^ 1])
    elif damage == 'magic':
        data = b'FAIL' + data[4:]
    else:
        data = record(flags=8)
    with pytest.raises(ProtocolError):
        decode_record(data)


@pytest.mark.parametrize(
    'kw',
    [
        dict(milliseconds=0),
        dict(milliseconds=600001),
        dict(period_ns=1599999),
        dict(yield_phase=34),
        dict(start_us=True),
    ],
)
def test_reject_request_without_hardware(kw):
    args = dict(start_us=10000)
    args.update(kw)
    with pytest.raises(ValueError):
        run_stream(None, **args)
