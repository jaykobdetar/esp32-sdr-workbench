#!/usr/bin/env python3
"""Finite source controls using direct CAP20, never detector-selected IQ or flashing.

Run with python -m nrf_campaigns.nrf_raw_controls. Outputs are private local files.
Receiver frequency and bandwidth have setter acknowledgments but no readback queries.
"""

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

from sdr_research.calibration import ADAPTIVE_VARIANTS, CALIBRATION_VARIANTS, record_calibration
from sdr_research.protocol import Radio
from sdr_research.recording import atomic_write_json, save_capture

try:
    from .nrf_gain_compare import (
        SELECTORS,
        TX_KEYS,
        VARIANTS,
        check_gain,
        checked_status,
        selectors,
        usb_identity,
    )
except ImportError:
    from nrf_gain_compare import (
        SELECTORS,
        TX_KEYS,
        VARIANTS,
        check_gain,
        checked_status,
        selectors,
        usb_identity,
    )


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('rx-port', 'rx-serial', 'tx-port', 'tx-serial'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--rx-artifact', type=Path, required=True)
    p.add_argument('--output-directory', type=Path, required=True)
    p.add_argument('--expected-variant', choices=VARIANTS)
    p.add_argument('--expected-revision')
    p.add_argument('--seed', type=int, default=52840)
    p.add_argument('--power-dbm', type=int, choices=(-40, -20, -16, -12, -8, -4, 0), default=0)
    p.add_argument(
        '--geometry', default='Existing bench placement; distance and orientation unmeasured'
    )
    return p


def plan(args):
    if not 1 <= args.seed <= 2000000000:
        raise ValueError('Seed must be 1..2000000000')
    if args.power_dbm not in (-40, -20, -16, -12, -8, -4, 0):
        raise ValueError('Unsupported source power')
    blocks = list(range(4))
    random.Random(args.seed).shuffle(blocks)
    rows = []
    for pair in blocks:
        controls = [
            dict(pair=pair, kind='matched', rx_frequency_mhz=2440, tx_on=on)
            for on in ((False, True) if pair % 2 == 0 else (True, False))
        ]
        offset = dict(pair=pair, kind='offset', rx_frequency_mhz=2470, tx_on=True)
        rows.extend(([offset] + controls) if pair % 2 else (controls + [offset]))
    return rows


def configuration(args):
    return dict(
        frequency_mhz=2440,
        mode_mbps=2,
        power_dbm=args.power_dbm,
        payload_len=64,
        interval_us=2000,
        jitter_us=150,
        hop_list='off',
        hop_every=1,
        burst_count=0,
        burst_gap_us=0,
        payload_hex='off',
        seed=args.seed,
    )


def canonical(key, value):
    if key == 'hop_list':
        return (
            []
            if value == 'off'
            else ([int(x) for x in value.split(',')] if isinstance(value, str) else value)
        )
    if key == 'payload_hex':
        return '' if value == 'off' else value.lower()
    return value


def verify_config(status, expected):
    for key in TX_KEYS:
        if (
            key not in status
            or key not in expected
            or canonical(key, status[key]) != canonical(key, expected[key])
        ):
            raise RuntimeError(f'Transmitter configuration mismatch: {key}')
    if status.get('healthy') is not True or status.get('errors') != 0:
        raise RuntimeError('Transmitter health or error readback failed')
    if status.get('active_frequency_mhz') != expected['frequency_mhz'] and not canonical(
        'hop_list', expected['hop_list']
    ):
        raise RuntimeError('Transmitter active frequency mismatch')


def gain_value(reply):
    fields = reply.split()
    gain = None if len(fields) == 6 and fields[1] == 'HARDWARE' else int(fields[2])
    check_gain(reply, gain)
    return gain


def execute(args, radio, tx, *, saver=save_capture, sleep=time.sleep):
    conditions = plan(args)
    artifact_hash = hashlib.sha256(args.rx_artifact.read_bytes()).hexdigest()
    out = args.output_directory
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = dict(
        status='running',
        usb_identity=getattr(args, 'usb_identity', None),
        local_reference_artifact_sha256=artifact_hash,
        artifact_note='Local reference only; installed flash is not reread or modified.',
        geometry=args.geometry,
        geometry_measured=False,
        expected_variant=args.expected_variant,
        expected_revision=args.expected_revision,
        capture_selection='unselected direct CAP20',
        settings=dict(samples=16380, bits=10, rate_hz=16000000, gain=60, bandwidth_mhz=12),
        cautions=[
            'Each capture is about 1.024 ms of RF; source counters bracket host commands, not exact RF windows.',
            'CRC validates serial transport, not a decoded radio packet. No calibrated sensitivity or packet recall is established.',
            'Receiver frequency and bandwidth have acknowledged setters but no independent readback queries.',
            'Source configuration and receiver gain/selectors are restored; receiver ends at 2440 MHz and bandwidth 12 MHz.',
        ],
        source_configuration=configuration(args),
        runs=[dict(row, index=i, status='not_run') for i, row in enumerate(conditions)],
    )
    original_tx = initial_gain = initial_selectors = None
    connected = False

    def persist():
        atomic_write_json(out / 'results.json', report)

    def fingerprint(boundary):
        record_calibration(
            report,
            radio,
            report['device'],
            boundary,
            required=version['firmware_variant'] in CALIBRATION_VARIANTS,
        )
        persist()

    def stop_status():
        tx.stop()
        return checked_status(tx, False)

    try:
        report['tx_initial'] = original_tx = stop_status()
        if any(k not in original_tx for k in TX_KEYS):
            raise RuntimeError('Source snapshot is incomplete; refusing to change configuration')
        report['device'] = radio.connect()
        connected = True
        version_text = report['device'].get('version', '').removeprefix('VERSION ')
        try:
            version = json.loads(version_text)
        except json.JSONDecodeError:
            version = {'firmware_variant': version_text}
        if not isinstance(version, dict) or version.get('firmware_variant') not in VARIANTS:
            raise RuntimeError('Unsupported receiver firmware')
        if args.expected_variant and version.get('firmware_variant') != args.expected_variant:
            raise RuntimeError('Receiver variant mismatch')
        if args.expected_revision and version.get('revision') != args.expected_revision:
            raise RuntimeError('Receiver revision mismatch')
        fingerprint('stage_start')
        names = SELECTORS + (
            ('PIPEKEEP',) if version['firmware_variant'] in ADAPTIVE_VARIANTS else ()
        )
        report['selectors_initial'] = initial_selectors = selectors(radio, names)
        report['gain_initial'] = initial_gain = radio.command('GAIN?')
        gain_value(initial_gain)
        tx.configure(**report['source_configuration'])
        verify_config(checked_status(tx, False), report['source_configuration'])
        persist()
        for row in report['runs']:
            row['status'] = 'running'
            persist()
            try:
                row['tx_pre_stop'] = stop_status()
                verify_config(row['tx_pre_stop'], report['source_configuration'])
                radio.configure(row['rx_frequency_mhz'], 16000000, 12, 60, 10)
                # Explicit acknowledged setters avoid relying on the host configuration cache.
                row['receiver_setter_acknowledgments'] = {}
                for cmd in (f'FREQ {row["rx_frequency_mhz"]}', 'BANDWIDTH 12'):
                    reply = radio.command(cmd)
                    if reply != 'OK':
                        raise RuntimeError(f'Unexpected receiver setter reply: {reply!r}')
                    row['receiver_setter_acknowledgments'][cmd] = reply
                row['gain_before'] = check_gain(radio.command('GAIN?'), 60)
                row['selectors_before'] = selectors(radio, names)
                if row['selectors_before'] != initial_selectors:
                    raise RuntimeError('Receiver selector drift')
                fingerprint(f'run_{row["index"]}_before')
                if row['tx_on']:
                    row['tx_start'] = tx.start(count=5000, duration_ms=6000)
                sleep(0.1)
                row['tx_before'] = checked_status(tx, row['tx_on'])
                verify_config(row['tx_before'], report['source_configuration'])
                capture = radio.capture(16380)
                row['tx_after'] = checked_status(tx, row['tx_on'])
                verify_config(row['tx_after'], report['source_configuration'])
                row['tx_completed_delta'] = delta = (
                    row['tx_after']['completed'] - row['tx_before']['completed']
                )
                row['transport_crc_valid'] = capture.crc_ok
                row['gain_after'] = check_gain(radio.command('GAIN?'), 60)
                row['selectors_after'] = selectors(radio, names)
                if row['selectors_after'] != initial_selectors:
                    raise RuntimeError('Receiver selector drift')
                if delta < 0 or (row['tx_on'] and delta == 0) or (not row['tx_on'] and delta != 0):
                    raise RuntimeError('Unexpected transmitter completed-counter delta')
                if not capture.crc_ok:
                    raise RuntimeError('Raw capture transport CRC mismatch')
                if (
                    len(capture.iq),
                    capture.bits,
                    capture.sample_rate_hz,
                    capture.frequency_hz,
                ) != (16380, 10, 16000000, row['rx_frequency_mhz'] * 1000000):
                    raise RuntimeError('Raw capture configuration mismatch')
                capture.metadata['raw_source_control'] = dict(
                    selection='unselected direct CAP20',
                    condition=dict(row),
                    source_configuration=report['source_configuration'],
                    device=report['device'],
                    local_reference_artifact_sha256=artifact_hash,
                    cautions=report['cautions'],
                    geometry=args.geometry,
                )
                prefix = out / f'{row["index"]:02d}-{row["kind"]}-{"on" if row["tx_on"] else "off"}'
                row['sigmf'] = str(saver(capture, prefix))
                row['status'] = 'passed'
            except BaseException as exc:
                row.update(status='failed', error=repr(exc))
                raise
            finally:
                try:
                    row['tx_post_stop'] = stop_status()
                    fingerprint(f'run_{row["index"]}_after')
                except Exception as exc:
                    row.update(status='failed', stop_error=repr(exc))
                    raise
                finally:
                    persist()
        report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error=repr(exc))
        raise
    finally:
        cleanup_errors = []
        try:
            report['tx_final_stopped'] = stop_status()
            if original_tx and all(k in original_tx for k in TX_KEYS):
                restore = {k: original_tx[k] for k in TX_KEYS}
                restore['hop_list'] = (
                    ','.join(map(str, canonical('hop_list', restore['hop_list']))) or 'off'
                )
                restore['payload_hex'] = restore['payload_hex'] or 'off'
                tx.configure(**restore)
                report['tx_restored'] = checked_status(tx, False)
                verify_config(report['tx_restored'], original_tx)
        except Exception as exc:
            cleanup_errors.append('Source restoration: ' + repr(exc))
        if connected and initial_gain is not None:
            if getattr(radio, 'failed', False):
                cleanup_errors.append(
                    'Receiver transport failed; gain, selectors and final tuning are unverified.'
                )
            else:
                # Independent cleanup attempts preserve gain even when a selector command fails.
                for label, operation in (
                    (
                        'tuning',
                        lambda: restore_tuning(radio, initial_gain),
                    ),
                    ('selectors', lambda: restore_selectors(radio, initial_selectors)),
                    ('gain', lambda: restore_gain(radio, initial_gain)),
                ):
                    try:
                        report['receiver_restored_' + label] = operation()
                    except Exception as exc:
                        cleanup_errors.append(label + ': ' + repr(exc))
        if connected and isinstance(version, dict) and version.get('firmware_variant') in VARIANTS:
            try:
                fingerprint('stage_end')
            except Exception as exc:
                cleanup_errors.append('Calibration observation: ' + type(exc).__name__)
        report['cleanup_errors'] = cleanup_errors
        if cleanup_errors:
            report['status'] = 'failed'
        persist()
    return report


