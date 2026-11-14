"""Recalculate archived combined-bank evidence, without opening any hardware."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import struct
import sys
import zlib
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.dual_stream_campaign import fit_clock, full_burst_opportunity, to_a
    from scripts.verify_nrf_evidence import verify_packet
else:
    from .dual_stream_campaign import fit_clock, full_burst_opportunity, to_a
    from .verify_nrf_evidence import verify_packet
from sdr_research.dual_timing import coverage

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'docs/evidence/combined-core-banks'


def require(value, message):
    if not value:
        raise ValueError(message)


def close(a, b):
    if isinstance(a, dict):
        require(a.keys() == b.keys(), 'Summary keys differ')
        for k in a:
            close(a[k], b[k])
    elif isinstance(a, list):
        require(len(a) == len(b), 'Summary lengths differ')
        for x, y in zip(a, b, strict=True):
            close(x, y)
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        require(
            math.isfinite(a) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-5),
            'Numeric summary mismatch',
        )
    else:
        require(a == b, 'Summary value mismatch')


def verify_campaign(d):
    require(d['status'] == 'passed' and d['runs'], 'Incomplete campaign')
    require(all(h['calibration_stable'] for h in d['health']), 'Unstable calibration')
    close(
        d['anchor_capture_times'],
        [
            {
                'index': p['index'],
                'receivers': [
                    {'trigger_us': r['trigger_us'], 'transport_crc_valid': r['transport_crc_valid']}
                    for r in p['receivers']
                ],
            }
            for p in d['anchor_proofs']
        ],
    )
    anchors = []
    for pair in d['anchor_proofs']:
        receivers = pair['receivers']
        require(
            len(receivers) == 2 and all(r['transport_crc_valid'] for r in receivers),
            'Invalid anchor transport',
        )
        packets = []
        for r in receivers:
            for h in r['known_packet_hits']:
                verify_packet(h)
            packets.append({h['sequence']: h for h in r['known_packet_hits']})
        for seq in sorted(packets[0].keys() & packets[1].keys()):
            t = [
                r['trigger_us'] + packets[k][seq]['payload_start_sample'] / 16
                for k, r in enumerate(receivers)
            ]
            anchors.append(dict(pair=pair['index'], sequence=seq, a_us=t[0], b_us=t[1]))
    close(anchors, d['anchors'])
    model = fit_clock(anchors)
    groups = {a['pair'] for a in anchors}
    require(len(groups) >= 6, 'Too few independent anchors')
    held = []
    for group in groups:
        m = fit_clock([a for a in anchors if a['pair'] != group])
        held.extend(abs(to_a(a['b_us'], m) - a['a_us']) for a in anchors if a['pair'] == group)
    model.update(heldout_max_error_us=max(held), independent_pairs=len(groups))
    require(
        model['max_residual_us'] < 20 and max(held) < 20 and abs(model['relative_drift']) < 0.001,
        'Clock screening failed',
    )
    close(model, d['clock_model'])
    c0 = d['host_clocks_before'][0]['best']
    c1 = d['host_clocks_after'][0]['best']
    require(
        all(c['host_after_us'] >= c['host_before_us'] for c in (c0, c1)), 'Invalid host bracket'
    )
    h0 = (c0['host_before_us'] + c0['host_after_us']) / 2
    h1 = (c1['host_before_us'] + c1['host_after_us']) / 2
    scale = (h1 - h0) / (c1['device_us'] - c0['device_us'])
    require(0.99 < scale < 1.01, 'Implausible host clock')
    host = lambda t: h0 + (t - c0['device_us']) * scale
    whole, analyzed = [], []
    on_packets = on_completed = off_packets = 0
    for index, row in enumerate(d['runs']):
        require(row['index'] == index and len(row['receivers']) == 2, 'Missing/reordered trial')
        require(
            row['source']['healthy']
            and not row['source']['running']
            and row['source']['errors'] == 0,
            'Source cleanup failure',
        )
        windows, packet_keys, per_receiver = [], set(), []
        for k, r in enumerate(row['receivers']):
            records = r['rows']
            require(r['crc_valid'] is True and len(records) == 1024, 'Incomplete trace')
            require(
                all(
                    a['trigger_us'] < b['trigger_us']
                    for a, b in zip(records, records[1:], strict=False)
                ),
                'Nonmonotonic trace',
            )
            wire = b''.join(
                struct.pack('<QII', t['trigger_us'], t['mean'], t['peak']) for t in records
            )
            require(zlib.crc32(wire) == r['trace_crc'], 'Trace CRC mismatch')
            require(
                r['device_start_us']
                <= records[0]['trigger_us']
                < records[-1]['trigger_us']
                < r['device_end_us'],
                'Invalid device window',
            )
            for t in records:
                a, b = t['trigger_us'], t['trigger_us'] + 511.75
                if k:
                    a, b = to_a(a, model), to_a(b, model)
                windows.append((a, b))
            if row['period_ns']:
                deadline = row['scheduled_b_us'] if k else row['scheduled_a_us']
                late = max(
                    t['trigger_us'] - deadline - i * row['periods_ns'][k] / 1000
                    for i, t in enumerate(records)
                )
                close(late, r['max_late_us'])
            hits = r['known_packet_hits']
            for h in hits:
                verify_packet(h)
                if row['on']:
                    require(
                        h['sequence'] < row['source']['completed'], 'Packet outside source START'
                    )
                packet_keys.add((h['sequence'], h['observed_payload_hex']))
            per_receiver.append(len(hits))
        require(
            len(packet_keys) == row['packets']['unique_full']
            and per_receiver == row['packets']['per_receiver'],
            'Packet totals differ',
        )
        if row['on']:
            require(row['source']['completed'] > 0, 'No completed source packets')
            on_packets += len(packet_keys)
            on_completed += row['source']['completed']
            close(
                len(packet_keys) / row['source']['completed'],
                row['packets']['whole_source_session_delivered_fraction'],
            )
        else:
            off_packets += len(packet_keys)
        start = row['scheduled_a_us'] if row['period_ns'] else min(a for a, b in windows)
        end = (
            start + 1024 * row['period_ns'] / 1000
            if row['period_ns']
            else max(
                row['receivers'][0]['device_end_us'],
                to_a(row['receivers'][1]['device_end_us'], model),
            )
        )
        require(
            len({a['pair'] for a in anchors if a['a_us'] < start}) >= 3
            and len({a['pair'] for a in anchors if a['a_us'] > end}) >= 3,
            'Missing independent bracketing anchors',
        )
        analyzed.append(
            dict(
                period=row['period_ns'],
                nominal=coverage(windows, start, end),
                full100=full_burst_opportunity(windows, start, end, 100),
                eroded=full_burst_opportunity(
                    [(a + 20, b - 20) for a, b in windows], start, end, 100
                ),
                host=coverage(
                    [(host(a), host(b)) for a, b in windows],
                    row['host_start_ns'] / 1000,
                    row['host_end_ns'] / 1000,
                ),
                receivers=row['receivers'],
            )
        )
        whole.extend((host(a), host(b)) for a, b in windows)
    for pair in d['anchor_capture_times']:
        for k, r in enumerate(pair['receivers']):
            a, b = r['trigger_us'], r['trigger_us'] + 1023.75
            if k:
                a, b = to_a(a, model), to_a(b, model)
            whole.append((host(a), host(b)))
    result = dict(
        status='passed',
        architecture=d['architecture'],
        clock_model=model,
        session_nominal_percent=coverage(
            whole, d['session_start_host_ns'] / 1000, d['session_end_host_ns'] / 1000
        )['coverage_percent'],
        session_s=(d['session_end_host_ns'] - d['session_start_host_ns']) / 1e9,
        periods={},
        on_packets=on_packets,
        on_completed=on_completed,
        off_packets=off_packets,
    )
    for period in sorted({r['period'] for r in analyzed}):
        rows = [r for r in analyzed if r['period'] == period]
        extent = lambda fn, rows=rows: [min(fn(r) for r in rows), max(fn(r) for r in rows)]
        result['periods'][str(period)] = dict(
            runs=len(rows),
            nominal_union_range=extent(lambda r: r['nominal']['coverage_percent']),
            full100_range=extent(lambda r: r['full100']['opportunity_percent']),
            eroded20_full100_range=extent(lambda r: r['eroded']['opportunity_percent']),
            max_gap_us=max(r['nominal']['max_gap_us'] for r in rows),
            host_command_nominal_range=extent(lambda r: r['host']['coverage_percent']),
            max_late_us=max(v.get('max_late_us', 0) for r in rows for v in r['receivers']),
            max_work_us=max(v['max_work_us'] for r in rows for v in r['receivers']),
        )
    return result


def load_evidence(path):
    with gzip.open(path, 'rb') as f:
        raw = f.read(64 * 1024 * 1024 + 1)
    require(len(raw) <= 64 * 1024 * 1024, 'Evidence too large')
    d = json.loads(raw)
    require(d['schema'] == 'combined-bank-evidence-v1', 'Unknown schema')
    return d['campaign']


def verify(directory=DEFAULT):
    manifest = json.loads((directory / 'manifest.json').read_text())
    result = {}
    for item in manifest['timing_files']:
        name = item['file']
        require(Path(name).name == name and name.endswith('.json.gz'), 'Unsafe evidence filename')
        path = directory / name
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'],
            'Evidence checksum mismatch',
        )
        d = load_evidence(path)
        require(len(d['runs']) == item['runs'], 'Manifest run count differs')
        result[name.removesuffix('.json.gz')] = verify_campaign(d)
    close(result, json.loads((directory / 'comparison-summary.json').read_text()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DEFAULT)
    args = parser.parse_args()
    result = verify(args.directory)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
