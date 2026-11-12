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
        condition=dict(
            index=0,
            pair=0,
            kind='matched',
            tx_on=True,
            rx_frequency_mhz=2440,
            transport_crc_valid=True,
            status='running',
        ),
        source_configuration=dict(mode_mbps=2, payload_len=64),
    )
    path = iq_fixture(tmp_path, dict(raw_source_control=raw))
    report = dict(
        status='passed',
        source_configuration=raw['source_configuration'],
        runs=[dict(raw['condition'], status='passed', sigmf=str(path))],
    )
    (tmp_path / 'results.json').write_text(json.dumps(report))
    assert len(analyzer.analyze(tmp_path, 500000)['records']) == 1
    raw['source_configuration']['payload_hex'] = 'deadbeef'
    (tmp_path / 'results.json').write_text(json.dumps(report))
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


def raw_campaign(tmp_path, fail_stop=False):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        'raw_completion_fakes', Path(__file__).with_name('test_nrf_raw_controls.py')
    )
    fakes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fakes)

    class TX(fakes.TX):
        def start(self, **kwargs):
            super().start(**kwargs)
            return self.status()

        def stop(self):
            if fail_stop and self.stops == 2:
                self.stops += 1
                raise RuntimeError('Injected post-capture stop failure')
            return super().stop()

    args = fakes.args(tmp_path)
    if fail_stop:
        with pytest.raises(RuntimeError, match='post-capture stop failure'):
            fakes.m.execute(args, fakes.RX(), TX(), sleep=lambda _: None)
    else:
        fakes.m.execute(args, fakes.RX(), TX(), sleep=lambda _: None)
    return args.output_directory


@pytest.mark.parametrize('fail_stop', [False, True])
def test_actual_raw_campaign_completion(tmp_path, fail_stop):
    directory = raw_campaign(tmp_path, fail_stop)
    paths = sorted(directory.glob('*.sigmf-data'))
    assert paths
    if fail_stop:
        with pytest.raises(ValueError, match='incomplete raw run/report'):
            analyzer.analyze(directory, 500000)
    else:
        # Validate every actual saved input without repeating expensive DSP here.
        for path in paths:
            run, _, _, _ = analyzer.source(path, analyzer.read(path.with_suffix('.sigmf-meta')))
            assert run['status'] == 'passed' and run['mode'] == 'raw'


@pytest.mark.parametrize(
    'mutation',
    [
        'missing',
        'failed',
        'duplicate',
        'key',
        'condition',
        'source',
        'device',
        'artifact',
        'frequency',
        'legacy',
    ],
)
def test_raw_completion_provenance_mismatch(tmp_path, mutation):
    directory = raw_campaign(tmp_path)
    path = sorted(directory.glob('*.sigmf-data'))[0]
    meta = analyzer.read(path.with_suffix('.sigmf-meta'))
    reportpath = directory / 'results.json'
    report = analyzer.read(reportpath)
    row = next(row for row in report['runs'] if analyzer.data_name(row['sigmf']) == path.name)
    if mutation == 'missing':
        reportpath.unlink()
    elif mutation == 'failed':
        row['status'] = 'failed'
    elif mutation == 'duplicate':
        report['runs'].append(dict(row))
    elif mutation == 'key':
        row['index'] = 99
    elif mutation == 'condition':
        row['tx_on'] = not row['tx_on']
    elif mutation == 'source':
        report['source_configuration']['payload_len'] = 32
    elif mutation == 'device':
        report['device'] = {}
    elif mutation == 'artifact':
        report['local_reference_artifact_sha256'] = '0' * 64
    elif mutation == 'frequency':
        meta['captures'][0]['core:frequency'] += 1
    elif mutation == 'legacy':
        (directory / f'{int(analyzer.run_key(path.name)):04d}-run.json').write_text(json.dumps(row))
    if mutation != 'missing':
        reportpath.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        analyzer.source(path, meta)
