"""Check the immutable public v7 evaluation export; never accesses hardware."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1] / 'docs/evidence/v7-evaluation'


def verify(root: Path = ROOT) -> dict:
    def read(name: str):
        return json.loads((root / name).read_text())

    manifest = read('publication-manifest.json')
    for name, digest in manifest['files'].items():
        assert Path(name).name == name
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    data = read('run-summaries.json')
    rows = data['runs']
    assert data['status'] == 'passed'
    stages = dict(Counter(r['stage'] for r in rows))
    assert stages == {'boundary': 336, 'rf_paired': 288, 'soak': 360}
    for row in rows:
        s = row['summary']
        assert s['captures'] == s['processed_captures']
        assert s['background_policy'] == row['policy']
        assert not any(s.get(k, 0) for k in ('status', 'errors', 'pack_failed'))
        assert row['recorded_transport_crc_valid']
    captures = sum(r['summary']['captures'] for r in rows)
    recordings = sum(len(r['recordings']) for r in rows)
    assert captures == 1288396 and recordings == 1520
    assert {r['heap_cleared'] for r in rows} == {'DETPIPEMEM 137456 69632'}
    assert data['distinct_campaign_calibration_fingerprints'] == 1
    rf = [r for r in rows if r['stage'] == 'rf_paired']
    for group in read('rf-statistics.json')['groups']:
        selected = [r for r in rf if (r['power'], r['gain']) == (group['power'], group['gain'])]
        lookup = {(r['pair'], r['policy'], r['tx_on']): r for r in selected}
        assert len(lookup) == len(selected) == 48

        def rate(pair: int, policy: int, on: bool, lookup=lookup) -> float:
            s = lookup[pair, policy, on]['summary']
            return s['detections'] * 1000000 / s['wall_elapsed_us']

        diffs = {}
        for policy in (1, 2):
            diffs[policy] = [rate(i, policy, True) - rate(i, policy, False) for i in range(12)]
            check_test(
                diffs[policy], group['policies'][str(policy)]['on_minus_off_candidates_per_second']
            )
        check_test(
            [b - a for a, b in zip(diffs[1], diffs[2], strict=True)],
            group['adaptive_minus_legacy_source_effect'],
        )
    decoder = read('rf-decoder-summaries.json')
    assert decoder['complete'] and len(decoder['runs']) == 288
    counts = {}
    for on in (False, True):
        records = [c for r in decoder['runs'] if r['tx_on'] == on for c in r['recordings']]
        counts['on' if on else 'off'] = {
            'recordings': len(records),
            'matching_payload_recordings': sum(bool(c['full_payload_matches']) for c in records),
            'crc_address_valid_recordings': sum(
                any(h['crc_verified'] and h['address_verified'] for h in c['full_payload_matches'])
                for c in records
            ),
        }
    assert counts['on'] == {
        'recordings': 144,
        'matching_payload_recordings': 15,
        'crc_address_valid_recordings': 11,
    }
    assert counts['off'] == {
        'recordings': 141,
        'matching_payload_recordings': 0,
        'crc_address_valid_recordings': 0,
    }
    timing = {}
    for image in ('v7', 'v2'):
        extra = read(f'extra-{image}.json')
        assert extra['status'] == 'passed' and len(extra['raw_controls']) == 72
        timing[image] = {
            str(retain): mean(
                r['summary']['nominal_local_rf_duty_percent']
                for r in extra['timing_runs']
                if r['retain'] == retain
            )
            for retain in (False, True)
        }
    return {
        'stages': stages,
        'captures': captures,
        'recordings': recordings,
        'rf': counts,
        'timing_local_duty_percent': timing,
        'exact_p_values_recomputed': True,
        'bootstrap_intervals_recomputed': False,
        'raw_rf_decoding_recomputed': False,
    }


def check_test(differences: list[float], expected: dict) -> None:
    observed = abs(mean(differences))
    extreme = sum(
        abs(sum(s * d for s, d in zip(signs, differences, strict=True)) / len(differences))
        >= observed - 1e-12
        for signs in itertools.product((-1, 1), repeat=len(differences))
    )
    p = extreme / (2 ** len(differences))
    assert math.isclose(mean(differences), expected['mean'], abs_tol=1e-10)
    assert p == expected['exact_two_sided_signflip_p']


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
