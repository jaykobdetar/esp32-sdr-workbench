"""Single discontinuous burst per SigMF recording. No invented continuous timestamps."""

import json
import os
import tempfile
from pathlib import Path

import numpy as np

from ._version import __version__
from .protocol import Capture


def atomic_write_json(path: str | Path, document: dict) -> None:
    """Publish complete JSON with a same-directory rename, cleaning failed temp writes.

    A new summary is invisible until its final recording outcome is known. Existing readers
    see either the previous complete document or the new complete document, never a prefix.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(document, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def save_capture(capture: Capture, path_without_suffix: str | Path) -> Path:
    base = Path(path_without_suffix)
    if base.suffix in ('.sigmf-meta', '.sigmf-data'):
        base = base.with_suffix('')
    base.parent.mkdir(parents=True, exist_ok=True)
    data = Path(str(base) + '.sigmf-data')
    meta = Path(str(base) + '.sigmf-meta')
    if data.exists() or meta.exists():
        raise FileExistsError(f'Recording exists: {base}')
    doc = {
        'global': {
            'core:datatype': 'cf32_le',
            'core:sample_rate': capture.sample_rate_hz,
            'core:version': '1.2.5',
            'core:description': 'ESP32 discontinuous raw I/Q burst, not a continuous session',
            'core:recorder': f'esp32-sdr-research {__version__}',
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
    # Stage both files on the destination filesystem before exposing either name.
    # Hard links publish complete files without replacing a concurrent writer's files.
    # Metadata is the commit marker: readers must discover recordings through it.
    with tempfile.TemporaryDirectory(prefix=f'.{base.name}.', dir=base.parent) as staging:
        staged_data = Path(staging) / data.name
        staged_meta = Path(staging) / meta.name
        with staged_data.open('xb') as output:
            np.asarray(capture.iq, dtype='<c8').tofile(output)
            output.flush()
            os.fsync(output.fileno())
        with staged_meta.open('x') as output:
            json.dump(doc, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.link(staged_data, data)
        try:
            os.link(staged_meta, meta)
        except BaseException:
            # Only roll back our published inode, not an observed replacement.
            # lstat avoids following symlinks; the directory must be trusted.
            try:
                ours = staged_data.stat()
                published = data.lstat()
                if (ours.st_dev, ours.st_ino) == (published.st_dev, published.st_ino):
                    data.unlink()
            except FileNotFoundError:
                pass
            raise
    return meta


def load_capture(meta_path: str | Path) -> Capture:
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
