import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_truthful_optional_variant():
    spec = importlib.util.spec_from_file_location(
        'version_generator', ROOT / 'tools/generate_version.py'
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        value = m.metadata(p, 'esp32')
        assert value['revision'] == 'unknown'
        assert 'firmware_variant' not in value
        (p / 'FIRMWARE_VARIANT').write_text('esp32-pipeline-optimized-v2\n')
        value = m.metadata(p, 'esp32')
        assert value['revision'] == 'unknown'
        assert value['firmware_variant'] == 'esp32-pipeline-optimized-v2'
        assert 'firmware_variant' not in m.metadata(p, 'esp32c3')
        (p / 'FIRMWARE_VARIANT').write_text('bad variant\n')
        try:
            m.metadata(p, 'esp32')
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid variant accepted')
