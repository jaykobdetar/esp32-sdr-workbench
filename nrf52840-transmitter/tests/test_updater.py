import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'host'))
from flash_uf2 import APP_START, validate_image


def uf2(path, addr=APP_START, flags=0x2000, family=0xADA52840, marker=True, reset=None):
    payload = bytearray(256)
    struct.pack_into('<II', payload, 0, 0x20040000, reset or (APP_START + 9))
    if marker:
        payload[32 : 32 + len(b'UF2_ENTRY_0x57_v1')] = b'UF2_ENTRY_0x57_v1'
    b = (
        struct.pack('<8I', 0x0A324655, 0x9E5D5157, flags, addr, 256, 0, 1, family)
        + payload
        + bytes(220)
        + struct.pack('<I', 0x0AB16F30)
    )
    path.write_bytes(b)
    return path


def test_safe_image(tmp_path):
    r = validate_image(uf2(tmp_path / 'a.uf2'))
    assert r['flash_start'] == 0x23000 and r['flash_end'] == 0x23100


@pytest.mark.parametrize(
    'addr', [0, 0x1000, 0x22000, 0x40000, 0xEA000, 0xF4000, 0xFD800, 0xFE000, 0xFF000, 0x10001000]
)
def test_reject_protected_addresses(tmp_path, addr):
    with pytest.raises(ValueError):
        validate_image(uf2(tmp_path / 'a.uf2', addr=addr))


@pytest.mark.parametrize(
    'kwargs',
    [
        {'flags': 0},
        {'flags': 0x2001},
        {'family': 0xD663823C},
        {'marker': False},
        {'reset': 0xF4001},
    ],
)
def test_reject_special_images(tmp_path, kwargs):
    with pytest.raises(ValueError):
        validate_image(uf2(tmp_path / 'a.uf2', **kwargs))


def test_reject_truncated(tmp_path):
    p = uf2(tmp_path / 'a.uf2')
    p.write_bytes(p.read_bytes()[:-1])
    with pytest.raises(ValueError):
        validate_image(p)


def test_reject_duplicate(tmp_path):
    p = uf2(tmp_path / 'a.uf2')
    p.write_bytes(p.read_bytes() * 2)
    with pytest.raises(ValueError):
        validate_image(p)


def mocked_update(tmp_path, monkeypatch, mutate=None):
    import flash_uf2 as module

    image = uf2(tmp_path / 'input.uf2')
    mount = tmp_path / 'mount'
    mount.mkdir()
    (mount / 'INFO_UF2.TXT').write_text('synthetic, no hardware')
    (mount / 'INDEX.HTM').write_text('synthetic, no hardware')
    current = bytearray(512)
    struct.pack_into('<8I', current, 0, 0, 0, 0, 0x3000, 256, 0, 1, 0)
    struct.pack_into('<II', current, 36, 0x51B1E5DB, APP_START)
    (mount / 'CURRENT.UF2').write_bytes(current)
    contacts = []

    def verified_mount(serial):
        contacts.append('mount')
        if mutate:
            mutate(image)
        return mount

    class TX:
        def __init__(self, *args, **kwargs):
            contacts.append('transmitter')

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def hello(self):
            return dict(version='0.2.2', healthy=True)

        def status(self):
            return dict(running=False)

    monkeypatch.setattr(module, 'verified_mount', verified_mount)
    monkeypatch.setattr(module, 'discover', lambda serial: 'fake-port')
    monkeypatch.setattr(module, 'Transmitter', TX)
    return module, image, mount, contacts


def test_update_transfers_the_validated_snapshot_not_replaced_path(tmp_path, monkeypatch):
    import hashlib

    module, image, mount, _ = mocked_update(
        tmp_path, monkeypatch, mutate=lambda path: path.write_bytes(b'unvalidated replacement')
    )
    original = image.read_bytes()
    report = module.update(
        image,
        '0.2.2',
        initial=True,
        serial_number='0123456789ABCDEF',
        state_directory=tmp_path / 'state',
    )
    assert image.read_bytes() != original
    assert (mount / 'RFTEST.UF2').read_bytes() == original
    assert report['validation']['sha256'] == hashlib.sha256(original).hexdigest()
    assert report['result'] == 'version_health_verified'
    assert report['requested_image_verified'] is False
    assert report['write_outcome'] == 'completed'


