"""Offline verification of sanitized dual-stream timing evidence; no hardware access.

CRC establishes recorded transport integrity, not physical RF coverage. Clock
sensitivity remains assumption-based. Raw RF and device identities are not needed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from .dual_stream_campaign import analyze_run

MAX_DECOMPRESSED = 256 * 1024 * 1024


def verify_file(path: Path) -> dict:
    with gzip.open(path, 'rb') as stream:
        raw = stream.read(MAX_DECOMPRESSED + 1)
    if len(raw) > MAX_DECOMPRESSED:
        raise ValueError('Evidence exceeds the decompressed size limit')
    document = json.loads(raw)
    if document.get('schema') != 'dual-stream-evidence-v1':
        raise ValueError('Unsupported evidence schema')
    analyses = []
    for row in document['runs']:
        analysis = analyze_run(row, document['anchors'])
        if analysis['status'] != 'verified-telemetry':
            raise ValueError(f'Invalid trial {row.get("index")}: {analysis.get("reason")}')
        analyses.append(dict(index=row['index'], analysis=analysis))
    if not analyses:
        raise ValueError('Evidence contains no trials')
    return dict(source=document['source'], trials=analyses)


def verify_directory(directory: Path) -> dict:
    manifest = json.loads((directory / 'manifest.json').read_text())
    results = {}
    for item in manifest['timing_files']:
        name = item['file']
        if Path(name).name != name or not name.endswith('.json.gz'):
            raise ValueError('Evidence filename must be a local .json.gz basename')
        path = directory / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'Checksum mismatch: {name}')
        results[name] = verify_file(path)
    if not results:
        raise ValueError('Manifest contains no timing evidence')
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_directory(args.directory), indent=2))


if __name__ == '__main__':
    main()
