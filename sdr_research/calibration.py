"""Private, read-only stored-PHY fingerprints at explicit campaign boundaries.

Not an integrity check or a snapshot of live radio coefficients. In particular,
identical observations cannot rule out changes and reversions between queries.
"""

import json
import re
from datetime import datetime, timezone

CURRENT_VARIANT = 'esp32-pipeline-adaptive-q16-v8'
CALIBRATION_VARIANTS = (
    'esp32-pipeline-adaptive-q16-v4',
    'esp32-pipeline-adaptive-q16-v5',
    'esp32-pipeline-adaptive-q16-v6',
    'esp32-pipeline-adaptive-q16-v7',
    CURRENT_VARIANT,
)
ADAPTIVE_VARIANTS = ('esp32-pipeline-adaptive-q16-v3', *CALIBRATION_VARIANTS)


def record_calibration(report, radio, info, boundary, *, required=False):
    """Append and return one observation; malformed/failed supported reads fail closed."""
    observations = report.setdefault('calibration_observations', [])
    row = dict(boundary=boundary, host_utc=datetime.now(timezone.utc).isoformat())
    observations.append(row)
    if getattr(radio, 'failed', False):
        row.update(status='unavailable', reason='Receiver transport failed; no query attempted')
        raise RuntimeError('Calibration fingerprint unavailable after transport failure')
    if 'CALHASH' not in info.get('caps', []):
        row.update(status='unsupported', reason='Firmware does not advertise CALHASH')
        if required:
            raise RuntimeError('Required calibration fingerprint capability missing')
        return row
    try:
        reply = radio.command('CALHASH?')
        if not reply.startswith('CALHASH '):
            raise ValueError('Invalid calibration reply prefix')
        value = json.loads(reply[len('CALHASH ') :])
        if (
            not isinstance(value, dict)
            or type(value.get('version')) is not int
            or value['version'] != 1
            or value.get('algorithm') != 'sha256'
            or type(value.get('bytes')) is not int
            or value['bytes'] != 1904
            or type(value.get('device_us')) is not int
            or value['device_us'] < 0
            or not isinstance(value.get('sha256'), str)
            or re.fullmatch('[0-9a-f]{64}', value['sha256']) is None
        ):
            raise ValueError('Invalid stored-PHY fingerprint fields')
        # Copy only the documented fields, never arbitrary device output.
        row.update(status='observed', **{k: value[k] for k in ('bytes', 'sha256', 'device_us')})
        previous = next((r for r in reversed(observations[:-1]) if r['status'] == 'observed'), None)
        row['changed_from_previous'] = (
            previous['sha256'] != row['sha256'] if previous is not None else None
        )
        row['device_clock_regressed'] = (
            row['device_us'] < previous['device_us'] if previous is not None else None
        )
        return row
    except Exception as exc:
        row.update(status='error', error=type(exc).__name__)
        raise
