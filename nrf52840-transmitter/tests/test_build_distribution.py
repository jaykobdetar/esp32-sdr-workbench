"""Installed host tooling must not try to build inside site-packages."""

import importlib.util
import sys
from pathlib import Path

import pytest

HOST = Path(__file__).parents[1] / 'host'
sys.path.insert(0, str(HOST))
spec = importlib.util.spec_from_file_location(
    'build_firmware_distribution', HOST / 'build_firmware.py'
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_installed_build_has_actionable_error_without_writes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['build_firmware', '--version', '1.2.3'])
    with pytest.raises(SystemExit) as error:
        builder.main()
    assert error.value.code == 2
    assert 'requires the project Git checkout' in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_installed_dry_run_stays_available(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['build_firmware', '--version', '1.2.3', '--dry-run'])
    builder.main()
    assert '"mode": "plan"' in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_source_checkout_accepts_git_worktree_file(tmp_path, monkeypatch):
    root = tmp_path / 'nrf52840-transmitter'
    (root / 'firmware').mkdir(parents=True)
    (root / 'host').mkdir()
    (tmp_path / '.git').write_text('gitdir: /some/worktree\n')
    for name in ('dependencies.json', 'firmware/Makefile', 'host/make_uf2.py'):
        (root / name).touch()
    monkeypatch.setattr(builder, 'ROOT', root)
    builder.require_source_checkout(builder.argparse.ArgumentParser())
