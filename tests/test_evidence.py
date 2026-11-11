"""Offline integrity/calculation tests; no board, network or private originals."""

import hashlib
import importlib.util
import json
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_headlines_and_source_hashes():
    actual = module('verify_evidence').verify()
    expected = json.loads((ROOT / 'docs/evidence/summary.json').read_text())
    assert actual == expected
    root = ROOT / 'docs/evidence'
    listed = set()
    for line in (root / 'SHA256SUMS.public').read_text().splitlines():
        digest, name = line.split('  ', 1)
        listed.add(name)
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    assert listed == {
        p.relative_to(root).as_posix()
        for p in root.rglob('*')
        if p.is_file() and p.name != 'SHA256SUMS.public'
    }


def test_synthetic_handshake_replay():
    from sdr_research.protocol import Radio

    fixture = json.loads((ROOT / 'docs/evidence/handshake/replay-fixture.json').read_text())
    archived = json.loads(
        (ROOT / 'docs/evidence/final/final-installed-verification.json').read_text()
    )
    assert fixture['kind'].startswith('synthetic')
    assert 'GAIN?' not in fixture['replies']
    radio = Radio('FAKE-NO-HARDWARE', transport=object())
    radio.synchronize = lambda: None
    commands = []

    def command(text):
        commands.append(text)
        return fixture['replies'][text]

    radio.command = command
    assert radio.connect() == archived['device']
    assert commands == ['INFO', 'CAPS', 'LIMITS?', 'VERSION?', 'TRANSPORT?', 'SPECINFO?']


@pytest.mark.parametrize('bits', [8, 10])
def test_endpoint_counts_and_q_sign(bits):
    scale = 1 << (bits - 1)
    # The saved complex format negates the packed wire Q.
    codes = [(-scale, 0), (0, scale - 1), (scale - 1, -scale), (2, -3)]
    data = b''.join(struct.pack('<ff', i / scale, -q / scale) for i, q in codes)
    result = module('count_sigmf_endpoints').count_endpoints(data, bits)
    assert result == dict(
        samples=4,
        i_endpoint_samples=2,
        wire_q_endpoint_samples=2,
        either_component_endpoint_samples=3,
        either_component_endpoint_percent=75.0,
    )


@pytest.mark.parametrize(
    'blob,bits',
    [
        (b'x', 10),
        (b'', 12),
        (struct.pack('<ff', float('nan'), 0), 10),
        (struct.pack('<ff', 1.0, 0), 10),
        (struct.pack('<ff', 0.0001, 0), 10),
    ],
)
def test_endpoint_rejects_invalid_data(blob, bits):
    with pytest.raises(ValueError):
        module('count_sigmf_endpoints').count_endpoints(blob, bits)
