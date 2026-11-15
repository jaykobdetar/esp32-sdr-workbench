#!/usr/bin/env python3
"""Generate the version record embedded in the firmware, once per build."""

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MARKER = 'ESP-SDR-VERSION:'


def metadata(root, profile, paused_extract=False):
    try:
        revision = subprocess.check_output(
            ['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True
        ).strip()
        dirty = subprocess.check_output(
            ['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], text=True
        )
        if dirty:
            revision += '-dirty'
    except (OSError, subprocess.CalledProcessError):
        revision = 'unknown'
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    value = dict(revision=revision, build_date=stamp[:10], build_timestamp=stamp, profile=profile)
    variant_file = Path(root) / 'FIRMWARE_VARIANT'
    if profile == 'esp32' and variant_file.exists():
        variant = variant_file.read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', variant):
            raise ValueError('Invalid firmware variant')
        value['firmware_variant'] = variant
    if paused_extract:
        if profile != 'esp32':
            raise ValueError('Paused extraction requires esp32')
        value['firmware_variant'] = 'esp32-paused-extract-compact-research-v2'
        value['paused_packet_extract_protocol'] = 1
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--paused-extract', action='store_true')
    args = parser.parse_args()
    record = MARKER + json.dumps(
        metadata(args.root, args.profile, args.paused_extract), separators=(',', ':')
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        '#pragma once\n#define ESP_SDR_VERSION_RECORD ' + json.dumps(record) + '\n'
    )
