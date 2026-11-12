"""Public summary arithmetic is reproducible without serial devices or raw RF."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_adaptive_evidence import DEFAULT, verify

EVIDENCE = DEFAULT.parent


@pytest.fixture(scope='module')
def evidence():
    return json.loads(DEFAULT.read_text())


def test_adaptive_evidence_accounting(evidence):
    result = verify(evidence)
    assert result['totals']['pipeline_runs'] == 925
    assert result['totals']['pipeline_captures'] == 1568533
    assert result['transport_crc_valid_files'] == 1818
    assert result['reported_minimum_heap_bytes'] == 30448
    assert result['reported_minimum_stack_bytes'] == 2748
    assert result['soak_pipeline_seconds'] == 1800.598720
    endpoints = result['strong_source_endpoints']
    assert len(endpoints) == 18
    assert endpoints['v2-strong-matched/hardware-agc/on'] == [1, 8]
    assert sum(value[0] for value in endpoints.values()) == 1


def test_adaptive_evidence_rejects_changed_capture_count(evidence):
    corrupted = copy.deepcopy(evidence)
    corrupted['stages']['health-fixed-soak']['records'][0]['summary']['captures'] += 1
    with pytest.raises(ValueError):
        verify(corrupted)


def test_adaptive_evidence_publication_manifest():
    manifest = json.loads((EVIDENCE / 'publication-manifest.json').read_text())
    root = Path(__file__).resolve().parents[1]
    for item in manifest['evidence_files']:
        assert hashlib.sha256((root / item['path']).read_bytes()).hexdigest() == item['sha256']
    text = DEFAULT.read_text()
    for forbidden in (
        'observed_payload_hex',
        'address_hex',
        '/home/',
        '/Users/',
        '/dev/serial/by-id/',
    ):
        assert forbidden not in text
