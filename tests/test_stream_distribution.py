"""Keep the explicit sdist allowlist complete without including private work files."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDED = {
    line.removeprefix('include ')
    for line in (ROOT / 'MANIFEST.in').read_text().splitlines()
    if line.startswith('include ')
}


def assert_included(path):
    relative = path.relative_to(ROOT).as_posix()
    assert relative in INCLUDED, f'Add an explicit MANIFEST.in include for {relative}'
    assert path.is_file(), f'Distribution resource does not exist: {relative}'


def test_original_esp32_local_quoted_includes_are_distributed():
    target = ROOT / 'firmware/main/targets/esp32'
    include_dirs = [target, ROOT / 'firmware/main/common', ROOT / 'firmware/main/diagnostics']
    for source in sorted(target.iterdir()):
        if source.suffix not in ('.c', '.h', '.inc'):
            continue
        for name in re.findall(r'^\s*#\s*include\s+"([^"]+)"', source.read_text(), re.MULTILINE):
            # SDK and generated headers are not source-distribution resources.
            local = next(
                (folder / name for folder in include_dirs if (folder / name).is_file()), None
            )
            if local is not None:
                assert_included(local)


def test_published_stream_manifest_and_all_named_fixtures_are_distributed():
    evidence = ROOT / 'docs/evidence/dual-stream-evaluation'
    for name in ('README.md', 'manifest.json'):
        assert_included(evidence / name)
    manifest = json.loads((evidence / 'manifest.json').read_text())
    for item in manifest['timing_files'] + manifest['derived_files']:
        assert Path(item['file']).name == item['file']
        assert_included(evidence / item['file'])


def test_stream_build_tests_launchers_and_guides_are_distributed():
    for name in (
        'firmware/tests/test_dual_timing_state.py',
        'firmware/tests/test_capture_scheduling.py',
        'firmware/tests/test_receiver_caps.py',
        'scripts/launch-lab.sh',
        'scripts/launch-studio.sh',
        'docs/continuous-dual-receivers.md',
        'docs/dual-receiver-results-2026-11-12.md',
        'docs/dual-receiver-timing.md',
        'docs/dual-sparse-campaign.md',
        'docs/rf-studio.md',
        'docs/rf-studio-hardware.png',
        'docs/shared-rf-console.md',
        'docs/sparse-iq-stream.md',
        'docs/pr4-review-follow-up.md',
        'tests/test_stream_distribution.py',
    ):
        assert_included(ROOT / name)
