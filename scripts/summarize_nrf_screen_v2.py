#!/usr/bin/env python3
"""Manifest-first screen summary; historical summarizer is preserved for provenance."""

import argparse
import datetime
import json
from pathlib import Path

if __package__:
    from .nrf_analysis_v2 import screen
else:
    from nrf_analysis_v2 import screen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        result = screen(args.directory)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = args.directory / f'summary-v2-{stamp}.json'
    out.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(out)


if __name__ == '__main__':
    main()
