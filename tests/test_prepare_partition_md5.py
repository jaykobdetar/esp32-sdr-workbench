import hashlib
import struct

import pytest

from scripts.prepare_partition_md5 import add_checksum


def sector():
    entries = b''.join(
        struct.pack('<HBBII16sI', 0x50AA, kind, sub, offset, size, label, 0)
        for kind, sub, offset, size, label in (
            (1, 2, 0x9000, 0x6000, b'nvs'),
            (0, 0, 0x10000, 0x100000, b'factory'),
        )
    )
    return entries + b'\xff' * (4096 - len(entries))


def test_checksum_only_preserves_entries_and_padding():
    original = sector()
    result = add_checksum(original)
    assert result[:64] == original[:64]
    assert result[64:80] == b'\xeb\xeb' + b'\xff' * 14
    assert result[80:96] == hashlib.md5(original[:64]).digest()
    assert result[96:] == original[96:]
    with pytest.raises(ValueError):
        add_checksum(result)


@pytest.mark.parametrize('data', [b'', b'\xff' * 4096, sector()[:-1], sector() + b'\xff'])
def test_reject_invalid_sector(data):
    with pytest.raises(ValueError):
        add_checksum(data)


def test_reject_nonempty_padding_and_overlapping_entries():
    data = bytearray(sector())
    data[-1] = 0
    with pytest.raises(ValueError):
        add_checksum(bytes(data))
    data = bytearray(sector())
    struct.pack_into('<I', data, 32 + 4, 0x9000)
    with pytest.raises(ValueError):
        add_checksum(bytes(data))
