#!/usr/bin/env python3
"""Offline integrity and decoded-test-packet checks; no radio/device access.

Checks published artifacts, not fresh IQ demodulation or packet recall.
Replays the published seeded NumPy bootstrap; raises ValueError on inconsistency.
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from itertools import combinations, product
from pathlib import Path
from statistics import mean

import numpy as np


def known_payload(sequence, length):
    return (
        b'RFTX'
        + sequence.to_bytes(4, 'little')
        + bytes((k + sequence) & 255 for k in range(8, length))
    )


def radio_crc(data):
    """Nordic CRC16: init FFFF, poly 1021, LSB-first data, MSB-first CRC."""
    crc = 0xFFFF
    for byte in data:
        for shift in range(8):
            feedback = ((crc >> 15) & 1) ^ ((byte >> shift) & 1)
            crc = (crc << 1) & 0xFFFF
            if feedback:
                crc ^= 0x1021
    return f'{crc:04x}'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_packet(packet):
    observed = bytes.fromhex(packet['observed_payload_hex'])
    expected = known_payload(packet['sequence'], packet['length'])
    require(observed == expected, 'Observed payload does not match test pattern')
    require(
        bytes.fromhex(packet['expected_payload_hex']) == expected,
        'Saved expected payload does not match test pattern',
    )
    require(len(observed) == packet['length'], 'Payload length mismatch')
    require(packet['address_hex'] == 'efcdab89c3', 'Test address mismatch')
    crc = radio_crc(bytes.fromhex(packet['address_hex']) + bytes([packet['length']]) + observed)
    require(crc == packet['crc_computed'] == packet['crc_received_msb_first'], 'RF CRC mismatch')
    require(
        packet['full_known_payload_match']
        and packet['address_verified']
        and packet['crc_verified'],
        'Missing full-frame validation flags',
    )


def close(actual, expected, message):
    require(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9), message)


def bootstrap_means(values, rng):
    """Match the archived analysis: 20,000 paired resamples with seed 52840."""
    values = np.asarray(values, dtype=float)
    require(values.size > 0 and np.isfinite(values).all(), 'Invalid bootstrap values')
    return values[rng.integers(0, len(values), size=(20000, len(values)))].mean(axis=1)


def verify_interval(actual, saved, label):
    require(len(saved) == len(actual) == 2, label + ' interval length mismatch')
    for value, expected in zip(actual, saved, strict=True):
        close(float(value), expected, label + ' interval mismatch')
    return [float(value) for value in actual]


def exact_sign_flip(values):
    """Two-sided paired randomization test, including ties and all 2**n assignments.

    Exact enumeration is not a guarantee of exchangeability: temporal ordering and
    nonrandomized ON/OFF assignment still limit causal interpretation.
    """
    values = tuple(float(value) for value in values)
    require(0 < len(values) <= 20, 'Exact paired test requires 1 to 20 pairs')
    require(all(math.isfinite(value) for value in values), 'Nonfinite paired value')
    observed = abs(math.fsum(values))
    extreme = sum(
        abs(math.fsum(value * sign for value, sign in zip(values, signs, strict=True)))
        >= observed - 1e-10
        for signs in product((-1, 1), repeat=len(values))
    )
    return {'two_sided_p': extreme / (2 ** len(values)), 'assignments': 2 ** len(values)}


def exact_independent_permutation(first, second):
    """Relabel whole ON/OFF pairs, never IQ samples, for descriptive cycle tests."""
    require(len(first) == len(second) == 4, 'Cycle test requires two groups of four pairs')
    pool = tuple(first) + tuple(second)
    observed = abs(mean(second) - mean(first))
    extreme = 0
    total = 0
    for selected in combinations(range(8), 4):
        group = set(selected)
        difference = mean(pool[i] for i in range(8) if i not in group) - mean(
            pool[i] for i in selected
        )
        extreme += abs(difference) >= observed - 1e-10
        total += 1
    return {'two_sided_p': extreme / total, 'assignments': total}


def recompute_headlines(records, abab, retention):
    """Verify point estimates and every archived interval from published run data."""
    rng = np.random.default_rng(52840)
    phase_results = {}
    phase_deltas = {}
    phase_intervals = {}
    phase_tests = {}
    for phase in abab['phases']:
        name = phase['phase']
        require(name not in phase_results, 'Duplicate ABAB phase')
        rows = sorted(
            (r for r in records if r['recording'].startswith('nrf-abab/' + name + '/')),
            key=lambda row: row['recording'],
        )
        require(len(rows) == phase['runs'] == 8, 'ABAB phase size mismatch')
        pairs = {}
        states = {}
        state_intervals = {}
        for on in (True, False):
            rr = [r for r in rows if r['tx_on'] is on]
            require(len(rr) == 4, 'ABAB state size mismatch')
            metrics = []
            for r in rr:
                summary = r['receiver_summary']
                aperture_s = summary['total_samples'] / summary['sample_rate_hz']
                values = {
                    'candidate_rate': summary['detections'] * 1e6 / summary['wall_elapsed_us'],
                    'local_rf_duty': 100 * aperture_s * 1e6 / summary['wall_elapsed_us'],
                    'host_rf_duty': 100 * aperture_s * 1e6 / summary['host_total_elapsed_us'],
                }
                pair_key = (r['source_metadata']['pair'], on)
                require(pair_key not in pairs, 'Duplicate ABAB pair')
                pairs[pair_key] = values['candidate_rate']
                metrics.append(values)
            state = 'on' if on else 'off'
            states[state] = {k: mean(v[k] for v in metrics) for k in metrics[0]}
            state_intervals[state] = {}
            for key, value in states[state].items():
                saved = phase['states'][state][key]
                require(saved['n'] == 4, 'ABAB saved state size mismatch')
                close(value, saved['mean'], 'ABAB ' + key + ' mismatch')
                for observed, expected in zip(
                    [v[key] for v in metrics], saved['values'], strict=True
                ):
                    close(observed, expected, 'ABAB per-run ' + key + ' mismatch')
                state_intervals[state][key] = verify_interval(
                    np.percentile(bootstrap_means([v[key] for v in metrics], rng), [2.5, 97.5]),
                    saved['bootstrap_percentile_95'],
                    'ABAB ' + key,
                )
        pair_ids = sorted({pair for pair, on in pairs})
        require(len(pair_ids) == 4, 'ABAB pair count mismatch')
        deltas = [pairs[(pair, True)] - pairs[(pair, False)] for pair in pair_ids]
        close(
            mean(deltas),
            phase['paired_candidate_excess']['mean'],
            'ABAB paired candidate excess mismatch',
        )
        for actual, expected in zip(
            deltas, phase['paired_candidate_excess']['values'], strict=True
        ):
            close(actual, expected, 'ABAB pair excess mismatch')
        require(phase['paired_candidate_excess']['n'] == len(deltas), 'ABAB pair n mismatch')
        phase_deltas[name] = deltas
        phase_tests[name] = exact_sign_flip(deltas)
        phase_intervals[name] = {
            'states': state_intervals,
            'paired_candidate_excess': verify_interval(
                np.percentile(bootstrap_means(deltas, rng), [2.5, 97.5]),
                phase['paired_candidate_excess']['bootstrap_percentile_95'],
                'ABAB paired candidate excess',
            ),
        }
        phase_results[name] = {'states': states, 'candidate_excess_per_second': mean(deltas)}
    require(
        list(phase_results) == ['historical-1', 'historical-2', 'optimized-1', 'optimized-2'],
        'ABAB phase order mismatch for seeded bootstrap',
    )
    require([row['cycle'] for row in abab['cycle_effects']] == [1, 2], 'ABAB cycle mismatch')
    cycles = []
    for saved in abab['cycle_effects']:
        cycle = saved['cycle']
        excess = (
            phase_results[f'optimized-{cycle}']['candidate_excess_per_second']
            - phase_results[f'historical-{cycle}']['candidate_excess_per_second']
        )
        close(
            excess,
            saved['optimized_minus_historical_excess_per_second'],
            'ABAB cycle excess mismatch',
        )
        historical = phase_deltas[f'historical-{cycle}']
        optimized = phase_deltas[f'optimized-{cycle}']
        historical_boot = bootstrap_means(historical, rng)
        optimized_boot = bootstrap_means(optimized, rng)
        cycles.append(
            {
                'cycle': cycle,
                'optimized_minus_historical_excess_per_second': excess,
                'bootstrap_percentile_95': verify_interval(
                    np.percentile(optimized_boot - historical_boot, [2.5, 97.5]),
                    saved['bootstrap_percentile_95'],
                    'ABAB cycle excess',
                ),
                'exact_pair_label_permutation': exact_independent_permutation(
                    historical, optimized
                ),
            }
        )
    headline_duty = {
        kind: {
            metric: mean(
                phase_results[f'{kind}-{cycle}']['states']['on'][metric] for cycle in (1, 2)
            )
            for metric in ('local_rf_duty', 'host_rf_duty')
        }
        for kind in ('historical', 'optimized')
    }
    retention_rows = [r for r in records if r['recording'].startswith('nrf-retention/')]
    require(len(retention_rows) == 48, 'Retention size mismatch')
    policy_results = {}
    paired = {}
    for group in retention['groups']:
        mode, on = group['mode'], group['tx_on']
        rows = [r for r in retention_rows if r['mode'] == mode and r['tx_on'] is on]
        require(len(rows) == group['n'] == 12, 'Retention group size mismatch')
        valid = sum(r['full_address_payload_rf_crc_count'] > 0 for r in rows)
        require(valid == group['full_crc'], 'Retention full-frame count mismatch')
        z = 1.959963984540054
        n = len(rows)
        proportion = valid / n
        denominator = 1 + z * z / n
        center = (proportion + z * z / (2 * n)) / denominator
        half = z * math.sqrt(proportion * (1 - proportion) / n + z * z / (4 * n * n)) / denominator
        verify_interval(
            [center - half, center + half], group['full_crc_wilson_95'], 'Retention Wilson'
        )
        if on:
            policy_results[mode] = {'full_crc': valid, 'n': len(rows)}
            for r in rows:
                key = (r['source_metadata']['pair'], mode)
                require(key not in paired, 'Duplicate retention pair')
                paired[key] = r['full_address_payload_rf_crc_count'] > 0
    pair_ids = sorted({p for p, mode in paired})
    require(len(pair_ids) == 12, 'Retention pair count mismatch')
    require(
        len(retention['pairs']) == 12
        and sorted(row['pair'] for row in retention['pairs']) == pair_ids,
        'Retention saved pair IDs mismatch',
    )
    delta = []
    for p in pair_ids:
        strongest = paired[(p, 'strongest')]
        reservoir = paired[(p, 'reservoir')]
        saved = next(row for row in retention['pairs'] if row['pair'] == p)
        require(
            strongest == saved['strongest_crc'] and reservoir == saved['reservoir_crc'],
            'Retention paired result mismatch',
        )
        delta.append(int(reservoir) - int(strongest))
    difference = mean(delta)
    close(difference, retention['paired_crc_difference'], 'Retention paired difference mismatch')
    require(
        delta.count(1) == retention['discordant_reservoir_only']
        and delta.count(-1) == retention['discordant_strongest_only'],
        'Retention discordant pair count mismatch',
    )
    retention_interval = verify_interval(
        np.percentile(bootstrap_means(delta, np.random.default_rng(52840)), [2.5, 97.5]),
        retention['paired_bootstrap_percentile_95'],
        'Retention paired bootstrap',
    )
    wins, losses = delta.count(1), delta.count(-1)
    discordant = wins + losses
    mcnemar = (
        min(
            1.0,
            2 * sum(math.comb(discordant, k) for k in range(min(wins, losses) + 1)) / 2**discordant,
        )
        if discordant
        else 1.0
    )
    close(mcnemar, retention['exact_mcnemar_two_sided_p'], 'Retention McNemar mismatch')
    return {
        'abab_on_duty_percent': headline_duty,
        'abab_cycle_effects': cycles,
        'retention_on': policy_results,
        'retention_paired_difference': difference,
        'bootstrap_intervals_recomputed': True,
        'bootstrap_method': {'seed': 52840, 'resamples': 20000, 'percentiles': [2.5, 97.5]},
        'abab_phase_bootstrap_intervals': phase_intervals,
        'abab_exact_paired_sign_flip': phase_tests,
        'retention_paired_bootstrap_percentile_95': retention_interval,
        'retention_exact_mcnemar_two_sided_p': mcnemar,
        'retention_exact_paired_sign_flip': exact_sign_flip(delta),
        'statistical_cautions': [
            'Bootstrap units are whole ON/OFF pairs, not IQ samples or detected candidates.',
            'Four pairs give only 16 sign assignments; the minimum two-sided p is 0.125.',
            'Tests assume exchangeable labels or symmetric paired errors; temporal ABAB order '
            'and only two cycles do not establish those assumptions or causal improvement.',
            'Intervals are descriptive small-sample percentile intervals, not packet recall.',
        ],
    }


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    for item in manifest['files']:
        name = item['file']
        require(Path(name).name == name, 'Invalid artifact filename')
        data = (directory / name).read_bytes()
        require(
            hashlib.sha256(data).hexdigest() == item['sha256'],
            f'Artifact checksum mismatch: {name}',
        )
        require(len(data) == item['bytes'], f'Artifact size mismatch: {name}')
    records = json.loads((directory / 'recordings.json').read_text())
    packets = json.loads((directory / 'known-packets.json').read_text())
    totals = json.loads((directory / 'campaign-totals.json').read_text())
    by_id = {r['recording']: r for r in records}
    require(len(records) == len(by_id) == 550, 'Expected 550 unique recordings')
    require(all(r['transport_crc_valid'] is True for r in records), 'Transport CRC report mismatch')
    counts = Counter()
    for packet in packets:
        verify_packet(packet)
        require(packet['recording'] in by_id, 'Unknown packet recording')
        require(
            by_id[packet['recording']]['tx_on'] is True, 'Known packet unexpectedly labeled TX OFF'
        )
        counts[packet['recording']] += 1
    require(len(counts) == 25, 'Expected 25 RF-validated recordings')
    for record in records:
        require(
            counts[record['recording']] == record['full_address_payload_rf_crc_count'],
            'Recording RF validation count mismatch',
        )
        require(
            record['iq_bytes'] == record['metrics']['samples'] * 8, 'cf32_le byte count mismatch'
        )
        expected_us = record['metrics']['samples'] / record['sample_rate_hz'] * 1e6
        require(
            abs(expected_us - record['metrics']['aperture_us']) < 1e-8, 'Nominal aperture mismatch'
        )
    for total in totals:
        group = [r for r in records if r['recording'].split('/')[0] == total['campaign']]
        require(total['recordings'] == len(group), 'Campaign count mismatch')
        require(
            total['transport_crc_valid'] == sum(r['transport_crc_valid'] for r in group),
            'Campaign transport count mismatch',
        )
        require(
            total['rf_crc_valid_recordings'] == sum(bool(counts[r['recording']]) for r in group),
            'Campaign RF count mismatch',
        )
    headlines = recompute_headlines(
        records,
        json.loads((directory / 'abab-comparison.json').read_text())['results'],
        json.loads((directory / 'retention-comparison.json').read_text())['results'],
    )
    return {
        'headlines': headlines,
        'recordings': len(records),
        'transport_crc_valid': 550,
        'rf_crc_valid_recordings': len(counts),
        'verified_known_packets': len(packets),
        'packet_recall': None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'directory',
        nargs='?',
        type=Path,
        default=Path(__file__).resolve().parents[1] / 'docs/evidence/nrf-validation',
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), indent=2))


if __name__ == '__main__':
    main()
