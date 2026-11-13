"""Private, bounded ON/OFF sparse-IQ dual-receiver campaign. Dry-run by default.

Run with python -m nrf_campaigns.dual_sparse_campaign (installed package), or
python -m scripts.dual_sparse_campaign from the checkout. Never flashes devices.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event

from nrf_tx.rf_tx import Transmitter

from sdr_research.detector_stream import run_stream
from sdr_research.dual_timing import clock_probe
from sdr_research.protocol import Radio, decode_iq
from sdr_research.recording import atomic_write_json

from .analyze_nrf_iq import decode
from .dual_stream_campaign import Campaign, analyze_run, delta_at, fit_clock


def packet_union(run_id: str, decoded: list[dict]) -> dict:
    """Deduplicate CRC-valid known payloads within ONE transmitter START only.

    A sequence number reused after START is a different packet. Never combine
    rows from other runs, even when the numerical sequence/payload is identical.
    """
    seen = [set(), set()]
    for item in decoded:
        if item['run_id'] != run_id or item['receiver'] not in (0, 1):
            raise ValueError('Packet union crossed run or receiver identity')
        for hit in item['decoder']['full_payload_matches']:
            if not (
                hit.get('crc_verified') is True
                and hit.get('address_verified') is True
                and hit.get('full_known_payload_match') is True
            ):
                continue
            seq = hit['sequence']
            if type(seq) is not int or not 0 <= seq <= 0xFFFFFFFF:
                raise ValueError('Invalid packet sequence')
            if not hit.get('observed_payload_hex') or hit['observed_payload_hex'] != hit.get(
                'expected_payload_hex'
            ):
                raise ValueError('Decoder known-payload assertion disagrees')
            seen[item['receiver']].add((seq, hit['observed_payload_hex']))
    both, union = seen[0] & seen[1], seen[0] | seen[1]
    return dict(
        run_id=run_id,
        per_receiver_unique=[len(s) for s in seen],
        unique_union=len(union),
        shared=len(both),
        only_a=len(seen[0] - seen[1]),
        only_b=len(seen[1] - seen[0]),
        packet_keys=[dict(sequence=s, payload_hex=p) for s, p in sorted(union)],
        note='Distinct known CRC-valid packets in sparse recordings, not packet recall or continuous capture.',
    )


def save_snapshot(directory: Path, run_id: str, receiver: int, snapshot: dict) -> dict:
    """Bounded raw write only; decoding is deliberately deferred until shutdown."""
    payload = snapshot['payload']
    if len(payload) != 40950 or zlib.crc32(payload) != snapshot['crc32']:
        raise ValueError('Invalid full packed snapshot')
    name = f'{run_id}-rx{receiver}-g{snapshot["generation"]:08d}'
    raw = directory / (name + '.packed')
    # Exclusive creation prevents accidental replacement of earlier evidence.
    with raw.open('xb') as f:
        f.write(payload)
    metadata = {k: v for k, v in snapshot.items() if k != 'payload'}
    metadata.update(run_id=run_id, receiver=receiver, file=raw.name)
    atomic_write_json(directory / (name + '.json'), metadata)
    return metadata


def decode_saved(directory: Path, row: dict) -> dict:
    decoded = []
    for metadata in row['snapshots']:
        if metadata['run_id'] != row['run_id']:
            raise ValueError('Snapshot run mismatch')
        name = metadata['file']
        if Path(name).name != name:
            raise ValueError('Snapshot filename must be local')
        raw = (directory / name).read_bytes()
        if len(raw) != 40950 or zlib.crc32(raw) != metadata['crc32']:
            raise ValueError('Saved raw snapshot CRC/size mismatch')
        result = decode(decode_iq(raw, 16380, 10), 16_000_000, 2, 16)
        decoded.append(
            dict(
                run_id=row['run_id'],
                receiver=metadata['receiver'],
                file=name,
                generation=metadata['generation'],
                decoder=result,
            )
        )
    return dict(recordings=decoded, packets=packet_union(row['run_id'], decoded))


class SparseCampaign(Campaign):
    def run_sparse(self, duration_ms, period_ns, every, source_on, trial, yield_phase=32):
        self.tx.stop()
        model = fit_clock(self.report['anchors'][-24:])
        clock = clock_probe(self.radios[0])
        target = time.monotonic_ns() / 1000 + 500_000
        a = round(target + clock['offset_us'])
        b = round(a + delta_at(a, model) + period_ns / 2000)
        periods = [period_ns, round(period_ns * (1 + model['relative_drift']))]
        stop = Event()
        run_id = uuid.uuid4().hex
        snapshots = [[], []]
        row = dict(
            run_id=run_id,
            trial=trial,
            source_on=source_on,
            scheduled_a_us=a,
            scheduled_b_us=b,
            duration_ms=duration_ms,
            periods_ns=periods,
            yield_phases=[yield_phase, yield_phase],
            snapshot_every=every,
            snapshot_phases=[0, every // 2],
            clock_prediction=model,
            snapshots=[],
            status='running',
        )
        self.report['runs'].append(row)
        futures = []
        try:
            row['tx_before'] = self.tx.status()
            if source_on:
                row['tx_start'] = self.tx.start(count=0, duration_ms=duration_ms + 2000)
            for k, (radio, deadline) in enumerate(zip(self.radios, [a, b], strict=True)):

                def retain(snapshot, receiver=k):
                    snapshots[receiver].append(save_snapshot(self.out, run_id, receiver, snapshot))

                futures.append(
                    self.pool.submit(
                        run_stream,
                        radio,
                        start_us=deadline,
                        milliseconds=duration_ms,
                        period_ns=periods[k],
                        yield_phase=yield_phase,
                        stop=stop,
                        snapshot_every=every,
                        snapshot_phase=row['snapshot_phases'][k],
                        on_snapshot=retain,
                    )
                )
            for future in as_completed(futures):
                future.result()
            row['receivers'] = [f.result() for f in futures]
            row['status'] = 'captured'
        except BaseException as exc:
            stop.set()
            row['status'], row['error'] = 'failed', repr(exc)
            raise
        finally:
            # STOP source immediately, then join receiver owners before any close.
            try:
                self.tx.stop()
                row['tx_after'] = self.tx.status()
            finally:
                stop.set()
                for future in futures:
                    try:
                        future.result()
                    except BaseException:
                        pass
                row['snapshots'] = snapshots[0] + snapshots[1]
                self.save()
        row['calibration_after'] = [r.command('CALHASH?') for r in self.radios]
        self.save()
        print(
            'sparse run',
            run_id,
            'ON' if source_on else 'OFF',
            'snapshots',
            list(map(len, snapshots)),
            flush=True,
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', action='append', required=True)
    p.add_argument('--tx-serial', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run', action='store_true')
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--trials', type=int, default=1)
    p.add_argument('--period-ns', type=int, default=1875000)
    p.add_argument('--snapshot-every', type=int, default=1024)
    p.add_argument('--yield-phase', type=int, choices=range(34), default=32)
    p.add_argument('--power-dbm', type=int, choices=[-40, -20, -16, -12, -8, -4, 0], default=-4)
    p.add_argument('--gain', type=int, default=60)
    args = p.parse_args()
    if len(args.port) != 2 or len({str(Path(x).resolve()) for x in args.port}) != 2:
        p.error('Exactly two distinct verified receiver ports required')
    if not 1 <= args.seconds <= 55 or not 1 <= args.trials <= 10:
        p.error('Seconds 1..55 and trials 1..10 required')
    if not 1600000 <= args.period_ns <= 10000000 or not 1024 <= args.snapshot_every <= 1000000:
        p.error('Period or sparse interval outside supported limits')
    if not 0 <= args.gain <= 81:
        p.error('Manual gain must be 0..81')
    if not args.run:
        print(
            json.dumps(
                dict(
                    mode='dry-run',
                    seconds=args.seconds,
                    trials=args.trials,
                    snapshot_every=args.snapshot_every,
                    yield_phase=args.yield_phase,
                    order='alternating ON/OFF within each pair',
                    transmitter=dict(
                        frequency_mhz=2440,
                        mode_mbps=2,
                        power_dbm=args.power_dbm,
                        payload_len=16,
                        interval_us=1000,
                    ),
                    note='No device access. --run saves PRIVATE raw RF and identifiers. Counts are not recall.',
                )
            )
        )
        return
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    radios = [Radio(x) for x in args.port]
    campaign = None
    with Transmitter(serial_number=args.tx_serial) as tx, ThreadPoolExecutor(2) as pool:
        campaign = SparseCampaign(radios, tx, pool, args.output)
        report = campaign.report
        report['configuration'] = dict(
            seconds=args.seconds,
            trials=args.trials,
            period_ns=args.period_ns,
            snapshot_every=args.snapshot_every,
            yield_phase=args.yield_phase,
            gain=args.gain,
            frequency_mhz=2440,
            sample_rate_hz=16000000,
            samples=16380,
            bits=10,
            bandwidth_mhz=12,
            background_policy=1,
            transmitter_power_dbm=args.power_dbm,
            transmitter_mode_mbps=2,
            transmitter_payload_bytes=16,
            transmitter_interval_us=1000,
            transmitter_jitter_us=113,
            order='ON/OFF then OFF/ON, alternating by trial',
        )
        report['completion_note'] = (
            'Complete means collection and offline decoding completed. '
            'Each timing result has its own verified/unverified status; none is a packet-recall claim.'
        )
        try:
            tx.stop()
            report['devices'] = [r.connect() for r in radios]
            for r in radios:
                if 'DSTREAMIQ' not in r.info['caps']:
                    raise ValueError('Sparse-IQ firmware required on both receivers')
                r.command('TRACECLEAR')
                r.command('DETPIPECLEAR')
                r.configure(2440, 16000000, 12, args.gain, 10)
                r.command('ACQOPT 3')
                r.command('CLEAROPT 1')
                r.command('BGPOLICY 1')
            report['calibration_before'] = [r.command('CALHASH?') for r in radios]
            tx.configure(
                frequency_mhz=2440,
                mode_mbps=2,
                power_dbm=args.power_dbm,
                payload_len=16,
                interval_us=1000,
                jitter_us=113,
                hop_list='off',
                hop_every=1,
                burst_count=0,
                burst_gap_us=0,
                payload_hex='off',
                seed=52840,
            )
            campaign.anchors(needed=3, attempts=60)
            for trial in range(args.trials):
                for source_on in [True, False] if trial % 2 == 0 else [False, True]:
                    campaign.run_sparse(
                        round(args.seconds * 1000),
                        args.period_ns,
                        args.snapshot_every,
                        source_on,
                        trial,
                        args.yield_phase,
                    )
                    campaign.anchors(needed=3, attempts=60)
                    row = report['runs'][-1]
                    row['timing'] = analyze_run(row, report['anchors'])
                    campaign.save()
            report['status'] = 'captured-awaiting-offline-analysis'
        except BaseException as exc:
            report['status'], report['error'] = 'failed', repr(exc)
            raise
        finally:
            try:
                tx.stop()
                report['tx_final'] = tx.status()
            finally:
                for radio in radios:
                    radio.close()
                campaign.save()
    # No radio/transmitter is open while potentially expensive decoding runs.
    try:
        for row in campaign.report['runs']:
            row['decoding'] = decode_saved(args.output, row)
            campaign.save()
        campaign.report['status'] = 'complete'
    except BaseException as exc:
        campaign.report['status'], campaign.report['error'] = 'analysis-failed', repr(exc)
        raise
    finally:
        campaign.save()


if __name__ == '__main__':
    main()
