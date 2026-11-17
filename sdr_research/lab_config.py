"""Lab configuration shared by session orchestration and portable Studio settings.

Defaults, device configuration records and per-device validation use only the
standard library. Constructing or checking a configuration never opens a device.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def default_receiver_settings() -> dict:
    return dict(
        mode='DETPIPE1',
        frequency_mhz=2440,
        rate_hz=16_000_000,
        bandwidth_mhz=12,
        gain=40,
        bits=10,
        samples=16380,
        det_ms=1000,
        ratio_milli=4000,
        background_policy=1,
        candidate_count=1,
        threshold_db=10,
        autosave=True,
        record_all=True,
        scan=False,
    )


def default_transmitter_settings() -> dict:
    return dict(
        frequency_mhz=2440,
        mode_mbps=2,
        power_dbm=-20,
        length=64,
        interval_us=2000,
        jitter_us=0,
        seed=52840,
        payload_hex='off',
        hop_list='off',
        hop_every=1,
        burst_count=0,
        burst_gap_us=0,
    )


def _integer(settings: dict, key: str, low: int, high: int) -> None:
    value = settings[key]
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{key} must be an integer in {low}..{high}')


def validate_receiver(settings: dict, demo: bool) -> None:
    s = default_receiver_settings() | settings
    if s['mode'] not in ('raw', 'DET1', 'DETPIPE1', 'DSTREAMIQ'):
        raise ValueError('Unsupported receiver mode')
    if demo and s['mode'] != 'raw':
        raise ValueError('Synthetic input supports raw mode only')
    for key, low, high in (
        ('frequency_mhz', 2400, 2500),
        ('bandwidth_mhz', 0, 67),
        ('samples', 256, 16380),
        ('det_ms', 1, 5000),
        ('ratio_milli', 1000, 1000000),
    ):
        _integer(s, key, low, high)
    if s['gain'] is not None:
        _integer(s, 'gain', 0, 81)
    if s['rate_hz'] not in (16_000_000, 40_000_000, 80_000_000):
        raise ValueError('Unsupported receiver sample rate')
    if s['bits'] not in (8, 10) or (s['mode'] != 'raw' and s['bits'] != 10):
        raise ValueError('Detector modes require 10-bit samples')
    if s['background_policy'] not in (None, 1, 2):
        raise ValueError('Unsupported background policy')
    if s['candidate_count'] not in (1, 3) or (
        s['candidate_count'] == 3 and s['mode'] != 'DETPIPE1'
    ):
        raise ValueError('Three candidates require DETPIPE1')
    if s['mode'] == 'DSTREAMIQ' and (
        s['samples'] != 16380 or s['rate_hz'] != 16000000 or s['bits'] != 10
    ):
        raise ValueError('DSTREAMIQ requires16380samples,16MS/sand10bits')
    if s['scan']:
        raise ValueError('Shared lab sessions use fixed per-receiver frequencies')


def validate_transmitter(settings: dict, serial_number: str) -> None:
    s = default_transmitter_settings() | settings
    if not re.fullmatch(r'[0-9A-F]{16}', serial_number):
        raise ValueError('Transmitter needs its exact uppercase USB serial')
    if set(s) - (set(default_transmitter_settings()) | {'count'}):
        raise ValueError('Unknown transmitter setting')
    s.setdefault('count', 0)
    for key, low, high in (
        ('frequency_mhz', 2402, 2480),
        ('length', 8, 252),
        ('interval_us', 1000, 1000000),
        ('jitter_us', 0, 500000),
        ('seed', 1, 2000000000),
        ('burst_count', 0, 20000),
        ('burst_gap_us', 0, 1000000),
        ('hop_every', 1, 20000),
        ('count', 0, 20000),
    ):
        _integer(s, key, low, high)
    if type(s['mode_mbps']) is not int or s['mode_mbps'] not in (1, 2):
        raise ValueError('Transmitter mode must be 1 or 2 Mbps')
    if type(s['power_dbm']) is not int or s['power_dbm'] not in (-40, -20, -16, -12, -8, -4, 0):
        raise ValueError('Unsupported transmitter power')
    if s['interval_us'] < (s['length'] + 10) * 8 // s['mode_mbps'] + 300:
        raise ValueError('Packet interval too short for packet length and mode')
    if s['jitter_us'] > s['interval_us'] // 2:
        raise ValueError('Jitter exceeds half the packet interval')
    payload = s['payload_hex']
    if payload != 'off' and (
        not isinstance(payload, str)
        or not re.fullmatch(r'(?:[0-9A-Fa-f]{2})+', payload)
        or len(payload) // 2 > s['length'] - 8
    ):
        raise ValueError('Invalid payload hex or payload too long')
    hops = s['hop_list']
    if hops != 'off':
        if not isinstance(hops, str) or not re.fullmatch(r'[0-9]+(?:,[0-9]+)*', hops):
            raise ValueError('Invalid hopping list')
        values = list(map(int, hops.split(',')))
        if len(values) > 16 or any(not 2402 <= value <= 2480 for value in values):
            raise ValueError('Hopping list must contain at most 16 frequencies in 2402..2480')


@dataclass
class ReceiverConfig:
    label: str
    port: str
    settings: dict = field(default_factory=default_receiver_settings)
    demo: bool = False


@dataclass
class TransmitterConfig:
    label: str
    port: str
    serial_number: str
    settings: dict = field(default_factory=default_transmitter_settings)
