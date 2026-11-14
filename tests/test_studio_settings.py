import json

import pytest

from sdr_research.studio_settings import FIELDS, llm_prompt, parse_settings

BASE = dict(
    schema_version=1,
    task='listen',
    frequency_mhz=2440,
    duration_s=10,
    save_captures=True,
    receiver_mode='raw',
    sample_rate_hz=16000000,
    gain=40,
    bandwidth_mhz=12,
    samples=16380,
    detector_window_ms=500,
    ratio_milli=4000,
    background_policy=None,
    tx_power_dbm=-20,
    tx_mode_mbps=2,
    tx_length_bytes=16,
    tx_interval_us=2000,
)


def test_roundtrip_and_prompt():
    assert parse_settings(json.dumps(BASE)) == BASE
    prompt = llm_prompt(BASE)
    assert all(key in prompt for key in FIELDS)
    assert 'Import NEVER starts hardware' in prompt
    assert 'floor((tx_length_bytes+10)*8/tx_mode_mbps)+300' in prompt


@pytest.mark.parametrize(
    'key,value',
    [
        ('schema_version', True),
        ('gain', True),
        ('background_policy', False),
        ('duration_s', 11),
        ('frequency_mhz', 2481),
        ('receiver_mode', 'shell'),
        ('samples', 16381),
        ('ratio_milli', 4001),
        ('tx_power_dbm', 10),
        ('tx_interval_us', 999),
        ('save_captures', 1),
        ('sample_rate_hz', 16e6),
        ('gain', float('nan')),
    ],
)
def test_reject_invalid(key, value):
    with pytest.raises(ValueError):
        parse_settings(json.dumps(BASE | {key: value}))


@pytest.mark.parametrize(
    'text',
    [
        '[]',
        'null',
        '```json\n{}\n```',
        '{"schema_version":1,"schema_version":1}',
        'x' * 16001,
        '[' * 2000,
    ],
)
def test_reject_bad_documents(text):
    with pytest.raises(ValueError):
        parse_settings(text)


def test_missing_unknown_and_combination():
    for doc in [
        {},
        BASE | {'command': 'start'},
        BASE | {'tx_mode_mbps': 1, 'tx_length_bytes': 252, 'tx_interval_us': 1000},
    ]:
        with pytest.raises(ValueError):
            parse_settings(json.dumps(doc))


def test_indefinite_receive_only():
    doc = BASE | {'duration_s': None, 'save_captures': False}
    assert parse_settings(json.dumps(doc)) == doc
    with pytest.raises(ValueError):
        parse_settings(json.dumps(doc | {'task': 'test'}))
