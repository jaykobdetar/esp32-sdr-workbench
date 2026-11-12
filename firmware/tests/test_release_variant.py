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


def test_current_variant_distinguishes_tie_fix_and_calibration_observer():
    from sdr_research.calibration import CURRENT_VARIANT

    assert (ROOT / 'FIRMWARE_VARIANT').read_text().strip() == CURRENT_VARIANT
    assert CURRENT_VARIANT == 'esp32-pipeline-adaptive-q16-v7'


def test_calibration_variants_remain_required_for_v4_through_v7():
    from sdr_research.calibration import ADAPTIVE_VARIANTS, CALIBRATION_VARIANTS

    assert CALIBRATION_VARIANTS == (
        'esp32-pipeline-adaptive-q16-v4',
        'esp32-pipeline-adaptive-q16-v5',
        'esp32-pipeline-adaptive-q16-v6',
        'esp32-pipeline-adaptive-q16-v7',
    )
    assert set(CALIBRATION_VARIANTS) < set(ADAPTIVE_VARIANTS)
