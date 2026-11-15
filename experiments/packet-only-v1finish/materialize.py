#!/usr/bin/env python3
"""Reconstruct opt-in candidate in a NEW directory. Never build/flash implicitly."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists():
        parser.error('Destination must not already exist')
    pins = json.loads((HERE / 'manifest.json').read_text())
    patch = HERE / 'candidate.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != pins['patch_sha256']:
        raise ValueError('Candidate patch hash mismatch')
    subprocess.run(
        [
            sys.executable,
            str(HERE.parent / 'nov14-research/materialize.py'),
            'core-bank-v9',
            str(destination),
        ],
        check=True,
    )
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=destination, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=destination, check=True)
    for name, digest in pins['source_sha256'].items():
        if hashlib.sha256((destination / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Materialized source mismatch: ' + name)
    print('Verified candidate sources; no hardware accessed.')


if __name__ == '__main__':
    main()
