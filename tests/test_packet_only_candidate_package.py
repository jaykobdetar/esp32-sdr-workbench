"""Sanitized research-package pin checks; no compilation or hardware."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / 'experiments/packet-only-v1finish'


def test_packet_candidate_patch_and_fixture_pins():
    pins = json.loads((HERE / 'manifest.json').read_text())
    assert (
        hashlib.sha256((HERE / 'candidate.patch').read_bytes()).hexdigest() == pins['patch_sha256']
    )
    for name, digest in pins['tests_sha256'].items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == digest
    assert pins['variant'] == 'esp32-packet-only-bounded-v1finish'
    assert pins['app_bytes'] == 720160
    assert 'GPL-3.0-or-later' in pins['decoder_provenance']['license']


def test_candidate_contains_no_private_paths_or_binary_images():
    for path in HERE.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        assert path.suffix not in ('.bin', '.elf', '.sigmf-data')
        contents = path.read_text()
        assert '/home/' not in contents and '/dev/ttyUSB' not in contents
