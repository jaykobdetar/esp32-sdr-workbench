"""Published source hashes must keep matching the files they describe."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = json.loads((ROOT / 'docs/rf-source-provenance.json').read_text())


def sha256(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def test_recorded_sources_are_unchanged():
    for source in PROVENANCE['sources']:
        assert sha256(source['path']) == source['public_sha256'], source['path']
        # A file marked identical must also still match the archived measurement source.
        if source['byte_identical']:
            assert source['public_sha256'] == source['archived_source_sha256'], source['path']
    patch = PROVENANCE['retention_patch']
    assert sha256(patch['path']) == patch['sha256']


def test_recorded_sources_are_excluded_from_the_formatter():
    """A reformat would silently invalidate the hashes, so ruff must skip these files."""
    # Plain text search keeps this test usable on Python 3.10, which has no tomllib.
    section = (ROOT / 'pyproject.toml').read_text().split('[tool.ruff]')[1].split('\n[')[0]
    for source in PROVENANCE['sources']:
        if source['path'].endswith('.py'):
            assert f'"{source["path"]}"' in section, source['path']
