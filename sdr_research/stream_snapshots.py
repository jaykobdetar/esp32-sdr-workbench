"""Bounded sparse packed-I/Q reconstruction. No disk writes or persistent raw cache."""

from __future__ import annotations

import struct
import zlib
from typing import Any

from .protocol import ProtocolError


class SnapshotAssembler:
    """Accept exactly one sequential 40950-byte snapshot; reject loss/corruption.

    Transport CRC is not an over-air packet CRC. Returned packed data is private
    unless a caller explicitly saves it. Never infer full-time raw coverage.
    """

    def __init__(self) -> None:
        self.pending: dict[str, Any] | None = None
        self.completed = 0
        self.last_generation = 0
        self._data = bytearray()

    def feed(self, frame: bytes, records: dict[int, dict[str, int]]) -> dict[str, Any] | None:
        if len(frame) != 48 or zlib.crc32(frame[:44]) != struct.unpack_from('<I', frame, 44)[0]:
            raise ProtocolError('Sparse snapshot frame CRC/length failure')
        if frame[:4] == b'DSI1':
            _, generation, trigger, samples, size, crc, gain, observed, frequency, reserved, _ = (
                struct.unpack('<4sIQIIIIIIII', frame)
            )
            r = records.get(generation)
            if (
                self.pending is not None
                or generation <= self.last_generation
                or samples != 16380
                or size != 40950
                or reserved != 0
                or not 2300 <= frequency <= 2600
            ):
                raise ProtocolError('Invalid sparse snapshot metadata')
            if r is None or (
                r['trigger_us'],
                r['gain_register_at_completion'],
                r['completion_observed_us'],
            ) != (trigger, gain, observed):
                raise ProtocolError('Sparse snapshot does not match timing record')
            self.pending = dict(
                generation=generation,
                trigger_us=trigger,
                samples=samples,
                packed_bytes=size,
                crc32=crc,
                gain_register=gain,
                completion_observed_us=observed,
                frequency_mhz=frequency,
                sample_rate=16_000_000,
                bits=10,
            )
            self._data = bytearray()
            return None
        if frame[:4] != b'DSQ1' or self.pending is None:
            raise ProtocolError('Unexpected sparse snapshot chunk')
        _, generation, offset, size = struct.unpack_from('<4sIII', frame)
        if (
            generation != self.pending['generation']
            or offset != len(self._data)
            or size != min(28, 40950 - offset)
            or not 1 <= size <= 28
            or any(frame[16 + size : 44])
        ):
            raise ProtocolError('Invalid sparse snapshot chunk order/size/padding')
        self._data.extend(frame[16 : 16 + size])
        if len(self._data) != 40950:
            return None
        if zlib.crc32(self._data) != self.pending['crc32']:
            raise ProtocolError('Sparse full snapshot CRC failure')
        result = dict(self.pending, payload=bytes(self._data), transport_crc_valid=True)
        self.last_generation = generation
        self.pending = None
        self._data = bytearray()
        self.completed += 1
        return result
