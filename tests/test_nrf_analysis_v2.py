"""Offline denominator and schema regressions, with no radio access."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
# Script entry points deliberately work without installing the package.
sys.path.insert(0, str(SCRIPTS))
try:
    import analyze_nrf_iq_v2 as analyzer
    import nrf_analysis_v2 as summary
finally:
    sys.path.pop(0)


def fixture_run(root, index, mode, on, count, pair=0, retained=None):
    if retained is None:
        retained = bool(count)
    run = dict(
        index=index,
        pair=pair,
        mode=mode,
        tx_on=on,
        status='passed',
        summary=dict(
            status=0,
            errors=0,
            pack_failed=0,
            detections=count,
            retained_samples=128 if retained else 0,
            wall_elapsed_us=1000000,
        ),
    )
    (root / f'{index:04d}-run.json').write_text(json.dumps(run))
    return dict(
        file=f'{index:04d}-{mode}.sigmf-data',
        mode=mode,
        tx_on=on,
        decoder=dict(full_payload_matches=[], exact_sync_candidates=[]),
        metrics={},
    )


def test_screen_counts_no_event_runs_and_empty_off(tmp_path):
    variant = tmp_path / 'variant'
    variant.mkdir()
    records = []
    for index, on, count in [(0, True, 10), (1, True, 0), (2, False, 2), (3, False, 0)]:
        record = fixture_run(variant, index, 'optimized', on, count)
        if count:
            records.append(record)
    directory = variant / 'analysis-v2-test'
    directory.mkdir()
    path = directory / 'analysis.json'
    path.write_text(json.dumps(dict(records=records)))
    g = summary.screen(tmp_path)['variants'][0]['groups']['optimized']
    assert (g['on']['candidate_rate'], g['off']['candidate_rate'], g['candidate_excess']) == (
        5,
        1,
        4,
    )
    assert g['on']['n'] == g['off']['n'] == 2
    fixture_run(variant, 2, 'optimized', False, 0)
    path.write_text(json.dumps(dict(records=records[:1])))
    g = summary.screen(tmp_path)['variants'][0]['groups']['optimized']
    assert g['off']['candidate_rate'] == 0
    assert g['off']['no_retention_runs'] == 2


def test_retention_zero_pairs_missing_analysis_and_empty_pairs(tmp_path):
    analysis = tmp_path / 'analysis-v2-test'
    analysis.mkdir()
    path = analysis / 'analysis.json'
    path.write_text(json.dumps(dict(records=[])))
    fixture_run(tmp_path, 0, 'strongest', True, 0)
    fixture_run(tmp_path, 1, 'reservoir', True, 0)
    result = summary.retention(path)
    assert len(result['pairs']) == 1
    assert result['paired_crc_difference'] == 0
    assert result['paired_bootstrap_percentile_95'] == [0, 0]
    fixture_run(tmp_path, 1, 'reservoir', True, 10)
    result = summary.retention(path)
    assert result['paired_crc_difference'] is None
    assert result['groups'][1]['full_crc'] is None
    assert result['groups'][1]['candidate_rate'] == 10
    (tmp_path / '0001-run.json').unlink()
    assert summary.retention(path)['paired_bootstrap_percentile_95'] is None
    fixture_run(tmp_path, 0, 'strongest', False, 0)
    assert summary.retention(path)['paired_crc_difference'] is None


def test_failed_duplicate_and_orphan_inputs(tmp_path):
    record = fixture_run(tmp_path, 0, 'optimized', True, 10)
    with pytest.raises(ValueError, match='Duplicate'):
        summary.load_runs(tmp_path, dict(records=[record, record]))
    record['tx_on'] = False
    with pytest.raises(ValueError, match='condition mismatch'):
        summary.load_runs(tmp_path, dict(records=[record]))
    record['file'] = '0009-optimized.sigmf-data'
    with pytest.raises(ValueError, match='without manifests'):
        summary.load_runs(tmp_path, dict(records=[record]))
    runpath = tmp_path / '0000-run.json'
    run = json.loads(runpath.read_text())
    run['summary']['wall_elapsed_us'] = 0
    runpath.write_text(json.dumps(run))
    with pytest.raises(ValueError, match='wall_elapsed_us'):
        summary.load_runs(tmp_path, dict(records=[]))


def iq_fixture(root, metadata, filename='0000-raw-on'):
    path = root / (filename + '.sigmf-data')
    np.ones(256, dtype='<c8').tofile(path)
    meta = {
        'global': {
            'core:datatype': 'cf32_le',
            'core:sample_rate': 16000000,
            'sdr_research:metadata': metadata,
        },
        'captures': [{'core:frequency': 2440000000}],
    }
    path.with_suffix('.sigmf-meta').write_text(json.dumps(meta))
    return path


def test_current_raw_metadata_and_custom_payload_rejected(tmp_path):
    raw = dict(
        condition=dict(tx_on=True, rx_frequency_mhz=2440),
        source_configuration=dict(mode_mbps=2, payload_len=64),
    )
    iq_fixture(tmp_path, dict(raw_source_control=raw))
    assert len(analyzer.analyze(tmp_path, 500000)['records']) == 1
    raw['source_configuration']['payload_hex'] = 'deadbeef'
    iq_fixture(tmp_path, dict(raw_source_control=raw))
    with pytest.raises(ValueError, match='Unsupported custom payload'):
        analyzer.analyze(tmp_path, 500000)


def test_gain_requires_complete_results_and_joins_crop(tmp_path):
    condition = dict(mode='manual-60', gain=60, tx_on=True, pair=0)
    path = iq_fixture(tmp_path, dict(gain_comparison=condition), '0000-manual-60-on-crop-0')
    with pytest.raises(ValueError, match='requires results.json'):
        analyzer.analyze(tmp_path, 500000)
    report = dict(
        runs=[
            dict(
                **condition,
                index=0,
                status='passed',
                tx_before=dict(mode_mbps=2, payload_len=64),
                crops=[dict(sigmf=str(path.with_suffix('.sigmf-meta')))],
            )
        ]
    )
    (tmp_path / 'results.json').write_text(json.dumps(report))
    assert analyzer.analyze(tmp_path, 500000)['records'][0]['mode'] == 'manual-60'
    report['runs'][0]['status'] = 'failed'
    (tmp_path / 'results.json').write_text(json.dumps(report))
    with pytest.raises(ValueError, match='incomplete gain run'):
        analyzer.analyze(tmp_path, 500000)


def test_empty_unknown_and_missing_metadata_fail(tmp_path):
    with pytest.raises(ValueError, match='No SigMF'):
        analyzer.analyze(tmp_path, 500000)
    path = iq_fixture(tmp_path, {})
    with pytest.raises(ValueError, match='Unsupported source'):
        analyzer.analyze(tmp_path, 500000)
    path.with_suffix('.sigmf-meta').unlink()
    with pytest.raises(ValueError, match='Missing metadata'):
        analyzer.analyze(tmp_path, 500000)


def test_controlled_manifest_custom_pattern_and_invalid_iq(tmp_path):
    record = fixture_run(tmp_path, 0, 'optimized', True, 1)
    path = iq_fixture(tmp_path, {}, Path(record['file']).stem)
    runpath = tmp_path / '0000-run.json'
    run = json.loads(runpath.read_text())
    run['tx_start'] = dict(mode_mbps=2, payload_len=64)
    run['tx_before'] = dict(mode_mbps=2, payload_len=64, payload_pattern_len=4)
    runpath.write_text(json.dumps(run))
    with pytest.raises(ValueError, match='Unsupported custom payload'):
        analyzer.analyze(tmp_path, 500000)
    run['tx_before']['payload_pattern_len'] = 0
    runpath.write_text(json.dumps(run))
    assert analyzer.analyze(tmp_path, 500000)['records'][0]['run_key'] == '0'
    path.write_bytes(b'bad')
    with pytest.raises(ValueError, match='Truncated'):
        analyzer.analyze(tmp_path, 500000)


def test_analyzer_cli_failure_has_no_success_artifact(tmp_path):
    import subprocess

    output = tmp_path / 'analysis-v2-failed'
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / 'analyze_nrf_iq_v2.py'),
            str(tmp_path),
            '--output',
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert 'No SigMF' in result.stderr
    assert not output.exists()
