#!/usr/bin/env python3
"""Validated offline analysis for campaign, raw-control and gain-comparison SigMF.

Uses the frozen historical DSP implementation; rejects unsupported payload patterns.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path

import numpy as np

if __package__:
    from . import analyze_nrf_iq as legacy
    from .nrf_analysis_v2 import number, read, run_key
else:
    import analyze_nrf_iq as legacy
    from nrf_analysis_v2 import number, read, run_key


def data_name(value):
    name = Path(value).name
    for suffix in ('.sigmf-meta', '.sigmf-data'):
        if name.endswith(suffix):
            return name[: -len(suffix)] + '.sigmf-data'
    return name + '.sigmf-data'


def source(path, meta):
    md = meta['global'].get('sdr_research:metadata', {})
    key = run_key(path.name)
    runpath = path.parent / f'{int(key):04d}-run.json'
    if runpath.exists():
        run = read(runpath)
        if run.get('status') != 'passed' or str(run['index']) != key:
            raise ValueError(f'Run not complete or key mismatch: {runpath}')
    elif 'raw_source_control' in md:
        raw = md['raw_source_control']
        run = dict(raw['condition'])
        run['mode'] = 'raw'
        run['frequency_mhz'] = run['rx_frequency_mhz']
        run['source_configuration'] = raw['source_configuration']
    elif 'gain_comparison' in md:
        report_path = path.parent / 'results.json'
        if not report_path.exists():
            raise ValueError(
                f'gain_comparison requires results.json with completed run and source configuration: {path}'
            )
        report = read(report_path)
        matches = [
            r
            for r in report['runs']
            if any(data_name(c['sigmf']) == path.name for c in r.get('crops', []))
            or (r.get('sigmf') and data_name(r['sigmf']) == path.name)
        ]
        if len(matches) != 1 or matches[0].get('status') != 'passed':
            raise ValueError(f'Missing, ambiguous or incomplete gain run for {path}')
        run = dict(matches[0])
        condition = md['gain_comparison']
        for field in ('mode', 'tx_on', 'pair', 'gain'):
            if field in condition and run.get(field) != condition[field]:
                raise ValueError(f'Gain metadata/run mismatch for {field}: {path}')
        run.setdefault('source_configuration', report.get('source_configuration', {}))
    elif 'controlled_source' in md:
        run = dict(md['controlled_source'])
        run.setdefault('mode', 'raw')
        run.setdefault('frequency_mhz', run.get('rx_frequency_mhz'))
    else:
        raise ValueError(f'Unsupported source metadata: {path}')
    if not isinstance(run.get('tx_on'), bool) or not isinstance(run.get('mode'), str):
        raise ValueError(f'Missing source condition: {path}')
    tx = (
        run.get('tx_start')
        or run.get('tx_stopped')
        or run.get('tx_before')
        or run.get('source_configuration')
    )
    if not tx:
        raise ValueError(f'Missing transmitter configuration: {path}')
    # Configuration fields may be reported in either source config or status.
    configs = [
        run.get(key, {})
        for key in (
            'tx_start',
            'tx_stopped',
            'tx_before',
            'tx_after',
            'source_configuration',
            'settings',
        )
    ]
    for config in configs:
        pattern = config.get('payload_hex')
        if pattern not in (None, '', 'off') or config.get('payload_pattern_len', 0):
            raise ValueError(
                f'Unsupported custom payload_hex={pattern!r} in {path}; refusing default-pattern scoring'
            )
    mbps, length = tx.get('mode_mbps'), tx.get('payload_len')
    if mbps not in (1, 2) or isinstance(mbps, bool):
        raise ValueError(f'Unsupported mode_mbps: {mbps!r}')
    if not isinstance(length, int) or isinstance(length, bool) or not 8 <= length <= 255:
        raise ValueError(f'Unsupported payload_len: {length!r}')
    frequency = run.get('frequency_mhz') or run.get('rx_frequency_mhz')
    if frequency is None:
        frequency = meta['captures'][0]['core:frequency'] / 1e6
    number(frequency, 'frequency_mhz', positive=True)
    return run, tx, frequency, md


def analyze(directory, cfo_step):
    paths = sorted(Path(directory).glob('*.sigmf-data'))
    if not paths:
        raise ValueError('No SigMF data inputs found')
    rows = []
    for path in paths:
        metapath = path.with_suffix('.sigmf-meta')
        if not metapath.exists():
            raise ValueError(f'Missing metadata: {metapath}')
        meta = read(metapath)
        if meta['global']['core:datatype'] != 'cf32_le':
            raise ValueError(f'Unsupported datatype: {path}')
        fs = number(meta['global']['core:sample_rate'], 'sample rate', positive=True)
        run, tx, frequency, md = source(path, meta)
        if fs / (tx['mode_mbps'] * 1e6) < 1:
            raise ValueError('Sample rate below symbol rate')
        if path.stat().st_size % 8:
            raise ValueError(f'Truncated complex float32 data: {path}')
        x = np.fromfile(path, dtype='<c8')
        if len(x) < 128 or not np.isfinite(x).all():
            raise ValueError(f'Need at least 128 finite IQ samples: {path}')
        rows.append(
            dict(
                file=path.name,
                run_key=run_key(path.name),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                tx_on=run['tx_on'],
                mode=run['mode'],
                frequency_mhz=frequency,
                gain=md.get('settings', {}).get('gain', run.get('gain')),
                receiver_summary=run.get('summary', {}),
                metrics=legacy.metrics(x, fs),
                decoder=legacy.decode(x, fs, tx['mode_mbps'], tx['payload_len'], cfo_step),
            )
        )
    return dict(
        schema_version=2,
        cfo_step_hz=cfo_step,
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        dsp_sha256=hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest(),
        records=rows,
        cautions=[
            'Default RFTX sequence payload only; custom payload patterns are rejected.',
            'component_clip_fraction retains the historical abs(component)>=.999 definition.',
            'Transport CRC is not on-air packet CRC. Retained-frame yield is not packet recall.',
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cfo-step-hz', type=int, default=125000)
    args = parser.parse_args()
    if args.cfo_step_hz <= 0:
        parser.error('--cfo-step-hz must be positive')
    try:
        result = analyze(args.directory, args.cfo_step_hz)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    result['synthetic_tests'] = legacy.selftest()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = args.output or args.directory / f'analysis-v2-{stamp}'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'analysis.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    legacy.svg(result['records'], out / 'diagnostics.svg')
    print(out)


if __name__ == '__main__':
    main()
