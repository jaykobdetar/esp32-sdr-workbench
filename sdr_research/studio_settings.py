"""Strict, portable settings documents. Parsing never accesses hardware or files."""

import json

from .lab_session import validate_receiver, validate_transmitter

FIELDS = {
    'schema_version': {'type': 'integer', 'enum': [1]},
    'task': {'type': 'string', 'enum': ['listen', 'test', 'compare']},
    'frequency_mhz': {'type': 'integer', 'minimum': 2402, 'maximum': 2480},
    'duration_s': {'type': ['integer', 'null'], 'enum': [None, 5, 10, 30, 60]},
    'save_captures': {'type': 'boolean'},
    'receiver_mode': {'type': 'string', 'enum': ['raw', 'DET1', 'DETPIPE1', 'DSTREAMIQ']},
    'sample_rate_hz': {'type': 'integer', 'enum': [16000000, 40000000, 80000000]},
    'gain': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 81},
    'bandwidth_mhz': {'type': 'integer', 'minimum': 0, 'maximum': 67},
    'samples': {'type': 'integer', 'minimum': 256, 'maximum': 16380},
    'detector_window_ms': {'type': 'integer', 'minimum': 1, 'maximum': 5000},
    'ratio_milli': {'type': 'integer', 'minimum': 1000, 'maximum': 1000000, 'multipleOf': 10},
    'background_policy': {'type': ['integer', 'null'], 'enum': [None, 1, 2]},
    'tx_power_dbm': {'type': 'integer', 'enum': [-40, -20, -16, -12, -8, -4, 0]},
    'tx_mode_mbps': {'type': 'integer', 'enum': [1, 2]},
    'tx_length_bytes': {'type': 'integer', 'minimum': 8, 'maximum': 252},
    'tx_interval_us': {'type': 'integer', 'minimum': 1000, 'maximum': 1000000},
}


def schema():
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': list(FIELDS),
        'properties': FIELDS,
    }


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate key: {key}')
        result[key] = value
    return result


def parse_settings(text):
    if len(text) > 16000:
        raise ValueError('Settings exceed the 16,000-character limit.')
    try:
        doc = json.loads(text, object_pairs_hook=_pairs)
    except (ValueError, RecursionError) as error:
        raise ValueError(f'Invalid JSON: {error}') from None
    if not isinstance(doc, dict):
        raise ValueError('Paste one JSON object, without Markdown fences.')
    missing = set(FIELDS) - set(doc)
    extra = set(doc) - set(FIELDS)
    if missing or extra:
        raise ValueError(
            f'Missing keys: {", ".join(sorted(missing)) or "none"}. Unknown keys: {", ".join(sorted(extra)) or "none"}.'
        )
    for key, spec in FIELDS.items():
        value = doc[key]
        types = spec['type'] if isinstance(spec['type'], list) else [spec['type']]
        kind = {int: 'integer', str: 'string', bool: 'boolean', type(None): 'null'}.get(type(value))
        if kind not in types:
            raise ValueError(f'{key}: expected {" or ".join(types)}.')
        if 'enum' in spec and value not in spec['enum']:
            raise ValueError(f'{key}: choose from {spec["enum"]}.')
        if value is not None and kind == 'integer':
            if 'minimum' in spec and not spec['minimum'] <= value <= spec['maximum']:
                raise ValueError(f'{key}: must be {spec["minimum"]}..{spec["maximum"]}.')
            if value % spec.get('multipleOf', 1):
                raise ValueError(f'{key}: must be a multiple of {spec["multipleOf"]}.')
    if doc['task'] == 'test' and doc['duration_s'] is None:
        raise ValueError('Transmitter tests require a bounded duration, not null.')
    validate_receiver(
        dict(
            mode=doc['receiver_mode'],
            frequency_mhz=doc['frequency_mhz'],
            rate_hz=doc['sample_rate_hz'],
            gain=doc['gain'],
            bandwidth_mhz=doc['bandwidth_mhz'],
            samples=doc['samples'],
            det_ms=doc['detector_window_ms'],
            ratio_milli=doc['ratio_milli'],
            background_policy=doc['background_policy'],
        ),
        False,
    )
    validate_transmitter(
        dict(
            frequency_mhz=doc['frequency_mhz'],
            power_dbm=doc['tx_power_dbm'],
            mode_mbps=doc['tx_mode_mbps'],
            length=doc['tx_length_bytes'],
            interval_us=doc['tx_interval_us'],
        ),
        '0000000000000000',
    )
    return doc


def llm_prompt(current):
    return (
        """Generate an RF Studio settings JSON document for the goal I will describe below. Return ONLY one JSON object, all required keys, no Markdown or commands. Use the schema and current settings below. Do not invent unsupported features.

Hardware: original ESP32 burst I/Q receivers and nRF52840 proprietary GFSK test transmitter. Shared frequency, independently controlled receivers, not synchronized. No continuous-coverage or packet-recall guarantee. Use low power initially. Respect applicable radio rules. No credentials or device identifiers are needed.

duration_s null runs until manually stopped and is receive-only; test requires 5/10/30/60 seconds. save_captures false means no session directory, summary or raw capture files are written.
Meaning: task listen/compare requests no transmission; compare needs at least two selected receivers. test needs an explicitly selected physical transmitter. Import NEVER starts hardware, selects transmitters, changes device paths, or changes the local recording folder. The user must review and press Start separately. Simulation remains local and overrides receiver acquisition to raw.
receiver_mode raw favors visible I/Q with readout gaps; DET1/DETPIPE1 retain candidate events, not decoded packets. gain null means hardware AGC; integers mean manual gain. AGC energies are not comparable across gain changes. ratio_milli=4000 means 4.00 times background (10-unit steps). background_policy null selects the firmware default policy; 1 legacy, 2 adaptive. Samples are fixed at 10 bits; candidate count is fixed at one. Firmware capability validation still applies at connection time.
DSTREAMIQ is experimental persistent detector telemetry plus sparse full I/Q, not continuous IQ. It requires compatible firmware, 16MS/s,16380 samples,10bits; receiver streams start independently with no shared-clock calibration. Snapshots approximately every5seconds; commands restart every600seconds with gaps. No automatic firmware flashing. Detector window is ignored in this mode.
Transmitter uses known payload/sequence numbers, no hopping, no custom payload. tx_interval_us must be >= floor((tx_length_bytes+10)*8/tx_mode_mbps)+300. The app sends only a finite-duration session, checks STOP and restores original transmitter packet configuration. No unbounded carrier or continuous transmission settings.

JSON schema:
"""
        + json.dumps(schema(), indent=2)
        + '\n\nCurrent portable settings:\n'
        + json.dumps(current, indent=2)
        + '\n\nMy goal: [describe what you want to observe or test here]\n'
    )
