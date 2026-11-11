#!/usr/bin/env python3
"""Convert application binary at the verified 0x23000 start, then safety-check."""

import argparse
import struct
from pathlib import Path

from flash_uf2 import validate_image

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('binary', type=Path)
a = p.parse_args()
b = a.binary.read_bytes()
b += b'\xff' * ((-len(b)) % 256)
n = len(b) // 256
out = bytearray()
for i in range(n):
    out += (
        struct.pack('<8I', 0x0A324655, 0x9E5D5157, 0x2000, 0x23000 + 256 * i, 256, i, n, 0xADA52840)
        + b[256 * i : 256 * (i + 1)]
        + bytes(220)
        + struct.pack('<I', 0x0AB16F30)
    )
f = a.binary.with_suffix('.uf2')
f.write_bytes(out)
print(f, validate_image(f))
