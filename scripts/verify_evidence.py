#!/usr/bin/env python3
"""Recompute public evidence checks offline. Never opens a serial device."""

import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence'


def load(path):
    return json.loads((EVIDENCE / path).read_text())


def duty(run, elapsed='wall_elapsed_us'):
    return 100 * run['total_samples'] / run['sample_rate_hz'] / (run[elapsed] / 1e6)


def bounds(values):
    return {'min': min(values), 'max': max(values)}


def verify():
    manifest = load('SOURCE_MANIFEST.json')
    for row in manifest['files']:
        blob = (EVIDENCE / row['path']).read_bytes()
        assert len(blob) == row['bytes'], row['path']
        assert hashlib.sha256(blob).hexdigest() == row['sha256'], row['path']
    diagnostics = load('diagnostic-sources/SOURCE_PROVENANCE.json')['files']
    for row in diagnostics:
        blob = (EVIDENCE / 'diagnostic-sources' / row['published_relative_path']).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == row['published_sha256'], row[
            'published_relative_path'
        ]
    final = load('final/final-release-v2.json')
    soak = load('final/final-release-v2-soak.json')
    gui = [load(f'gui/gui-run-{i:02d}.detpipe1.json') for i in range(1, 6)]
    historic = [
        r for phase in ('v2-B1', 'v2-B2') for r in load(f'historical-det1/{phase}.json')['runs']
    ]
    assert len(final['runs']) == 12 and len(soak['runs']) == 24 and len(historic) == 12
    for r in final['runs'] + soak['runs'] + gui + historic:
        assert r['status'] == 0 and r['errors'] == 0 and not r['errors_received']
        assert math.isclose(duty(r), r['nominal_rf_duty_percent'], abs_tol=1e-10)
        assert r['total_samples'] == r['captures'] * 16380
        assert r['analyzed_samples'] == r['captures'] * 16320
        if 'processed_captures' in r:
            assert r['processed_captures'] == r['captures']
    ab = {}
    for mode in ('baseline', 'optimized'):
        for retain in (False, True):
            rows = [
                r for r in final['runs'] if r['mode'] == mode and r['retain_requested'] == retain
            ]
            assert len(rows) == 3 and {r['repeat'] for r in rows} == {0, 1, 2}
            assert all(r['post_raw_crc'] for r in rows)
            assert all(r['retained_crc_valid'] == retain for r in rows)
            ab[f'{mode}_retain_{str(retain).lower()}'] = bounds([duty(r) for r in rows])
    assert sum(r['captures'] for r in soak['runs']) == 73745
    assert all(r['post_raw_crc'] and r['retained_crc_valid'] for r in soak['runs'])
    heap = {r['memory_after'] for r in soak['runs']}
    assert heap == {'DETPIPEMEM 96688 65536'}
    assert soak['memory_final'] == 'DETPIPEMEM 137688 73728'
    hist_mean = statistics.mean(duty(r) for r in historic)
    assert math.isclose(
        hist_mean, load('historical-det1/comparison-summary.json')['v2']['local_duty_mean']
    )
    last = gui[-1]
    cumulative_samples = sum(r['total_samples'] for r in gui)
    session = 100 * cumulative_samples / 16000000 / last['host_session_elapsed_through_recording_s']
    assert math.isclose(session, last['host_session_nominal_rf_duty_percent'], abs_tol=1e-10)
    assert all(r['retained_crc_valid'] for r in gui)
    kernel = {}
    for r in load('microbenchmarks/energy-test-v1-kernels.json')['runs']:
        assert r['end']['mismatch_mask'] == 0
        assert all(v['mismatch_count'] == 0 for v in r['results'])
        if r['samples'] != 16380:
            continue
        assert r['end']['cpu_hz_before'] == r['end']['cpu_hz_after'] == 240000000
        for v in r['results']:
            if v['placement'] == 'flash' and v['variant'] in (0, 3):
                kernel.setdefault(v['name'], []).append(v['median_cycles'] / 240)
    packing = {}
    for r in load('microbenchmarks/packing-v1.json')['runs']:
        assert (
            r['status'] == 0
            and r['pack_failed'] == 0
            and r['retained_crc_valid']
            and r['post_raw_crc']
        )
        if r['profile_enabled']:
            stage = next(s for s in r['profile_stages'] if s['name'] == 'retention')
            packing.setdefault(str(r['pack_requested']), []).append(
                stage['sum_us'] / stage['count']
            )
    fused = {}
    for r in load('microbenchmarks/validate-copy-v1.json')['runs']:
        assert r['end']['mismatch_mask'] == 0 and r['post_raw_crc']
        assert all(v['mismatch_count'] == 0 for v in r['results'])
        if r['request']['samples'] == 16380:
            for v in r['results']:
                fused.setdefault(v['name'], []).append(
                    v['median_cycles'] / (r['end']['cpu_hz_before'] / 1e6)
                )
    build = load('build/manifest.json')['variants']['esp32']
    app = next(p for p in build['parts'] if p['name'] == '2-esp_sdr.bin')
    assert (
        app['sha256'] == final['binary_sha256'] == load('build/version.json')['application_sha256']
    )
    assert (
        hashlib.sha256((EVIDENCE / 'build/sdkconfig').read_bytes()).hexdigest()
        == load('build/BUILD_VERIFICATION.json')['sha256']['build-esp32/sdkconfig']
    )
    clipping = load('gui/clipping-counts.json')
    assert (
        hashlib.sha256((ROOT / clipping['screenshot_public_path']).read_bytes()).hexdigest()
        == clipping['screenshot_sha256']
    )
    return {
        'final_ab_local_rf_duty_percent': ab,
        'soak': {
            'runs': 24,
            'captures': 73745,
            'local_rf_duty_percent': bounds([duty(r) for r in soak['runs']]),
            'host_run_rf_duty_percent': bounds(
                [duty(r, 'host_total_elapsed_us') for r in soak['runs']]
            ),
            'memory_after_every_run': sorted(heap),
            'memory_after_clear': soak['memory_final'],
        },
        'gui': {
            'runs': 5,
            'captures': sum(r['captures'] for r in gui),
            'last_run_local_rf_percent': duty(last),
            'host_session_rf_percent_through_last_recording': session,
            'note': 'Last-run local and cumulative host-session values are different aggregation windows.',
        },
        'historical_det1_v2': {
            'runs': 12,
            'mean_local_rf_percent': hist_mean,
            'range_local_rf_percent': bounds([duty(r) for r in historic]),
            'ratio_final_optimized_no_retention_mean_to_historical_mean': statistics.mean(
                duty(r)
                for r in final['runs']
                if r['mode'] == 'optimized' and not r['retain_requested']
            )
            / hist_mean,
        },
        'microbenchmarks': {
            'kernel_flash_median_us_ranges': {k: bounds(v) for k, v in kernel.items()},
            'packing_profiled_mean_us_ranges_by_option': {k: bounds(v) for k, v in packing.items()},
            'validate_copy_full_buffer_median_us_ranges': {k: bounds(v) for k, v in fused.items()},
        },
        'measurement_application_sha256': app['sha256'],
        'verified_source_manifest_files': len(manifest['files']),
        'verified_diagnostic_source_files': len(diagnostics),
    }


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
