import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
from flash_uf2 import APP_START, validate_image


def uf2(path, addr=APP_START, flags=0x2000, family=0xADA52840, marker=True, reset=None):
    payload = bytearray(256)
    struct.pack_into('<II', payload, 0, 0x20040000, reset or (APP_START + 9))
    if marker:
        payload[32 : 32 + len(b'UF2_ENTRY_0x57_v1')] = b'UF2_ENTRY_0x57_v1'
    b = (
        struct.pack('<8I', 0x0A324655, 0x9E5D5157, flags, addr, 256, 0, 1, family)
        + payload
        + bytes(220)
        + struct.pack('<I', 0x0AB16F30)
    )
    path.write_bytes(b)
    return path


def test_safe_image(tmp_path):
    r = validate_image(uf2(tmp_path / 'a.uf2'))
    assert r['flash_start'] == 0x23000 and r['flash_end'] == 0x23100


@pytest.mark.parametrize(
    'addr', [0, 0x1000, 0x22000, 0x40000, 0xEA000, 0xF4000, 0xFD800, 0xFE000, 0xFF000, 0x10001000]
)
def test_reject_protected_addresses(tmp_path, addr):
    with pytest.raises(ValueError):
        validate_image(uf2(tmp_path / 'a.uf2', addr=addr))


@pytest.mark.parametrize(
    'kwargs',
    [
        {'flags': 0},
        {'flags': 0x2001},
        {'family': 0xD663823C},
        {'marker': False},
        {'reset': 0xF4001},
    ],
)
def test_reject_special_images(tmp_path, kwargs):
    with pytest.raises(ValueError):
        validate_image(uf2(tmp_path / 'a.uf2', **kwargs))


def test_reject_truncated(tmp_path):
    p = uf2(tmp_path / 'a.uf2')
    p.write_bytes(p.read_bytes()[:-1])
    with pytest.raises(ValueError):
        validate_image(p)


def test_reject_duplicate(tmp_path):
    p = uf2(tmp_path / 'a.uf2')
    p.write_bytes(p.read_bytes() * 2)
    with pytest.raises(ValueError):
        validate_image(p)
