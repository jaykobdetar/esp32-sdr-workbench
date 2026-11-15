"""Offline-only checksum completion for a reviewed legacy ESP32 partition sector.

Never flashes hardware. Input must be a private verified 4096-byte table sector.
Output is device-local recovery material, not a generic replacement table.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


def add_checksum(sector: bytes) -> bytes:
    if len(sector) != 4096:
        raise ValueError('Exactly one 4096-byte partition-table sector required')
    end = 0
    ranges = []
    while end < 0xC00 and sector[end : end + 2] == b'\xaa\x50':
        _, kind, subtype, offset, size, label, flags = struct.unpack(
            '<HBBII16sI', sector[end : end + 32]
        )
        if not size or offset < 0x9000 or offset % 4096 or size % 4096:
            raise ValueError('Unaligned or invalid partition region')
        if offset + size > 0x400000 or any(offset < b and a < offset + size for a, b in ranges):
            raise ValueError('Overlapping or outside-4MB partition region')
        if kind == 0 and offset % 65536:
            raise ValueError('Unaligned application')
        if not label.split(b'\0')[0] or flags != 0:
            raise ValueError('Unsupported partition label or flags')
        ranges.append((offset, offset + size))
        end += 32
    if not end or end + 32 > 0xC00:
        raise ValueError('Missing entries or no checksum slot')
    if sector[end:] != b'\xff' * (4096 - end):
        raise ValueError('Existing checksum or nonempty trailing data; do not replace')
    trailer = b'\xeb\xeb' + b'\xff' * 14 + hashlib.md5(sector[:end]).digest()
    result = sector[:end] + trailer + sector[end + 32 :]
    assert result[:end] == sector[:end] and result[end + 32 :] == sector[end + 32 :]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sector', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    data = args.sector.read_bytes()
    if hashlib.sha256(data).hexdigest() != args.expected_sha256:
        parser.error('Input does not match reviewed sector SHA256')
    result = add_checksum(data)
    with args.output.open('xb') as stream:
        stream.write(result)
    print(
        'Prepared checksum-only sector; no hardware opened. Verify board identity and recovery before use.'
    )


if __name__ == '__main__':
    main()
