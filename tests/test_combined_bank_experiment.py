"""Offline experiment preparation and integrity checks; no hardware access."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

from scripts.prepare_bank_experiment import BASE, EXPERIMENT, ROOT, prepare
from scripts.verify_combined_banks import DEFAULT, load_evidence, verify, verify_campaign


def test_archived_combined_evidence_recomputes():
    result = verify()
    assert result['combined']['on_packets'] == 9
    assert result['combined']['on_completed'] == 23307
    assert result['combined']['off_packets'] == 0
    for period in ('800000', '820000', '850000', '900000'):
        assert result['combined']['periods'][period]['nominal_union_range'] == [100, 100]
    assert result['combined']['periods']['800000']['full100_range'][1] < 100
    assert result['combined']['session_nominal_percent'] < 27


@pytest.mark.parametrize('damage', ['trace', 'packet', 'bracket'])
def test_evidence_rejects_damage(damage):
    d = copy.deepcopy(load_evidence(DEFAULT / 'combined.json.gz'))
    if damage == 'trace':
        d['runs'][0]['receivers'][0]['rows'][0]['mean'] ^= 1
    elif damage == 'packet':
        hit = next(
            h for p in d['anchor_proofs'] for r in p['receivers'] for h in r['known_packet_hits']
        )
        hit['observed_payload_hex'] = '00'
    else:
        d['anchors'] = d['anchors'][:2]
    with pytest.raises(ValueError):
        verify_campaign(d)


@pytest.mark.skipif(
    not shutil.which('cc') or not shutil.which('git'), reason='Host cc and git required'
)
@pytest.mark.parametrize('variant', ['combined', 'unicore'])
def test_prepare_exact_sources_and_mocked_hardware(tmp_path, variant):
    destination = tmp_path / 'experiment'
    default_before = (ROOT / 'firmware/FIRMWARE_VARIANT').read_bytes()
    try:
        prepare(destination, variant)
        config = (destination / 'firmware/sdkconfig.defaults.esp32').read_text()
        assert ('CONFIG_ESP_MAIN_TASK_AFFINITY_CPU1=y' in config) == (variant == 'combined')
        subprocess.run(
            [
                sys.executable,
                '-m',
                'pytest',
                '-q',
                'firmware/tests/test_bank_combined.py',
                'firmware/tests/test_nvs_preservation.py',
                'firmware/tests/test_release_variant.py',
                'tests/test_stream_distribution.py',
            ],
            cwd=destination,
            env={**os.environ, 'PYTHONPATH': str(destination)},
            check=True,
        )
        assert (ROOT / 'firmware/FIRMWARE_VARIANT').read_bytes() == default_before
    finally:
        if destination.exists():
            subprocess.run(
                ['git', '-C', str(ROOT), 'worktree', 'remove', '--force', str(destination)],
                check=True,
            )


def test_publication_defaults_and_patch_identity():
    assert (
        ROOT / 'firmware/FIRMWARE_VARIANT'
    ).read_text().strip() == 'esp32-dual-sparse-iq-experimental-v7'
    manifest = json.loads((DEFAULT / 'manifest.json').read_text())
    assert manifest['publication_base'] == BASE
    assert (
        hashlib.sha256((EXPERIMENT / 'experiment.patch').read_bytes()).hexdigest()
        == manifest['patch_sha256']
    )


def test_collector_defaults_to_dry_run_without_device_environment(tmp_path):
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ('SDR_RX_A', 'SDR_RX_B', 'NRF_SERIAL', 'SDR_REPOSITORY')
    }
    output = tmp_path / 'not-created'
    result = subprocess.run(
        [
            sys.executable,
            str(EXPERIMENT / 'run_campaign.py'),
            str(output),
            '--variant',
            'esp32-bank-core1-combined-v5',
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert 'no devices opened' in result.stdout
    assert not output.exists()
