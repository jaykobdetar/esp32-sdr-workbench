"""Manifest-first analysis helpers. Historical analysis sources remain immutable."""

import json
import math
import re
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(Path(path).read_text())


def run_key(filename):
    match = re.match(r'^(\d+)-', Path(filename).name)
    if not match:
        raise ValueError(f'No campaign run key in {filename}')
    return str(int(match[1]))


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f'Invalid {name}: {value!r}')
    if value < 0 or (positive and value == 0):
        raise ValueError(f'Invalid {name}: {value!r}')
    return value


def load_runs(directory, analysis):
    """Count every completed run; never impute a missing retained analysis as zero."""
    records = {}
    for record in analysis['records']:
        key = str(record.get('run_key', run_key(record['file'])))
        if key in records:
            raise ValueError(f'Duplicate analysis for run {key}; multi-crop input unsupported')
        records[key] = record
    rows, excluded, seen = [], [], set()
    manifests = sorted(Path(directory).glob('*-run.json'))
    if not manifests:
        raise ValueError(
            'No *-run.json manifests; retained-only analysis cannot establish denominators'
        )
    for path in manifests:
        run = read(path)
        key = str(int(run['index']))
        if key != run_key(path.name) or key in seen:
            raise ValueError(f'Inconsistent or duplicate run key: {path}')
        seen.add(key)
        if run.get('status') != 'passed':
            excluded.append(dict(run_key=key, reason='run not passed'))
            continue
        if not isinstance(run.get('tx_on'), bool) or not isinstance(run.get('mode'), str):
            raise ValueError(f'Missing run condition: {path}')
        s = run.get('summary', {})
        record = records.get(key)
        if record and (record['mode'] != run['mode'] or record['tx_on'] != run['tx_on']):
            raise ValueError(f'Analysis/run condition mismatch: {path}')
        if run['mode'] != 'raw':
            if s.get('status') != 0 or s.get('errors', 0) or s.get('pack_failed', 0):
                raise ValueError(f'Incomplete or failed receiver summary: {path}')
            rate = (
                number(s.get('detections'), 'detections')
                * 1e6
                / number(s.get('wall_elapsed_us'), 'wall_elapsed_us', positive=True)
            )
            retained = number(s.get('retained_samples'), 'retained_samples') > 0
        else:
            rate, retained = None, True
        if not retained and (record or run.get('sigmf') or run.get('retained_crc_valid')):
            raise ValueError(f'Inconsistent no-retention manifest: {path}')
        if retained and record is None:
            state, full, crc, header = 'missing_analysis', None, None, None
        elif retained:
            decoder = record['decoder']
            hits = decoder['full_payload_matches']
            state = 'analyzed'
            full = bool(hits)
            crc = any(h['crc_verified'] and h['address_verified'] for h in hits)
            header = bool(decoder['exact_sync_candidates'])
        else:
            state, full, crc, header = 'no_retention', False, False, False
        rows.append(
            dict(
                run_key=key,
                pair=run.get('pair'),
                mode=run['mode'],
                tx_on=run['tx_on'],
                analysis_status=state,
                full_payload=full,
                full_crc=crc,
                exact_header=header,
                candidate_rate=rate,
                local_duty=s.get('nominal_rf_duty_percent'),
                host_duty=s.get('nominal_host_rf_duty_percent', s.get('nominal_host_duty_percent')),
                retention_copy_us=s.get('retention_copy_us'),
                component_clip_fraction=record['metrics'].get('component_clip_fraction')
                if record
                else None,
            )
        )
    orphan = set(records) - seen
    if orphan:
        raise ValueError(f'Analysis records without manifests: {sorted(orphan)}')
    if not rows:
        raise ValueError('No passed runs')
    return rows, excluded


def mean(rows, key):
    values = [r[key] for r in rows if r[key] is not None]
    return float(np.mean(values)) if values else None


def wilson(k, n):
    if not n:
        return None
    z = 1.959963984540054
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def group(rows):
    known = [r for r in rows if r['full_crc'] is not None]
    complete = len(known) == len(rows)
    k = sum(r['full_crc'] for r in known)
    return dict(
        n=len(rows),
        analyzed_buffers=sum(r['analysis_status'] == 'analyzed' for r in rows),
        no_retention_runs=sum(r['analysis_status'] == 'no_retention' for r in rows),
        missing_analysis_runs=len(rows) - len(known),
        yield_complete=complete,
        full_crc=k if complete else None,
        full_crc_wilson_95=wilson(k, len(rows)) if complete else None,
        full_payload_buffers=sum(r['full_payload'] for r in known) if complete else None,
        address_crc_buffers=k if complete else None,
        exact_header_buffers=sum(r['exact_header'] for r in known) if complete else None,
        **{
            k: mean(rows, k)
            for k in (
                'candidate_rate',
                'local_duty',
                'host_duty',
                'retention_copy_us',
                'component_clip_fraction',
            )
        },
    )


