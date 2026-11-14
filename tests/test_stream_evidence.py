import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    'scripts.verify_stream_evidence',
    Path(__file__).resolve().parents[1] / 'scripts/verify_stream_evidence.py',
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def test_verifier_rejects_schema_and_path_escape(tmp_path):
    path = tmp_path / 'example.json.gz'
    path.write_bytes(gzip.compress(b'{"schema":"other"}'))
    with pytest.raises(ValueError, match='schema'):
        _module.verify_file(path)
    (tmp_path / 'manifest.json').write_text(
        json.dumps({'timing_files': [{'file': '../x.json.gz', 'sha256': ''}]})
    )
    with pytest.raises(ValueError, match='basename'):
        _module.verify_directory(tmp_path)


def test_verifier_rejects_checksum_empty_and_oversize(tmp_path, monkeypatch):
    path = tmp_path / 'example.json.gz'
    path.write_bytes(
        gzip.compress(b'{"schema":"dual-stream-evidence-v1","source":{},"runs":[],"anchors":[]}')
    )
    manifest = {'timing_files': [{'file': path.name, 'sha256': 'wrong'}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Checksum'):
        _module.verify_directory(tmp_path)
    manifest['timing_files'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='no trials'):
        _module.verify_directory(tmp_path)
    monkeypatch.setattr(_module, 'MAX_DECOMPRESSED', 10)
    with pytest.raises(ValueError, match='size limit'):
        _module.verify_file(path)
