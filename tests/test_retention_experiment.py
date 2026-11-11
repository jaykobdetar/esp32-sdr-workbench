"""Apply the unadopted experiment in a temporary source copy, never on hardware."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(
    not shutil.which('cc') or not shutil.which('git'), reason='Host C compiler and git required'
)
def test_retention_patch_and_mocked_pipeline(tmp_path):
    fixture = ROOT / 'tests/fixtures/retention-base'
    manifest = json.loads((fixture / 'manifest.json').read_text())
    assert manifest['base_commit'] == '3e382d94ce914e1b89fcc04c688f7d8a2a7f6b89'
    for name, expected in manifest['files'].items():
        assert hashlib.sha256((fixture / name).read_bytes()).hexdigest() == expected
    shutil.copytree(fixture / 'firmware', tmp_path / 'firmware')
    subprocess.run(
        ['git', 'apply', str(ROOT / 'experiments/retention/retention-experiment.patch')],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [sys.executable, 'firmware/tests/test_pipeline_retention.py'], cwd=tmp_path, check=True
    )
