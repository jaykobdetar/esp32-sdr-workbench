"""Experimental timing/coverage utilities. Trigger + N/fs is not measured RF aperture."""

from __future__ import annotations

import struct
import time
import zlib

from .protocol import ProtocolError


def clock_probe(radio, samples=30):
    """Narrowest observed serial RTT interval, not a synchronised hardware clock."""
    if not 1 <= samples <= 1000:
        raise ValueError('Invalid probe count')
    probes = []
    for _ in range(samples):
        before = time.monotonic_ns() / 1000
        line = radio.command('CLOCK?')
        after = time.monotonic_ns() / 1000
        fields = line.split()
        if len(fields) != 2 or fields[0] != 'CLOCK':
            raise ProtocolError('Invalid CLOCK reply')
        device = int(fields[1])
        probes.append(
            dict(
                host_before_us=before,
                host_after_us=after,
                device_us=device,
                offset_low_us=device - after,
                offset_high_us=device - before,
            )
        )
    best = min(probes, key=lambda p: p['host_after_us'] - p['host_before_us'])
    return dict(
        best=best,
        probes=probes,
        offset_us=(best['offset_low_us'] + best['offset_high_us']) / 2,
        uncertainty_us=(best['offset_high_us'] - best['offset_low_us']) / 2,
    )


def read_trace(radio):
    fields = radio.command('TRACEGET').split()
    if len(fields) != 8 or fields[0] != 'TRACE':
        raise ProtocolError('Invalid TRACE header')
    count, first = int(fields[1]), int(fields[2])
    if not 1 <= count <= 4096:
        raise ProtocolError('Trace length outside bounds')
    payload = radio._read(count * 4)
    if zlib.crc32(payload) != int(fields[3], 16):
        raise ProtocolError('Trace CRC mismatch')
    offsets = list(struct.unpack(f'<{count}I', payload))
    if offsets[0] != 0 or any(a >= b for a, b in zip(offsets, offsets[1:], strict=False)):
        raise ProtocolError('Trace timestamps not strictly increasing')
    if int(fields[4]):
        raise ProtocolError('Trace overflow')
    return dict(
        count=count,
        first_trigger_device_us=first,
        offsets_us=offsets,
        transport_crc_valid=True,
        max_schedule_late_us=int(fields[5]),
        skipped_slots=int(fields[6]),
        period_us=int(fields[7]),
    )


def coverage(intervals, start, end):
    """Exact interval union within an explicitly fixed denominator."""
    if not start < end:
        raise ValueError('Empty denominator')
    windows = sorted((max(a, start), min(b, end)) for a, b in intervals if a < end and b > start)
    merged = []
    for a, b in windows:
        if not a < b:
            raise ValueError('Invalid interval')
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    gaps = []
    last = start
    for a, b in merged:
        if a > last:
            gaps.append([last, a])
        last = b
    if last < end:
        gaps.append([last, end])
    covered = sum(b - a for a, b in merged)
    return dict(
        coverage_percent=100 * covered / (end - start),
        covered_us=covered,
        duration_us=end - start,
        gap_count=len(gaps),
        max_gap_us=max((b - a for a, b in gaps), default=0),
        gaps_us=gaps,
    )


def trace_windows(trace, offset_us=0, aperture_us=1023.75):
    if aperture_us <= 0:
        raise ValueError('Invalid aperture')
    return [
        (
            trace['first_trigger_device_us'] + x - offset_us,
            trace['first_trigger_device_us'] + x - offset_us + aperture_us,
        )
        for x in trace['offsets_us']
    ]
