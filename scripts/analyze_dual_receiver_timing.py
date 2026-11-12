import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdr_research.dual_timing import coverage, trace_windows

p = Path(sys.argv[1])
r = json.loads((p / 'results.json').read_text())
a = r['anchors']
if r['status'] != 'passed' or len(a) < 6:
    raise ValueError('A completed campaign with at least six RF anchors is required')
for anchor in a:
    pair = r['anchor_pairs'][anchor['pair']]
    for k, field in enumerate(('a_us', 'b_us')):
        hits = [
            h
            for h in pair['decoders'][k]['full_payload_matches']
            if h['sequence'] == anchor['sequence'] and h['crc_verified'] and h['address_verified']
        ]
        if len(hits) != 1 or not pair['receivers'][k]['transport_crc_valid']:
            raise ValueError('Anchor lacks unique verified packet evidence')
        observed = pair['receivers'][k]['trigger_device_us'] + hits[0]['payload_start_sample'] / 16
        if abs(observed - anchor[field]) > 1e-6:
            raise ValueError('Anchor timestamp does not match its packet metadata')
x = np.array([v['a_us'] for v in a])
y = np.array([v['b_us'] for v in a])
if (
    not np.all(np.isfinite(x))
    or not np.all(np.isfinite(y))
    or np.ptp(x) < 5e6
    or not np.all(np.diff(x) > 0)
):
    raise ValueError('Anchor time order/span insufficient')
x0 = x.mean()
y0 = y.mean()
slope = float(np.dot(x - x0, y - y0) / np.dot(x - x0, x - x0))
res = y - (y0 + slope * (x - x0))
# Alternating anchors train a separate fit; the other half are held out.
train = np.arange(len(x)) % 2 == 0
mx = x[train].mean()
my = y[train].mean()
ms = float(np.dot(x[train] - mx, y[train] - my) / np.dot(x[train] - mx, x[train] - mx))
heldout = y[~train] - (my + ms * (x[~train] - mx))
error = max(max(abs(res)), max(abs(heldout))) + 1.0
fit = dict(
    anchors=len(a),
    heldout_residual_us=heldout.tolist(),
    heldout_max_abs_us=float(max(abs(heldout))),
    span_s=float(np.ptp(x) / 1e6),
    a_origin_us=x0,
    b_origin_us=y0,
    b_per_a_slope=slope,
    relative_drift_ppm=(slope - 1) * 1e6,
    residual_us=res.tolist(),
    max_abs_residual_us=float(max(abs(res))),
    empirical_timing_allowance_us=float(error),
    allowance_note='Empirical residual plus one microsecond, not a guaranteed calibrated RF uncertainty bound.',
)
rows = []
all_windows = []
for row in r['runs']:
    w0 = trace_windows(row['receivers'][0]['trace'])
    wb = trace_windows(row['receivers'][1]['trace'])
    w1 = [(x0 + (s - y0) / slope, x0 + (e - y0) / slope) for s, e in wb]
    all_windows.extend(w0 + w1)
    start = row['scheduled_a_us']
    end = start + row['duration_ms'] * 1000
    full = coverage(w0 + w1, start, end)
    decision = coverage(
        [(a, b - 3.75) for a, b in w0[16:]] + [(a, b - 3.75 / slope) for a, b in w1[16:]],
        start,
        end,
    )
    inner = coverage(w0 + w1, start + 5000, end - 5000)
    individual = [coverage(w, start, end)['coverage_percent'] for w in (w0, w1)]
    shifts = [
        coverage(w0 + [(s + shift, e + shift) for s, e in w1], start, end)['coverage_percent']
        for shift in (-error, 0, error)
    ]
    rows.append(
        dict(
            index=row['index'],
            period_us=row['period_us'],
            phase_us=row['phase_us'],
            duration_ms=row['duration_ms'],
            retain=row['retain'],
            capture_counts=[v['trace']['count'] for v in row['receivers']],
            single_nominal_duty_percent=individual,
            summed_nominal_duty_percent=sum(individual),
            union_nominal_percent=full['coverage_percent'],
            post_warmup_decision_window_union_percent=decision['coverage_percent'],
            interior_union_nominal_percent=inner['coverage_percent'],
            gap_count=full['gap_count'],
            max_gap_us=full['max_gap_us'],
            interior_max_gap_us=inner['max_gap_us'],
            endpoint_shift_sensitivity_percent=shifts,
            late_us=[v['trace']['max_schedule_late_us'] for v in row['receivers']],
            skipped_slots=[v['trace']['skipped_slots'] for v in row['receivers']],
        )
    )
