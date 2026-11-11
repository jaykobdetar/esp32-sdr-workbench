"""Check installed imports and CLI discovery without connecting to hardware."""

import importlib
import importlib.metadata
import subprocess
import sys
from pathlib import Path

from sdr_research._version import __version__


def test_single_version_source():
    assert importlib.metadata.version('esp32-sdr-research') == __version__


def test_transmitter_and_campaign_packages():
    for name in (
        'nrf_tx.rf_tx',
        'nrf_tx.flash_uf2',
        'nrf_campaigns.nrf_rf_campaign',
        'nrf_campaigns.nrf_receiver_compare',
        'nrf_campaigns.nrf_retention_campaign',
    ):
        assert importlib.import_module(name).__name__ == name


def test_campaign_help_outside_checkout(tmp_path):
    for name in (
        'nrf_rf_campaign',
        'nrf_receiver_compare',
        'nrf_retention_campaign',
        'nrf_parameter_screen',
        'nrf_raw_scope',
    ):
        result = subprocess.run(
            [sys.executable, '-m', 'nrf_campaigns.' + name, '--help'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert '--rx-port' in result.stdout


def test_campaigns_do_not_modify_module_search_path():
    root = Path(__file__).resolve().parents[1]
    for name in (
        'nrf_rf_campaign',
        'nrf_receiver_compare',
        'nrf_retention_campaign',
        'nrf_parameter_screen',
        'nrf_raw_scope',
    ):
        assert 'sys.path' not in (root / 'scripts' / (name + '.py')).read_text()
