"""Recompute every published stream trial and known packet proof in normal CI."""

import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_sparse_packet_evidence import verify
from scripts.verify_stream_evidence import verify_file

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence/dual-stream-evaluation'
MANIFEST = json.loads((EVIDENCE / 'manifest.json').read_text())
SUMMARY = json.loads((EVIDENCE / 'summary.json').read_text())


def assert_published_analysis(actual, expected, location='analysis'):
    """Only full gap lists are omitted from the public summary, not scalar metrics."""
    if isinstance(expected, dict):
        assert set(actual) - {'gaps_us'} == set(expected), location
        for key, value in expected.items():
            assert_published_analysis(actual[key], value, f'{location}.{key}')
    elif isinstance(expected, list):
        assert len(actual) == len(expected), location
        for index, (observed, published) in enumerate(zip(actual, expected, strict=True)):
            assert_published_analysis(observed, published, f'{location}[{index}]')
    elif isinstance(expected, float):
        # NumPy's least-squares backend can differ slightly across supported hosts.
        assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6), location
    else:
        assert actual == expected, location


def test_published_stream_manifest_and_trial_inventory():
    for item in MANIFEST['timing_files'] + MANIFEST['derived_files']:
        assert Path(item['file']).name == item['file']
        data = (EVIDENCE / item['file']).read_bytes()
        assert len(data) == item['bytes'], item['file']
        assert hashlib.sha256(data).hexdigest() == item['sha256'], item['file']
    campaigns = [row['campaign'] for row in SUMMARY['experiments']]
    assert len(set(campaigns)) == len(campaigns)
    assert {f'{name}.json.gz' for name in campaigns} == {
        item['file'] for item in MANIFEST['timing_files']
    }


@pytest.mark.parametrize('experiment', SUMMARY['experiments'], ids=lambda row: row['campaign'])
def test_published_stream_figures_recompute(experiment):
    actual = verify_file(EVIDENCE / f'{experiment["campaign"]}.json.gz')
    source = actual['source']
    assert source['variant'] == experiment['source']['variant']
    assert source['application_sha256'] == experiment['source']['application_sha256']
    assert [row['index'] for row in actual['trials']] == [
        row['index'] for row in experiment['runs']
    ]
    for observed, published in zip(actual['trials'], experiment['runs'], strict=True):
        assert_published_analysis(observed['analysis'], published['analysis'])


def test_published_sparse_packet_proof_recomputes():
    document = json.loads((EVIDENCE / 'packet-proof.json').read_text())
    result = verify(document)
    assert len(result['runs']) == len(document['runs']) == 12
    assert {row['run_id'] for row in result['runs']} == {row['run_id'] for row in document['runs']}


@pytest.mark.parametrize('name', ['verify_stream_evidence', 'verify_sparse_packet_evidence'])
@pytest.mark.parametrize('direct', [False, True], ids=['module', 'script'])
def test_stream_verifier_entry_points(name, direct, tmp_path):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    args = [str(ROOT / 'scripts' / f'{name}.py')] if direct else ['-m', f'scripts.{name}']
    result = subprocess.run(
        [sys.executable, *args, '--help'],
        cwd=tmp_path if direct else ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout


@pytest.mark.parametrize(
    'actual, expected',
    [
        ({'coverage_percent': 99.9}, {'coverage_percent': 99.99}),
        ({'sensitivity': [{'max_gap_us': 101.0}]}, {'sensitivity': [{'max_gap_us': 100.0}]}),
        ({'gap_count': 11}, {'gap_count': 10}),
        ({'coverage_percent': 99.9, 'extra_metric': 1}, {'coverage_percent': 99.9}),
        ({'coverage_percent': float('nan')}, {'coverage_percent': 99.9}),
    ],
)
def test_summary_comparison_rejects_metric_drift(actual, expected):
    with pytest.raises(AssertionError):
        assert_published_analysis(actual, expected)