stream_result = None
if r.get('stream_chunks'):
    stream_windows = [[], []]
    decision_windows = []
    for k, chunks in enumerate(r['stream_chunks']):
        for chunk in chunks:
            windows = trace_windows(chunk['trace'])
            if k:
                windows = [(x0 + (a - y0) / slope, x0 + (b - y0) / slope) for a, b in windows]
            stream_windows[k].extend(windows)
            decision_windows.extend(
                [(a, b - (3.75 / slope if k else 3.75)) for a, b in windows[16:]]
            )
    together = stream_windows[0] + stream_windows[1]
    all_windows.extend(together)
    first = min(a for a, b in together)
    last = max(b for a, b in together)
    episode = coverage(together, first, last)
    episode.pop('gaps_us')
    planned_start = r['stream_model']['grid_a_us']
    planned = coverage(together, planned_start, planned_start + 30e6)
    planned.pop('gaps_us')
    stream_result = dict(
        full_episode=episode,
        fixed_30_second_window=planned,
        chunks=[len(v) for v in r['stream_chunks']],
        captures=[sum(q['trace']['count'] for q in v) for v in r['stream_chunks']],
        fixed_30_second_post_warmup_decision_window_percent=coverage(
            decision_windows, planned_start, planned_start + 30e6
        )['coverage_percent'],
        note='Includes real readout/restart gaps. Fixed 30-second window begins at the preselected shared grid. No RF anchors interrupt this window; affine clock fit uses the bracketing packet anchors.',
    )

for pair in r['anchor_pairs']:
    t0 = pair['receivers'][0]['trigger_device_us']
    t1 = x0 + (pair['receivers'][1]['trigger_device_us'] - y0) / slope
    all_windows.extend([(t0, t0 + 1023.75), (t1, t1 + 1023.75 / slope)])
span_start = min(w[0] for w in all_windows)
span_end = max(w[1] for w in all_windows)
session = coverage(all_windows, span_start, span_end)
session.pop('gaps_us')
session['denominator_note'] = (
    'First recorded RF trigger through last recorded nominal sample, including all between-run, transfer and anchor-analysis gaps; excludes initial setup and final cleanup.'
)
result = dict(
    status=r['status'],
    staggered_session_nominal_union=stream_result,
    whole_campaign_nominal_union=session,
    clock_fit=fit,
    runs=rows,
    notes=[
        'RF-aligned recorded trigger times plus nominal N/fs apertures, not externally calibrated continuous reception.',
        'No packet recall denominator. Trace transfers/configuration gaps are outside individual run denominators.',
        'No interpolation-only quantity should be called more than 100% union coverage.',
    ],
)
(p / 'analysis.json').write_text(json.dumps(result, indent=2))
print(json.dumps(fit, indent=2))
for q in rows:
    print(
        q['index'],
        q['period_us'],
        q['phase_us'],
        q['duration_ms'],
        q['retain'],
        'sum',
        round(q['summed_nominal_duty_percent'], 3),
        'union',
        round(q['union_nominal_percent'], 4),
        'interior',
        round(q['interior_union_nominal_percent'], 4),
        'maxgap',
        round(q['max_gap_us'], 2),
    )
