#!/usr/bin/env python3
"""Write-once application packaging. Never opens hardware or flashes anything."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

if __package__:
    from .flash_uf2 import validate_image
else:  # Preserve documented direct-script invocation.
    from flash_uf2 import validate_image

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vendor_state():
    result = {}
    for item in json.loads((ROOT / 'dependencies.json').read_text()):
        path = ROOT / item['path']
        commit = subprocess.check_output(
            ['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True
        ).strip()
        dirty = subprocess.check_output(
            ['git', '-C', str(path), 'status', '--porcelain'], text=True
        ).strip()
        if commit != item['commit'] or dirty:
            raise RuntimeError(f'Dependency must be clean and pinned: {item["path"]}')
        result[item['path']] = {'commit': commit, 'origin': item['url']}
    return result


def require_source_checkout(parser):
    """Fail before writing anything when invoked from an installed host-only wheel."""
    required = ('dependencies.json', 'firmware/Makefile', 'host/make_uf2.py')
    if not all((ROOT / name).is_file() for name in required) or not (ROOT.parent / '.git').exists():
        parser.error(
            'Firmware packaging requires the project Git checkout and pinned vendor '
            'dependencies, not an installed wheel or extracted source archive. '
            'From the checkout run: python nrf52840-transmitter/host/build_firmware.py '
            '--version VERSION. See nrf52840-transmitter/README.md and '
            'nrf52840-transmitter/THIRD_PARTY.md for dependency setup. '
            'Use --dry-run for a host-only plan.'
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', required=True)
    p.add_argument('--output-root', type=Path, default=ROOT / 'artifacts')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?', a.version):
        p.error('Numeric semantic version with optional safe suffix required')
    destination = a.output_root.resolve() / a.version
    if destination.exists():
        raise FileExistsError('Refusing to overwrite existing version')
    if a.dry_run:
        print(json.dumps({'version': a.version, 'flashing': False, 'mode': 'plan'}))
        return
    require_source_checkout(p)
    with (ROOT / '.firmware-build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        vendors = vendor_state()
        sources = sorted(
            p for folder in ('firmware', 'host') for p in (ROOT / folder).iterdir() if p.is_file()
        )
        before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
        destination.mkdir(parents=True)  # atomic reservation; never overwrite
        try:
            subprocess.run(
                ['make', '-C', str(ROOT / 'firmware'), f'VERSION={a.version}'], check=True
            )
            if vendors != vendor_state() or before != {
                str(p.relative_to(ROOT)): sha(p) for p in sources
            }:
                raise RuntimeError('Build inputs changed during build')
            for source in sources:
                target = destination / 'source' / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            for ext in ('bin', 'hex'):
                shutil.copyfile(
                    ROOT / 'firmware/build' / f'rf-test-tx.{ext}', destination / f'rf-test-tx.{ext}'
                )
            subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / 'host/make_uf2.py'),
                    str(destination / 'rf-test-tx.bin'),
                ],
                check=True,
            )
            manifest = {
                'version': a.version,
                'hardware_accessed': False,
                'automatic_flashing': False,
                'validation': 'built_not_hardware_validated',
                'dependencies': vendors,
                'source_sha256': before,
                'uf2': validate_image(destination / 'rf-test-tx.uf2'),
                'compiler': subprocess.check_output(
                    [os.environ.get('CROSS_COMPILE', 'arm-none-eabi-') + 'gcc', '--version'],
                    text=True,
                ).splitlines()[0],
            }
            (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            (destination / 'SHA256SUMS').write_text(
                ''.join(
                    f'{sha(p)}  {p.relative_to(destination)}\n'
                    for p in sorted(destination.rglob('*'))
                    if p.is_file()
                )
            )
        except Exception:
            (destination / 'FAILED.txt').write_text(
                'Incomplete package. No flash attempted. Inspect and choose a new version.\n'
            )
            raise
        finally:
            for item in destination.rglob('*'):
                if item.is_file():
                    item.chmod(0o444)
        print(destination)


if __name__ == '__main__':
    main()
