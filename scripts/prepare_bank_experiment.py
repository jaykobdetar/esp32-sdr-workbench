"""Prepare a separate, opt-in firmware source worktree. Never flashes hardware."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'd23ddddeaabee46d340caba60b038f39946cd534'
EXPERIMENT = ROOT / 'experiments/combined-core-banks'
EVIDENCE = ROOT / 'docs/evidence/combined-core-banks'


def prepare(destination: Path, variant: str) -> Path:
    if variant not in ('combined', 'unicore'):
        raise ValueError('Select combined or unicore')
    destination = destination.resolve()
    if destination.exists() or ROOT == destination or ROOT in destination.parents:
        raise ValueError('Use a new destination outside this checkout')
    manifest = json.loads((EVIDENCE / 'manifest.json').read_text())
    patch = EXPERIMENT / 'experiment.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patch_sha256']:
        raise ValueError('Experiment patch checksum mismatch')
    subprocess.run(
        ['git', '-C', str(ROOT), 'worktree', 'add', '--detach', str(destination), BASE], check=True
    )
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=destination, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=destination, check=True)
    if variant == 'unicore':
        (destination / 'firmware/sdkconfig.defaults.esp32').write_bytes(
            (EXPERIMENT / 'unicore-sdkconfig.defaults').read_bytes()
        )
        for name in (
            'firmware/FIRMWARE_VARIANT',
            'firmware/tests/test_release_variant.py',
            'sdr_research/calibration.py',
        ):
            path = destination / name
            path.write_text(
                path.read_text().replace(
                    'esp32-bank-core1-combined-v5', 'esp32-bank-unicore-control-v5'
                )
            )
    sources = json.loads((EVIDENCE / 'shared-source-identity.json').read_text())['sources']
    for name, expected in sources.items():
        if hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Measured C source differs: {name}')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--variant', choices=('combined', 'unicore'), default='combined')
    args = parser.parse_args()
    print(prepare(args.destination, args.variant))


if __name__ == '__main__':
    main()
