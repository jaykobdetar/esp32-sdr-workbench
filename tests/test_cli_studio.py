"""Installed CLI routing without starting Qt or opening hardware."""

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from sdr_research.cli import main


def test_studio_routes_arguments_and_return_value(monkeypatch):
    studio = Mock(return_value=7)
    monkeypatch.setitem(sys.modules, 'sdr_research.studio_gui', SimpleNamespace(main=studio))
    assert main(['studio', '--demo']) == 7
    studio.assert_called_once_with(['--demo'])


def test_studio_help_exits_without_starting_window():
    result = subprocess.run(
        [sys.executable, '-m', 'sdr_research.cli', 'studio', '--help'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '--demo' in result.stdout
