#!/usr/bin/env python3
"""Materialize a research snapshot in a NEW directory; never flash or modify main."""

import argparse
import hashlib
import io
import json
import pathlib
import shutil
import subprocess
import tarfile

BASE = 'd23ddddeaabee46d340caba60b038f39946cd534'
HERE = pathlib.Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('variant', choices=['core-bank-v9', 'compact-v2', 'nrf-trace-exp2'])
    p.add_argument('destination', type=pathlib.Path)
    a = p.parse_args()
    dest = a.destination.resolve()
    if dest.exists():
        p.error('destination must not exist; no existing files are overwritten')
    source = HERE / a.variant
    pins = json.loads((source / 'overlay-sha256.json').read_text())
    for rel, h in pins.items():
        f = source / 'overlay' / rel
        if hashlib.sha256(f.read_bytes()).hexdigest() != h:
            raise ValueError('overlay hash mismatch: ' + rel)
    archive = subprocess.check_output(['git', '-C', str(HERE.parents[1]), 'archive', BASE])
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        t.extractall(dest, filter='data')
    shutil.copytree(source / 'overlay', dest, dirs_exist_ok=True)
    # No code edits: fixtures and collector copied alongside for optional test portability.
    shutil.copytree(HERE / 'fixtures', dest / 'publication-fixtures')
    shutil.copytree(HERE / 'host', dest / 'publication-host')
    print(dest)


if __name__ == '__main__':
    main()