def test_uncertain_write_is_not_verified_by_old_same_version_app(tmp_path, monkeypatch):
    import os

    module, image, mount, _ = mocked_update(tmp_path, monkeypatch)
    real_fsync = os.fsync

    def fail_transfer_fsync(fd):
        if Path(f'/proc/self/fd/{fd}').resolve() == mount / 'RFTEST.UF2':
            raise OSError('simulated bootloader disconnect')
        real_fsync(fd)

    monkeypatch.setattr(module.os, 'fsync', fail_transfer_fsync)
    report = module.update(
        image,
        '0.2.2',
        initial=True,
        serial_number='0123456789ABCDEF',
        state_directory=tmp_path / 'state',
    )
    assert report['result'] == 'write_uncertain_version_health_observed'
    assert report['write_outcome'] == 'uncertain' and report['requested_image_verified'] is False
    assert [r['event'] for r in report['events']].count('write_begin') == 1
    assert not any(r['event'] == 'verified' for r in report['events'])


def test_updater_state_is_private_and_independent_of_installed_package(tmp_path, monkeypatch):
    import os
    import stat

    module, image, _, _ = mocked_update(tmp_path, monkeypatch)
    monkeypatch.setattr(module, '__file__', '/read-only-site-packages/nrf_tx/flash_uf2.py')
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'user-state'))
    old_umask = os.umask(0o002)
    try:
        report = module.update(image, '0.2.2', initial=True, serial_number='0123456789ABCDEF')
    finally:
        os.umask(old_umask)
    backup, log = Path(report['recovery_directory']), Path(report['log'])
    assert backup.is_relative_to(tmp_path / 'user-state')
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700
    for path in [log, *backup.iterdir()]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (tmp_path / 'recovery').exists()


@pytest.mark.parametrize('unsafe', ['existing-log', 'symlink-log', 'public-state', 'symlink-state'])
def test_unsafe_destinations_fail_before_contacting_devices(tmp_path, monkeypatch, unsafe):
    module, image, _, contacts = mocked_update(tmp_path, monkeypatch)
    state, log = tmp_path / 'state', tmp_path / 'update.json'
    protected = tmp_path / 'existing.txt'
    protected.write_text('keep unchanged')
    if unsafe == 'existing-log':
        log.write_text('keep unchanged')
    elif unsafe == 'symlink-log':
        log.symlink_to(protected)
    elif unsafe == 'public-state':
        state.mkdir(mode=0o755)
        state.chmod(0o755)
    else:
        target = tmp_path / 'real-state'
        target.mkdir(mode=0o700)
        state.symlink_to(target)
    with pytest.raises((FileExistsError, PermissionError)):
        module.update(
            image,
            '0.2.2',
            initial=True,
            serial_number='0123456789ABCDEF',
            state_directory=state,
            output=log,
        )
    assert contacts == [] and protected.read_text() == 'keep unchanged'
    if unsafe == 'existing-log':
        assert log.read_text() == 'keep unchanged'


def test_cli_returns_nonzero_for_unresolved_write(tmp_path, monkeypatch, capsys):
    import flash_uf2 as module

    monkeypatch.setattr(
        module, 'update', lambda *args: dict(result='write_uncertain_version_health_observed')
    )
    monkeypatch.setattr(sys, 'argv', ['flash_uf2', 'unused.uf2', '--expected-version', '0.2.2'])
    assert module.main() == 2
    assert 'write_uncertain' in capsys.readouterr().out


def test_failed_open_cannot_be_verified_by_existing_same_version_app(tmp_path, monkeypatch):
    module, image, mount, _ = mocked_update(tmp_path, monkeypatch)
    original_open = Path.open

    def blocked_open(path, *args, **kwargs):
        if path == mount / 'RFTEST.UF2':
            raise OSError('simulated write failure before first byte')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', blocked_open)
    report = module.update(
        image,
        '0.2.2',
        initial=True,
        serial_number='0123456789ABCDEF',
        state_directory=tmp_path / 'state',
    )
    assert report['result'] == 'write_uncertain_version_health_observed'
    assert report['requested_image_verified'] is False
    assert not (mount / 'RFTEST.UF2').exists()


def test_validator_rejects_mutable_snapshot(tmp_path):
    import flash_uf2 as module

    with pytest.raises(TypeError, match='immutable bytes'):
        module.validate_image_bytes(bytearray(uf2(tmp_path / 'input.uf2').read_bytes()))
