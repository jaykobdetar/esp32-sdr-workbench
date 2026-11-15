"""Offline exact CAP16 quantization replay on private CAP20 campaign recordings.

Does not open serial ports or modify input evidence. Prints an aggregate report.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from .analyze_nrf_iq import decode
from .four_receiver_packets import accepted


def quantize_iq8(iq):
    """Mirror pack_iq8's upper-eight-bit truncation, including negative Q sign."""
    x = np.asarray(iq)
    if x.ndim != 1 or not np.iscomplexobj(x) or not np.all(np.isfinite(x)):
        raise ValueError('Finite one-dimensional complex IQ required')
    i = np.rint(x.real * 512)
    q = np.rint(-x.imag * 512)
    if (
        np.any(i < -512)
        or np.any(i > 511)
        or np.any(q < -512)
        or np.any(q > 511)
        or not np.array_equal(x, (i - 1j * q) / 512)
    ):
        raise ValueError('Input is not exact decoded signed IQ10')
    return ((i.astype(np.int16) >> 2) - 1j * (q.astype(np.int16) >> 2)) / 128


def replay(directory):
    root = Path(directory).resolve()
    report = json.loads((root / 'results.json').read_text())
    totals = dict(
        captures=0,
        on_captures=0,
        off_captures=0,
        original_on_observations=0,
        iq8_on_observations=0,
        lost_observations=0,
        gained_observations=0,
        original_off_observations=0,
        iq8_off_observations=0,
    )
    before_union, after_union = set(), set()
    for row in report['captures']:
        if row.get('transport_crc_valid') is not True:
            raise ValueError('Invalid original transport')
        settings = row.get('metadata', {}).get('settings', {})
        if settings.get('bits') != 10 or settings.get('rate_hz') != 16000000:
            raise ValueError('Replay requires 16 MS/s IQ10 source captures')
        path = (root / row['file']).resolve()
        if path.parent != root:
            raise ValueError('Capture must be directly inside campaign directory')
        iq = np.load(path, allow_pickle=False)
        if len(iq) != 16380:
            raise ValueError('Unexpected capture length')
        baseline = set(accepted(decode(iq, 16000000, 2, 16)))
        cached = set(accepted(row['decoder']))
        if baseline != cached:
            raise ValueError('Original decoder replay differs from saved evidence')
        candidate = set(accepted(decode(quantize_iq8(iq), 16000000, 2, 16)))
        totals['captures'] += 1
        if row['condition'] == 'ON':
            totals['on_captures'] += 1
            totals['original_on_observations'] += len(baseline)
            totals['iq8_on_observations'] += len(candidate)
            totals['lost_observations'] += len(baseline - candidate)
            totals['gained_observations'] += len(candidate - baseline)
            before_union |= baseline
            after_union |= candidate
        elif row['condition'] == 'OFF':
            totals['off_captures'] += 1
            totals['original_off_observations'] += len(baseline)
            totals['iq8_off_observations'] += len(candidate)
        else:
            raise ValueError('Unknown condition')
    totals.update(
        original_unique_packets=len(before_union),
        iq8_unique_packets=len(after_union),
        lost_unique_packets=len(before_union - after_union),
        gained_unique_packets=len(after_union - before_union),
        note='Offline deterministic quantization only, not CAP16 hardware validation, '
        'new captures, a throughput measurement, or universal decoder equivalence.',
    )
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.directory), indent=2))


if __name__ == '__main__':
    main()
