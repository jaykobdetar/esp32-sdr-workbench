#!/usr/bin/env python3
"""Count signed ADC endpoint codes in a local cf32_le SigMF file; no uploads."""

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path


def count_endpoints(data, bits):
    if bits not in (8, 10) or len(data) % 8:
        raise ValueError('Require 8/10-bit source and complete cf32_le pairs')
    scale = 1 << (bits - 1)
    low, high = -scale, scale - 1
    counts = dict(
        samples=0,
        i_endpoint_samples=0,
        wire_q_endpoint_samples=0,
        either_component_endpoint_samples=0,
    )
    for real, imag in struct.iter_unpack('<ff', data):
        i, q = real * scale, -imag * scale
        if not all(math.isfinite(v) and v.is_integer() and low <= v <= high for v in (i, q)):
            raise ValueError('Capture is not exactly on the expected signed ADC lattice')
        ir, qr = i in (low, high), q in (low, high)
        counts['samples'] += 1
        counts['i_endpoint_samples'] += ir
        counts['wire_q_endpoint_samples'] += qr
        counts['either_component_endpoint_samples'] += ir or qr
    counts['either_component_endpoint_percent'] = (
        (100 * counts['either_component_endpoint_samples'] / counts['samples'])
        if counts['samples']
        else 0.0
    )
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('metadata', type=Path)
    a = p.parse_args()
    meta = json.loads(a.metadata.read_text())
    if meta['global']['core:datatype'] != 'cf32_le':
        raise ValueError('Only cf32_le recordings are supported')
    path = a.metadata.with_suffix('.sigmf-data')
    data = path.read_bytes()
    result = count_endpoints(data, meta['global']['sdr_research:timing']['bits'])
    result['data_sha256'] = hashlib.sha256(data).hexdigest()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
