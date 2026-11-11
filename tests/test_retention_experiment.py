"""Apply the unadopted experiment in a temporary source copy, never on hardware."""

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
    shutil.copytree(ROOT / 'firmware', tmp_path / 'firmware')
    subprocess.run(
        ['git', 'apply', str(ROOT / 'experiments/retention/retention-experiment.patch')],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [sys.executable, 'firmware/tests/test_pipeline_retention.py'], cwd=tmp_path, check=True
    )
