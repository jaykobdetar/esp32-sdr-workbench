"""Synthetic software regression checks only; no hardware or RF claims."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'offline_nrf_analysis', Path(__file__).parents[1] / 'scripts/analyze_nrf_iq.py'
)
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)


def test_synthetic_known_packets_and_noise():
    result = analyzer.selftest()
    assert [r['mbps'] for r in result] == [1, 2]
    assert all(r['synthetic_payload_address_crc_recovered'] and r['noise_negative'] for r in result)
