"""Release command construction and export checks require only a synthetic build directory."""

import importlib.util
import json
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location('esp_build_test', TOOLS / 'build_firmware.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_command_uses_profile_paths_and_disables_every_release_probe(builder, tmp_path):
    profile = {'target': 'esp32', 'preview': False}
    args = builder.build_command(profile, tmp_path / 'sdk', tmp_path / 'build')
    assert args[-1] == 'build' and '--preview' not in args
    assert '-DESP_SDR_STREAMING=OFF' in args
    assert f'-DSDKCONFIG_DEFAULTS={builder.ROOT}/sdkconfig.defaults.esp32' in args
    assert [a for a in args if a.endswith('_PROBE=OFF')] == [
        f'-D{name}=OFF'
        for name in (
            'RING_PROBE',
            'SAMPLE_RATE_PROBE',
            'FILTER_REGISTER_PROBE',
            'S3_RF_PROBE',
            'C5_TUNE_PROBE',
            'S2_RF_PROBE',
        )
    ]
    args = builder.build_command(
        profile | {'preview': True, 'streaming': True, 'sdkconfig': 'custom'},
        tmp_path / 'sdk',
        tmp_path / 'build',
    )
    assert '--preview' in args and '-DESP_SDR_STREAMING=ON' in args
    assert f'-DSDKCONFIG_DEFAULTS={builder.ROOT}/custom' in args
    assert not any(a.endswith('_PROBE=OFF') for a in args)


def test_export_validation_precedes_publication(builder, tmp_path):
    build, output = tmp_path / 'build', tmp_path / 'artifacts'
    (build / 'config').mkdir(parents=True)
    cache = build / 'CMakeCache.txt'
    for probe in builder.DIAGNOSTIC_PROBES:
        cache.write_text(f'{probe}:BOOL=ON\n')
        with pytest.raises(ValueError, match='diagnostic probe'):
            builder.export(build, output, 'esp32', 'Example', 'sample')
        assert not output.exists()
    cache.write_text('RING_PROBE:BOOL=off\nOTHER_PROBE:BOOL=ON\n')
    (build / 'config/sdkconfig.json').write_text(json.dumps({'IDF_TARGET': 'esp32'}))
    settings = {'flash_size': '2MB', 'flash_mode': 'dio', 'flash_freq': '40m'}
    (build / 'a.bin').write_bytes(b'alpha')
    (build / 'b.bin').write_bytes(b'beta')
    args = {'extra_esptool_args': {'chip': 'esp32'}, 'flash_settings': settings}
    for pairs, error in [
        ({}, 'No firmware images'),
        ({'0x0': 'a.bin', '0x4': 'b.bin'}, 'overlapping'),
        ({'0x200000': 'a.bin'}, 'out-of-flash'),
    ]:
        (build / 'flasher_args.json').write_text(json.dumps(args | {'flash_files': pairs}))
        with pytest.raises(ValueError, match=error):
            builder.export(build, output, 'esp32', 'Example', 'sample')
        assert not output.exists()
    pairs = {'0x10': 'b.bin', '0x0': 'a.bin'}
    (build / 'flasher_args.json').write_text(json.dumps(args | {'flash_files': pairs}))
    manifest_path = builder.export(build, output, 'esp32', 'Example', 'sample')
    variant = json.loads(manifest_path.read_text())['variants']['esp32']
    assert [p['offset'] for p in variant['parts']] == [0, 16]
    assert (output / 'esp32/0-a.bin').read_bytes() == b'alpha'
    assert (output / 'esp32/1-b.bin').read_bytes() == b'beta'
    with pytest.raises(FileExistsError):
        builder.export(build, output, 'esp32', 'Example', 'sample')
