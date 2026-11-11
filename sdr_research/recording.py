"""Single discontinuous burst per SigMF recording. No invented continuous timestamps."""

import json
from pathlib import Path

import numpy as np

from .protocol import Capture


def save_capture(capture, path_without_suffix):
    base = Path(path_without_suffix)
    if base.suffix in ('.sigmf-meta', '.sigmf-data'):
        base = base.with_suffix('')
    base.parent.mkdir(parents=True, exist_ok=True)
    data = Path(str(base) + '.sigmf-data')
    meta = Path(str(base) + '.sigmf-meta')
    if data.exists() or meta.exists():
        raise FileExistsError(f'Recording exists: {base}')
    with data.open('xb') as f:
        np.asarray(capture.iq, dtype='<c8').tofile(f)
    doc = {
        'global': {
            'core:datatype': 'cf32_le',
            'core:sample_rate': capture.sample_rate_hz,
            'core:version': '1.2.5',
            'core:description': 'ESP32 discontinuous raw I/Q burst, not a continuous session',
            'core:recorder': 'esp32-sdr-research 0.1.0',
            'core:extensions': [{'name': 'sdr_research', 'version': '1.0.0', 'optional': True}],
            'sdr_research:metadata': capture.metadata,
            'sdr_research:timing': {
                'monotonic_start_ns': capture.monotonic_start_ns,
                'monotonic_end_ns': capture.monotonic_end_ns,
                'firmware_capture_us': capture.firmware_capture_us,
                'bits': capture.bits,
                'crc_ok': capture.crc_ok,
                'nominal_rf_duration_s': len(capture.iq) / capture.sample_rate_hz,
                'timestamp_reference': 'host request, not hardware RF start',
            },
        },
        'captures': [
            {
                'core:sample_start': 0,
                'core:frequency': capture.frequency_hz,
                'core:datetime': capture.timestamp,
            }
        ],
        'annotations': [],
    }
    try:
        with meta.open('x') as f:
            json.dump(doc, f, indent=2)
    except Exception:
        data.unlink()
        raise
    return meta


def load_capture(meta_path):
    path = Path(meta_path)
    doc = json.loads(path.read_text())
    g = doc['global']
    c = doc['captures'][0]
    if g['core:datatype'] != 'cf32_le':
        raise ValueError('Replay currently supports cf32_le SigMF')
    data_path = path.with_suffix('.sigmf-data')
    if data_path.stat().st_size % 8:
        raise ValueError('Truncated complex float32 payload')
    iq = np.fromfile(data_path, dtype='<c8')
    if not len(iq):
        raise ValueError('Empty capture')
    t = g.get('sdr_research:timing', {})
    return Capture(
        iq,
        int(g['core:sample_rate']),
        int(c['core:frequency']),
        c['core:datetime'],
        t.get('monotonic_start_ns', 0),
        t.get('monotonic_end_ns', 0),
        t.get('firmware_capture_us', 0),
        t.get('bits', 8),
        t.get('crc_ok', False),
        g.get('sdr_research:metadata', {}),
    )
