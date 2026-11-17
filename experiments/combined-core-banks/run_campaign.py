"""Explicitly enabled finite hardware experiment. Never flashes firmware."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument(
        '--variant',
        required=True,
        choices=('esp32-bank-unicore-control-v5', 'esp32-bank-core1-combined-v5'),
    )
    parser.add_argument('--repeats', type=int, default=3, choices=(1, 2, 3))
    parser.add_argument(
        '--run',
        action='store_true',
        help='Operate the explicitly selected radios and bounded test transmitter',
    )
    args = parser.parse_args()
    if not args.run:
        print(
            'Dry run: no devices opened. --run explicitly enables the bounded transmitter/capture campaign.'
        )
        return
    if not __debug__:
        raise SystemExit('Do not use python -O: integrity checks must remain enabled.')
    import os
    import struct
    import sys
    import threading
    import time
    import zlib
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np

    repo = Path(os.environ.get('SDR_REPOSITORY', Path(__file__).resolve().parents[2]))
    sys.path[:0] = [str(repo), str(repo / 'nrf52840-transmitter/host')]
    from rf_tx import Transmitter

    from scripts.analyze_nrf_iq import decode
    from scripts.dual_stream_campaign import (
        Campaign,
        delta_at,
        fit_clock,
        full_burst_opportunity,
        to_a,
    )
    from scripts.verify_nrf_evidence import verify_packet
    from sdr_research.dual_timing import clock_probe, coverage
    from sdr_research.pipeline import run_pipeline
    from sdr_research.protocol import ProtocolError, Radio

    os.umask(0o077)
    out = args.output
    out.mkdir(mode=0o700)
    variant = args.variant
    repeats = args.repeats
    radios = [Radio(os.environ[k]) for k in ('SDR_RX_A', 'SDR_RX_B')]
    if not radios[0].port or radios[0].port == radios[1].port:
        raise ValueError('Choose two distinct explicit receiver ports')

    def source_cfg(s):
        d = {
            k: s[k]
            for k in (
                'frequency_mhz',
                'mode_mbps',
                'power_dbm',
                'payload_len',
                'interval_us',
                'jitter_us',
                'seed',
                'burst_count',
                'burst_gap_us',
                'hop_every',
            )
        }
        d.update(
            hop_list=','.join(map(str, s['hop_list'])) or 'off',
            payload_hex=s['payload_hex'] or 'off',
        )
        return d

    def bank(r, idx, k, deadline, period):
        start = time.monotonic_ns()
        command = f'BANKAT 1024 0 {deadline} {period}' if period else 'BANKRUN 1024 0'
        h = r.command(command).split()
        assert h[:3] == ['BANKRUN', '1024', '8188'], h
        header_host = time.monotonic_ns()
        data = r._read(16384)
        assert zlib.crc32(data) == int(h[3], 16)
        assert r._line() == 'BANKEND'
        rows = [
            {'trigger_us': a, 'mean': b, 'peak': c} for a, b, c in struct.iter_unpack('<QII', data)
        ]
        assert len(rows) == 1024 and all(
            a['trigger_us'] < b['trigger_us'] for a, b in zip(rows, rows[1:], strict=False)
        )
        h2 = r.command('BANKGET').split()
        assert h2[:2] == ['BANKDATA', '8188']
        raw = r._read(32752)
        assert zlib.crc32(raw) == int(h2[2], 16) and int(h2[3]) == rows[-1]['trigger_us']
        filename = f'run-{idx:03}-rx{k}.u32'
        (out / filename).write_bytes(raw)
        result = {
            'rows': rows,
            'trace_crc': zlib.crc32(data),
            'raw_crc': zlib.crc32(raw),
            'raw_file': filename,
            'device_start_us': int(h[4]),
            'device_end_us': int(h[5]),
            'max_work_us': int(h[6]),
            'idle_observed': int(h[7]),
            'idle_fallbacks': int(h[8]),
            'host_start_ns': start,
            'header_host_ns': header_host,
            'host_end_ns': time.monotonic_ns(),
            'crc_valid': True,
        }
        if period:
            result['max_late_us'] = max(
                v['trigger_us'] - deadline - i * period / 1000 for i, v in enumerate(rows)
            )
        result['single_nominal_device_window'] = coverage(
            [(v['trigger_us'], v['trigger_us'] + 511.75) for v in rows], int(h[4]), int(h[5])
        )
        return result

    with Transmitter(serial_number=os.environ['NRF_SERIAL']) as tx, ThreadPoolExecutor(2) as pool:
        tx.stop()
        old = source_cfg(tx.status())
        camp = Campaign(radios, tx, pool, out)
        d = camp.report
        d['architecture'] = variant
        d['startup'] = {}
        d['health'] = []
        try:
            d['devices'] = [r.connect() for r in radios]
            for k, r in enumerate(radios):
                assert variant in d['devices'][k]['version']
                expected = 'CORE 1 2' if 'combined' in variant else 'CORE 0 1'
                assert r.command('CORE?') == expected
                r.configure(2440, 16000000, 12, 60, 10)
                r.command('BGPOLICY 1')
                row = {
                    'receiver': k,
                    'core': expected,
                    'cal_before': r.command('CALHASH?'),
                    'live': [],
                    'finite': [],
                }
                d['health'].append(row)
                for _ in range(8):
                    for mode in (1, 2):
                        f = list(map(int, r.command(f'BANKLIVE {mode}').split()[1:]))
                        assert f[:7] == [mode, 1, 8188, 0, 0, 0, 0], f
                        row['live'].append(f)
                for bad in ('BANKRUN 0 0', 'BANKAT 8 0 1 800000'):
                    try:
                        r.command(bad)
                        raise AssertionError('Invalid command accepted')
                    except ProtocolError as e:
                        assert 'ERR bank_args' in str(e)
                deadline = int(r.command('CLOCK?').split()[1]) + 400000
                timer = threading.Timer(0.1, lambda r=r: r.serial.write(b'STOP\n'))
                timer.start()
                try:
                    try:
                        r.command(f'BANKAT 1024 0 {deadline} 900000')
                        raise AssertionError('STOP ignored')
                    except ProtocolError as e:
                        assert 'ERR bank_run 3 0 0' in str(e), e
                        row['stop_before_start'] = 'passed'
                finally:
                    timer.cancel()
                r.command('BANKDROP')
                for retain in (False, True):
                    summary, capture = run_pipeline(
                        r, milliseconds=200, retain=retain, kernel=3, optimized=True
                    )
                    assert summary['status'] == 0
                    if retain:
                        assert capture.crc_ok
                    row['finite'].append(
                        {
                            'retain': retain,
                            'summary': summary,
                            'crc_ok': None if capture is None else capture.crc_ok,
                        }
                    )
            tx.configure(
                frequency_mhz=2440,
                mode_mbps=2,
                power_dbm=0,
                payload_len=16,
                interval_us=1000,
                jitter_us=113,
                seed=52840,
                burst_count=0,
                burst_gap_us=0,
                hop_every=1,
                hop_list='off',
                payload_hex='off',
            )
            d['session_start_host_ns'] = time.monotonic_ns()
            d['host_clocks_before'] = list(pool.map(clock_probe, radios))
            camp.anchors(8)
            for repeat in range(repeats):
                periods = (
                    (0, 800000, 820000, 850000, 900000)
                    if repeat % 2 == 0
                    else (900000, 850000, 820000, 800000, 0)
                )
                for period in periods:
                    for on in (False, True) if repeat % 2 == 0 else (True, False):
                        tx.stop()
                        idx = len(d['runs'])
                        row = {
                            'index': idx,
                            'repeat': repeat,
                            'period_ns': period,
                            'on': on,
                            'host_start_ns': time.monotonic_ns(),
                            'status': 'running',
                        }
                        d['runs'].append(row)
                        camp.save()
                        model = fit_clock(d['anchors'][-12:])
                        c = clock_probe(radios[0])
                        target = time.monotonic_ns() / 1000 + 250000
                        a = round(target + c['offset_us'])
                        b = round(a + delta_at(a, model) + period / 2000)
                        row.update(
                            scheduled_a_us=a,
                            scheduled_b_us=b,
                            clock_prediction=model,
                            periods_ns=[period, round(period * (1 + model['relative_drift']))],
                        )
                        fs = []
                        try:
                            if on:
                                row['tx_start'] = tx.start(count=4000, duration_ms=3000)
                            fs = [
                                pool.submit(bank, r, idx, k, (a, b)[k], row['periods_ns'][k])
                                for k, r in enumerate(radios)
                            ]
                            row['receivers'] = [f.result() for f in fs]
                            row['status'] = 'captured'
                        finally:
                            tx.stop()
                            for f in fs:
                                try:
                                    f.result()
                                except BaseException:
                                    pass
                            row['tx_final'] = tx.status()
                            row['host_end_ns'] = time.monotonic_ns()
                            assert (
                                not row['tx_final']['running']
                                and row['tx_final']['healthy']
                                and row['tx_final']['errors'] == 0
                            )
                            camp.save()
                        print(
                            'run',
                            idx,
                            period,
                            on,
                            'work',
                            [v['max_work_us'] for v in row['receivers']],
                            'late',
                            [v.get('max_late_us') for v in row['receivers']],
                            flush=True,
                        )
            camp.anchors(8)
            d['host_clocks_after'] = list(pool.map(clock_probe, radios))
            d['session_end_host_ns'] = time.monotonic_ns()
            for k, r in enumerate(radios):
                c = r.capture()
                assert c.crc_ok
                d['health'][k]['final_raw_crc'] = c.crc_ok
                d['health'][k]['cal_after'] = r.command('CALHASH?')
            d['status'] = 'captured'
            camp.save()
        except BaseException as e:
            d.update(status='failed', error=repr(e))
            camp.save()
            raise
        finally:
            tx.stop()
            tx.configure(**old)
            d['source_final'] = tx.status()
            for r in radios:
                r.close()
            camp.save()
    # Analysis uses only independently bracketed, full known-payload + address + air-CRC anchors.
    assert all(
        h.get('full_known_payload_match')
        for pair in d['anchor_pairs']
        for dec in pair['decoders']
        for h in dec['full_payload_matches']
        if h['crc_verified'] and h['address_verified']
    )
    model = fit_clock(d['anchors'])
    groups = {x['pair'] for x in d['anchors']}
    held = []
    for group in groups:
        m = fit_clock([x for x in d['anchors'] if x['pair'] != group])
        held.extend(abs(to_a(x['b_us'], m) - x['a_us']) for x in d['anchors'] if x['pair'] == group)
    model['heldout_max_error_us'] = max(held)
    model['independent_pairs'] = len(groups)
    assert model['max_residual_us'] < 20 and max(held) < 20, (
        'Clock screening failed; no verified coverage claim'
    )
    d['clock_model'] = model
    c0 = d['host_clocks_before'][0]['best']
    c1 = d['host_clocks_after'][0]['best']
    h0 = (c0['host_before_us'] + c0['host_after_us']) / 2
    h1 = (c1['host_before_us'] + c1['host_after_us']) / 2
    scale = (h1 - h0) / (c1['device_us'] - c0['device_us'])

    def host(t):
        return h0 + (t - c0['device_us']) * scale

    whole = []
    for row in d['runs']:
        windows = []
        keys = set()
        per = []
        for k, r in enumerate(row['receivers']):
            for t in r['rows']:
                a = t['trigger_us']
                b = a + 511.75
                if k:
                    a, b = to_a(a, model), to_a(b, model)
                windows.append((a, b))
            raw = np.fromfile(out / r['raw_file'], dtype='<u4')
            i = (raw & 1023).astype(np.int32)
            q = ((raw >> 10) & 1023).astype(np.int32)
            i = np.where(i >= 512, i - 1024, i)
            q = np.where(q >= 512, q - 1024, q)
            r['decoder'] = decode(((i - 1j * q) / 512).astype(np.complex64), 16000000, 2, 16)
            hits = [
                h
                for h in r['decoder']['full_payload_matches']
                if h['crc_verified'] and h['address_verified'] and h['full_known_payload_match']
            ]
            for h in hits:
                verify_packet(h)
                if row['on']:
                    assert h['sequence'] < row['tx_final']['completed']
                keys.add((h['sequence'], h['observed_payload_hex']))
            per.append(len(hits))
        start = row['scheduled_a_us'] if row['period_ns'] else min(a for a, b in windows)
        end = (
            start + 1024 * row['period_ns'] / 1000
            if row['period_ns']
            else max(
                row['receivers'][0]['device_end_us'],
                to_a(row['receivers'][1]['device_end_us'], model),
            )
        )
        assert (
            sum(x['a_us'] < start for x in d['anchors']) >= 3
            and sum(x['a_us'] > end for x in d['anchors']) >= 3
        )
        row['analysis'] = {
            'nominal_union': coverage(windows, start, end),
            'full100': full_burst_opportunity(windows, start, end, 100),
            'erosion': [
                {
                    'us': e,
                    'nominal': coverage([(a + e, b - e) for a, b in windows], start, end),
                    'full100': full_burst_opportunity(
                        [(a + e, b - e) for a, b in windows], start, end, 100
                    ),
                }
                for e in (1, 5, 20)
            ],
            'host_complete_command_nominal': coverage(
                [(host(a), host(b)) for a, b in windows],
                row['host_start_ns'] / 1000,
                row['host_end_ns'] / 1000,
            ),
        }
        row['packets'] = {
            'unique_full': len(keys),
            'per_receiver': per,
            'completed_source_packets': row['tx_final']['completed'] if row['on'] else 0,
            'whole_source_session_delivered_fraction': len(keys) / row['tx_final']['completed']
            if row['on']
            else None,
            'note': 'Only each receiver final snapshot retained. All completed transmissions in this bounded ON source session are denominator, including scheduled wait and readout gaps. Not conditional aperture recall or continuous output.',
        }
        whole.extend((host(a), host(b)) for a, b in windows)
        row['status'] = 'analyzed'
    for pair in d['anchor_pairs']:
        for k, r in enumerate(pair['receivers']):
            a = r['trigger_us']
            b = a + 1023.75
            if k:
                a, b = to_a(a, model), to_a(b, model)
            whole.append((host(a), host(b)))
    d['whole_measurement_session_nominal'] = coverage(
        whole, d['session_start_host_ns'] / 1000, d['session_end_host_ns'] / 1000
    )
    d['timing_note'] = (
        'Trigger + N/fs nominal windows, not calibrated RF aperture. RF fit and USB midpoint mapping are empirical estimates, not confidence bounds. Whole session includes initial/post anchors, waits, UART trace/IQ readout and all inter-trial gaps. No trimming.'
    )
    d['status'] = 'passed'
    camp.save()
    print(
        'PASSED',
        variant,
        'session',
        d['whole_measurement_session_nominal']['coverage_percent'],
        'clock',
        model,
        'packets',
        [(r['on'], r['packets']['unique_full']) for r in d['runs']],
        flush=True,
    )


if __name__ == '__main__':
    main()
