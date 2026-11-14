import struct
import zlib

import pytest

from sdr_research.dual_timing import coverage, read_trace, trace_windows
from sdr_research.protocol import ProtocolError


def test_union_not_duty_sum():
    assert coverage([(0, 63), (0, 63)], 0, 100)['coverage_percent'] == 63
    assert coverage([(0, 63), (37, 100)], 0, 100)['coverage_percent'] == 100
    assert coverage([(0, 63), (20, 83)], 0, 100)['coverage_percent'] == 83


def test_gaps_edges_and_clip():
    result = coverage([(-1, 2), (5, 8), (6, 7), (12, 14)], 0, 10)
    assert result['covered_us'] == 5
    assert result['gaps_us'] == [[2, 5], [8, 10]]
    assert result['max_gap_us'] == 3
    assert coverage([], 0, 10)['max_gap_us'] == 10


def test_trace_parser():
    class Radio:
        def __init__(self, values, crc_delta=0, overflow=0):
            self.data = struct.pack(f'<{len(values)}I', *values)
            self.header = f'TRACE {len(values)} 1000 {zlib.crc32(self.data) ^ crc_delta:08x} {overflow} 4 0 1800'

        def command(self, command):
            assert command == 'TRACEGET'
            return self.header

        def _read(self, size):
            assert size == len(self.data)
            return self.data

    trace = read_trace(Radio([0, 1800]))
    assert trace_windows(trace, 100, 1000) == [(900, 1900), (2700, 3700)]
    for radio in (Radio([0, 1], 1), Radio([0, 0]), Radio([1, 2]), Radio([0], overflow=1)):
        with pytest.raises(ProtocolError):
            read_trace(radio)
