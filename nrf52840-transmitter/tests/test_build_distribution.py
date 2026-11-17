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


def test_conversion_from_installed_module_and_script_matches_wire_bytes(tmp_path):
    """Exercise both public entrypoints without hardware or an ARM compiler."""
    import struct
    import subprocess

    from nrf_tx.make_uf2 import encode_blocks

    payload = bytearray(257)
    struct.pack_into('<II', payload, 0, 0x20040000, 0x23009)
    marker = b'UF2_ENTRY_0x57_v1'
    payload[32 : 32 + len(marker)] = marker
    payload[-1] = 0x5A
    expected = b''.join(
        struct.pack('<8I', 0x0A324655, 0x9E5D5157, 0x2000, 0x23000 + i * 256, 256, i, 2, 0xADA52840)
        + chunk
        + bytes(220)
        + struct.pack('<I', 0x0AB16F30)
        for i, chunk in enumerate((bytes(payload[:256]), b'\x5a' + b'\xff' * 255))
    )
    assert encode_blocks(bytes(payload)) == expected
    assert encode_blocks(b'') == b''
    assert len(encode_blocks(bytes(payload[:256]))) == 512
    for name, entry in [
        ('source', [str(HOST / 'make_uf2.py')]),
        ('installed', ['-m', 'nrf_tx.make_uf2']),
    ]:
        binary = tmp_path / f'{name}.bin'
        binary.write_bytes(payload)
        subprocess.run([sys.executable, *entry, str(binary)], cwd=tmp_path, check=True)
        assert binary.with_suffix('.uf2').read_bytes() == expected