def screen(directory):
    variants = []
    for variant in sorted(p for p in Path(directory).iterdir() if p.is_dir()):
        if not list(variant.glob('*-run.json')):
            continue
        analyses = sorted(variant.glob('analysis-*/analysis.json'))
        analysis = read(analyses[-1]) if analyses else {'records': []}
        rows, excluded = load_runs(variant, analysis)
        groups = {}
        for mode in sorted({r['mode'] for r in rows}):
            g = {
                label: group([r for r in rows if r['mode'] == mode and r['tx_on'] == on])
                for label, on in [('on', True), ('off', False)]
            }
            on, off = (g[label]['candidate_rate'] for label in ('on', 'off'))
            g['candidate_excess'] = on - off if on is not None and off is not None else None
            groups[mode] = g
        variants.append(
            dict(variant=variant.name, groups=groups, records=rows, excluded_runs=excluded)
        )
    if not variants:
        raise ValueError('No campaign variants with run manifests')
    return dict(schema_version=2, variants=variants, cautions=CAUTIONS)


def retention(analysis_path):
    analysis_path = Path(analysis_path)
    rows, excluded = load_runs(analysis_path.parent.parent, read(analysis_path))
    rows = [r for r in rows if r['mode'] in ('strongest', 'reservoir')]
    groups = [
        dict(mode=mode, tx_on=on, **group(rr))
        for mode in ('strongest', 'reservoir')
        for on in (True, False)
        if (rr := [r for r in rows if r['mode'] == mode and r['tx_on'] == on])
    ]
    pairs = []
    if any(r['pair'] is None for r in rows):
        raise ValueError('Retention run missing pair key')
    for pair in sorted({r['pair'] for r in rows}):
        on = [r for r in rows if r['pair'] == pair and r['tx_on']]
        if len({r['mode'] for r in on}) != len(on):
            raise ValueError(f'Duplicate retention pair arm: {pair}')
        arms = {r['mode']: r for r in on}
        if len(arms) != 2:
            pairs.append(dict(pair=pair, status='incomplete_pair'))
            continue
        a, b = arms['strongest'], arms['reservoir']
        pairs.append(
            dict(
                pair=pair,
                status='complete'
                if a['full_crc'] is not None and b['full_crc'] is not None
                else 'missing_analysis',
                strongest_crc=a['full_crc'],
                reservoir_crc=b['full_crc'],
                rate_difference=b['candidate_rate'] - a['candidate_rate'],
            )
        )
    complete = [p for p in pairs if p['status'] == 'complete']
    diff = np.array([int(p['reservoir_crc']) - int(p['strongest_crc']) for p in complete])
    # Do not silently condition inference on the subset with available analysis.
    inference = bool(pairs) and len(complete) == len(pairs)
    interval = None
    if inference:
        rng = np.random.default_rng(52840)
        boot = diff[rng.integers(0, len(diff), (20000, len(diff)))].mean(1)
        interval = np.percentile(boot, [2.5, 97.5]).tolist()
    win, lose = int(sum(diff == 1)), int(sum(diff == -1))
    n = win + lose
    pval = (
        min(1.0, 2 * sum(math.comb(n, k) for k in range(min(win, lose) + 1)) / 2**n) if n else 1.0
    )
    return dict(
        schema_version=2,
        groups=groups,
        pairs=pairs,
        records=rows,
        excluded_runs=excluded,
        paired_inference_complete=inference,
        paired_crc_difference=float(diff.mean()) if inference else None,
        paired_bootstrap_percentile_95=interval,
        exact_mcnemar_two_sided_p=pval if inference else None,
        discordant_reservoir_only=win if inference else None,
        discordant_strongest_only=lose if inference else None,
        cautions=CAUTIONS,
    )


CAUTIONS = [
    'Run-level retained-frame yield is not RF packet recall.',
    'Missing retained-IQ analysis is unknown, not a zero-yield run.',
    'No-retention passed runs remain in rate and retained-yield denominators.',
    'Component clipping is averaged only across analyzed buffers; no-retention runs have no IQ metric.',
    'Version 2 does not replace or reinterpret archived historical results.',
]