def restore_tuning(radio, original_gain):
    radio.configure(2440, 16000000, 12, gain_value(original_gain), 10)
    acknowledgments = {}
    for cmd in ('FREQ 2440', 'BANDWIDTH 12'):
        reply = radio.command(cmd)
        if reply != 'OK':
            raise RuntimeError(f'Final tuning setter failed: {reply!r}')
        acknowledgments[cmd] = reply
    return acknowledgments


def restore_selectors(radio, original):
    if original is None:
        return None
    for command in original.values():
        radio.command(command)
    observed = selectors(radio, original)
    if observed != original:
        raise RuntimeError('Selector restoration mismatch')
    return observed


def restore_gain(radio, original):
    if original is None:
        return None
    gain = gain_value(original)
    radio.command('GAIN HARDWARE' if gain is None else f'GAIN MANUAL {gain}')
    reply = check_gain(radio.command('GAIN?'), gain)
    return reply


def main():
    from nrf_tx.rf_tx import Transmitter
    from serial.tools import list_ports

    args = parser().parse_args()
    plan(args)
    if (
        Path(args.rx_port).resolve() == Path(args.tx_port).resolve()
        or args.rx_serial == args.tx_serial
    ):
        raise ValueError('Receiver and source must be distinct USB devices')
    # Check local prerequisites before opening either device.
    if not args.rx_artifact.is_file() or args.output_directory.exists():
        raise ValueError('Artifact must exist and output directory must be new')
    ports = list(list_ports.comports())
    args.usb_identity = dict(
        rx=usb_identity(args.rx_port, args.rx_serial, ports),
        tx=usb_identity(args.tx_port, args.tx_serial, ports),
    )
    radio = Radio(args.rx_port)
    try:
        with Transmitter(args.tx_port, serial_number=args.tx_serial) as tx:
            report = execute(args, radio, tx)
        print(
            json.dumps(dict(status=report['status'], output_directory=str(args.output_directory)))
        )
        return 0 if report['status'] == 'passed' else 1
    finally:
        radio.close()


if __name__ == '__main__':
    raise SystemExit(main())
