#!/usr/bin/env python3
"""Convert application binary at the verified 0x23000 start, then safety-check."""

import argparse
import struct
from pathlib import Path

if __package__:
    from .flash_uf2 import APP_START, validate_image
else:  # Preserve documented direct-script invocation.
    from flash_uf2 import APP_START, validate_image

PAYLOAD_BYTES = 256
BLOCK_BYTES = 512
HEADER = struct.Struct('<8I')
TRAILER = struct.Struct('<I')


def encode_blocks(binary: bytes) -> bytes:
    """Encode contiguous application blocks; the updater remains the validation authority."""
    padded = binary + b'\xff' * ((-len(binary)) % PAYLOAD_BYTES)
    total = len(padded) // PAYLOAD_BYTES
    out = bytearray()
    for index in range(total):
        offset = index * PAYLOAD_BYTES
        out.extend(
            HEADER.pack(
                0x0A324655,
                0x9E5D5157,
                0x2000,
                APP_START + offset,
                PAYLOAD_BYTES,
                index,
                total,
                0xADA52840,
            )
        )
        out.extend(padded[offset : offset + PAYLOAD_BYTES])
        out.extend(bytes(BLOCK_BYTES - HEADER.size - PAYLOAD_BYTES - TRAILER.size))
        out.extend(TRAILER.pack(0x0AB16F30))
    return bytes(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args(argv)
    output = args.binary.with_suffix('.uf2')
    output.write_bytes(encode_blocks(args.binary.read_bytes()))
    print(output, validate_image(output))


if __name__ == '__main__':
    main()
