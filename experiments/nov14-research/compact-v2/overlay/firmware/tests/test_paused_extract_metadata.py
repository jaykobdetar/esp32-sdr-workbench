import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_optin_metadata_and_default_are_distinct():
    spec = importlib.util.spec_from_file_location('px_version', ROOT / 'tools/generate_version.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ordinary = m.metadata(ROOT, 'esp32')
    research = m.metadata(ROOT, 'esp32', True)
    assert ordinary['firmware_variant'] == 'esp32-core1-banks-experimental-v9'
    assert 'paused_packet_extract_protocol' not in ordinary
    assert research['firmware_variant'] == 'esp32-paused-extract-compact-research-v2'
    assert research['paused_packet_extract_protocol'] == 1
    try:
        m.metadata(ROOT, 'esp32s3', True)
    except ValueError:
        pass
    else:
        raise AssertionError('nonESP32 admitted')


def test_defaultoff_dispatch_and_original_caps_preserved():
    cmake = (ROOT / 'main/CMakeLists.txt').read_text()
    assert (
        'option(PAUSED_PACKET_EXTRACT "Build opt-in single paused RFTX extraction research (never package)" OFF)'
        in cmake
    )
    receiver = (ROOT / 'main/targets/esp32/receiver.c').read_text()
    assert (
        '#ifdef PAUSED_PACKET_EXTRACT\n    if (paused_extract_command(line)) return;\n#endif'
        in receiver
    )
    # No normal CAPS additions: separate explicit PEX? discovery only.
    assert 'PEX' not in (ROOT / 'main/targets/esp32/receiver_caps.h').read_text()
