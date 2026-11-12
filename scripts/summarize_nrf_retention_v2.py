#!/usr/bin/env python3
"""Manifest-first retention summary; historical summarizer is preserved for provenance."""

import argparse
import datetime
import json
from pathlib import Path

if __package__:
    from .nrf_analysis_v2 import retention
else:
    from nrf_analysis_v2 import retention


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json', type=Path)
    args = parser.parse_args()
    try:
        result = retention(args.analysis_json)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = args.analysis_json.parent / f'retention-summary-v2-{stamp}.json'
    out.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(out)


if __name__ == '__main__':
    main()
