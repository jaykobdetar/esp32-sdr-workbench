"""Experimental DETPIPE1 client. No flashing; caller owns configured Radio."""

import json
import re
import time
import zlib
from datetime import datetime, timezone
from typing import Any

from sdr_research.protocol import RATES, Capture, ProtocolError, Radio, decode_iq

from .summary_validation import retained_trigger_metadata, validate_run_summary


def run_pipeline(
    radio: Radio,
    milliseconds: int = 2000,
    samples: int = 16380,
    rate_hz: int = 16000000,
    ratio_milli: int = 4000,
    retain: bool = True,
    kernel: int = 0,
    optimized: bool = False,
    copy_option: int | None = None,
    candidate_count: int = 1,
) -> tuple[dict[str, Any], Capture | None]:
    if any(type(v) is not int for v in (milliseconds, samples, rate_hz, ratio_milli)):
        raise ValueError('Integer request fields required')
    if (
        not 1 <= milliseconds <= 5000
        or not 256 <= samples <= 16380
        or not 1000 <= ratio_milli <= 1000000
    ):
        raise ValueError('Invalid pipeline request')
    if rate_hz not in (16000000, 40000000, 80000000) or type(retain) is not bool:
        raise ValueError('Invalid rate or retention flag')
    if type(kernel) is not int or kernel not in (0, 3):
        raise ValueError('Pipeline kernel must be 0 or 3')
    if type(optimized) is not bool:
        raise ValueError('optimized must be bool')
    if optimized and kernel != 3:
        raise ValueError('Optimized mode requires kernel 3')
    if copy_option is not None and (type(copy_option) is not int or copy_option not in (0, 1)):
        raise ValueError('copy_option must be None, 0 or 1')
    if type(candidate_count) is not int or candidate_count not in (1, 3):
        raise ValueError('candidate_count must be 1 or 3')
    frequency = radio.settings['frequency_mhz']
    total_start = time.monotonic_ns()
    copy_policy = select_copy_policy(radio, copy_option)
    policies = select_acquisition_policy(radio, optimized)
    if radio.command(f'PIPEKERNEL {kernel}') != f'PIPEKERNEL {kernel}':
        raise ProtocolError('Pipeline kernel selection failed')
    if optimized and radio.command('PIPEKERNEL?') != f'PIPEKERNEL {kernel}':
        raise ProtocolError('Pipeline kernel readback failed')
    if radio.command('DETPIPEINFO?') != 'DETPIPEINFO 1 5000 16 64':
        raise ProtocolError('Unsupported pipeline firmware')
    if candidate_count == 3:
        try:
            if (
                radio.command('PIPEKEEP 3') != 'PIPEKEEP 3'
                or radio.command('PIPEKEEP?') != 'PIPEKEEP 3'
            ):
                raise ProtocolError('PIPEKEEP selection/readback failed')
        except Exception:
            radio.failed = True
            raise
    stamp = datetime.now(timezone.utc).isoformat()
    start = time.monotonic_ns()
    command = f'DETPIPE1 {milliseconds} {samples} {RATES[rate_hz]} {ratio_milli} {int(retain)}'
    try:
        begin = radio.command(command)
        if (
            begin
            != f'DETPIPE1 BEGIN {milliseconds} {samples} {RATES[rate_hz]} {ratio_milli} {int(retain)} {frequency}'
        ):
            raise ProtocolError('Invalid pipeline begin')
        deadline = time.monotonic() + milliseconds / 1000 + 5
        errors = []
        while True:
            line = radio._line(deadline)
            if line.startswith('ERR '):
                errors.append(line)
                continue
            if not line.startswith('DETPIPE1 END '):
                raise ProtocolError('Invalid pipeline end')
            summary = json.loads(line[len('DETPIPE1 END ') :])
            break
        summary = validate_run_summary(
            summary,
            samples=samples,
            rate_hz=rate_hz,
            frequency_mhz=frequency,
            retain=retain,
            pipeline=True,
            kernel=kernel,
            errors_received=bool(errors),
            candidate_count=candidate_count,
        )
        for selector, field in [('ACQOPT', 'acquisition_option'), ('CLEAROPT', 'clear_option')]:
            policy = policies[selector]
            if policy['supported'] and (
                type(summary.get(field)) is not int or summary[field] != policy['returned']
            ):
                raise ProtocolError(f'Pipeline {field} summary mismatch or missing field')
        if copy_option is not None:
            expected_fused = int(copy_option == 1 and samples == 16380)
            if (
                type(summary.get('copy_option')) is not int
                or summary['copy_option'] != copy_option
                or type(summary.get('fused_active')) is not int
                or summary['fused_active'] != expected_fused
            ):
                raise ProtocolError(
                    'Pipeline copy_option/fused_active summary mismatch or missing field'
                )
        count = summary['captures']
        summary['errors_received'] = errors
        summary['host_request_timestamp'] = stamp
        summary['host_run_elapsed_us'] = (time.monotonic_ns() - start) / 1000
        capture = None
        if summary['status'] == 0 and summary['retained_samples']:
            line = radio.command('DETPIPEGET')
            header = re.fullmatch(r'DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)', line)
            retained_samples = summary['retained_samples']
            if not header or int(header[1]) != retained_samples:
                raise ProtocolError('Invalid retained pipeline header')
            payload = radio._read((retained_samples * 20 + 7) // 8)
            if zlib.crc32(payload) != int(header[2], 16):
                raise ProtocolError('Retained pipeline CRC mismatch')
            capture = Capture(
                decode_iq(payload, retained_samples, 10),
                rate_hz,
                frequency * 1000000,
                stamp,
                start,
                time.monotonic_ns(),
                int(header[3]),
                10,
                True,
                {
                    'detector_summary': summary,
                    **retained_trigger_metadata(summary),
                    'device': radio.info,
                    'timestamp_reference': 'pipeline run start, not RF arrival',
                    'firmware_capture_us_semantics': 'trigger to observed completion, may include overlapped prior processing; not RF duration',
                },
            )
        if capture is not None and candidate_count == 3:
            strongest = next(
                c
                for c in summary['retained_candidates']
                if c['generation'] == summary['retained_generation']
            )
            if capture.firmware_capture_us != strongest['capture_us']:
                raise ProtocolError('Strongest candidate capture timing mismatch')
            _set_candidate_metadata(capture, strongest)
        summary['copy_policy'] = copy_policy
        summary['acquisition_policies'] = policies
        summary['kernel_requested'] = kernel
        summary['kernel_returned'] = summary['kernel']
        summary['host_total_elapsed_us'] = (time.monotonic_ns() - total_start) / 1000
        for label, duration in [
            ('local', summary['wall_elapsed_us']),
            ('host', summary['host_total_elapsed_us']),
        ]:
            summary[f'nominal_{label}_rf_duty_percent'] = (
                100 * summary['total_samples'] / rate_hz / (duration / 1e6)
            )
            summary[f'nominal_{label}_decision_duty_percent'] = (
                100 * max(0, count - 16) * (samples // 64) * 64 / rate_hz / (duration / 1e6)
            )
        summary['nominal_rf_duty_percent'] = summary['nominal_local_rf_duty_percent']
        summary['nominal_decision_duty_percent'] = summary['nominal_local_decision_duty_percent']
        summary['nominal_analyzed_duty_percent'] = (
            100 * summary['analyzed_samples'] / rate_hz / (summary['wall_elapsed_us'] / 1e6)
        )
        summary['retained_crc_valid'] = capture is not None
        summary['timing_note'] = (
            'Acquisition includes overlapped energy; do not sum it with energy compute time. RF aperture is N/fs, never observed completion latency.'
        )
        return summary, capture
    except Exception:
        radio.failed = True
        raise


def select_acquisition_policy(
    radio: Radio, optimized: bool = False
) -> dict[str, dict[str, int | bool | None]]:
    """Never probe absent legacy capabilities or silently accept sticky policies."""
    caps = set(radio.info.get('caps', []))
    requested = {'ACQOPT': 3 if optimized else 0, 'CLEAROPT': 1 if optimized else 0}
    if optimized and not set(requested).issubset(caps):
        raise ProtocolError(
            'Optimized pipeline requires ACQOPT and CLEAROPT capabilities; nothing flashed'
        )
    policies = {}
    for name, value in requested.items():
        if name not in caps:
            policies[name] = {'requested': None, 'returned': None, 'supported': False}
            continue
        try:
            if radio.command(f'{name} {value}') != 'OK':
                raise ProtocolError(f'{name} selection failed')
            response = radio.command(f'{name}?')
            if response != f'{name} {value}':
                raise ProtocolError(f'{name} readback mismatch: {response}')
            policies[name] = {'requested': value, 'returned': value, 'supported': True}
        except Exception:
            radio.failed = True
            raise
    return policies


def select_copy_policy(radio: Radio, copy_option: int | None) -> dict[str, int | bool | None]:
    """None deliberately preserves legacy experiment behavior without probing."""
    policy = {
        'requested': copy_option,
        'returned': None,
        'supported': 'PIPECOPY' in radio.info.get('caps', []),
    }
    if copy_option is None:
        return policy
    if not policy['supported']:
        raise ProtocolError('PIPECOPY capability required for explicit copy policy')
    try:
        expected = f'PIPECOPY {copy_option}'
        if radio.command(expected) != expected:
            raise ProtocolError('PIPECOPY selection failed')
        if radio.command('PIPECOPY?') != expected:
            raise ProtocolError('PIPECOPY readback mismatch')
        policy['returned'] = copy_option
        return policy
    except Exception:
        radio.failed = True
        raise


def run_pipeline_candidates(
    radio: Radio,
    milliseconds: int = 2000,
    samples: int = 16380,
    rate_hz: int = 16000000,
    ratio_milli: int = 4000,
    retain: bool = True,
    kernel: int = 0,
    optimized: bool = False,
    copy_option: int | None = None,
) -> tuple[dict[str, Any], list[Capture]]:
    """Opt in to three bounded crops; return strongest first, then remaining slots.

    Requires PIPEKEEP firmware. No fallback silently changes retention policy.
    Crop trigger times refer to the original acquisition, with offset_samples
    giving nominal crop placement, not a hardware timestamp for each sample.
    """
    total_start = time.monotonic_ns()
    summary, strongest = run_pipeline(
        radio,
        milliseconds,
        samples,
        rate_hz,
        ratio_milli,
        retain,
        kernel,
        optimized,
        copy_option,
        candidate_count=3,
    )
    if strongest is None:
        summary['retained_event_count'] = 0
        return summary, []
    candidates = summary['retained_candidates']
    best = next(c for c in candidates if c['generation'] == summary['retained_generation'])
    _set_candidate_metadata(strongest, best)
    captures = [strongest]
    try:
        for item in candidates:
            if item['slot'] == best['slot']:
                continue
            line = radio.command(f'DETPIPEGET {item["slot"]}')
            header = re.fullmatch(r'DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)', line)
            if (
                not header
                or int(header[1]) != item['samples']
                or int(header[3]) != item['capture_us']
            ):
                raise ProtocolError('Invalid retained candidate header')
            payload = radio._read((item['samples'] * 20 + 7) // 8)
            if zlib.crc32(payload) != int(header[2], 16):
                raise ProtocolError('Retained candidate CRC mismatch')
            capture = Capture(
                decode_iq(payload, item['samples'], 10),
                rate_hz,
                strongest.frequency_hz,
                strongest.timestamp,
                strongest.monotonic_start_ns,
                time.monotonic_ns(),
                int(header[3]),
                10,
                True,
                dict(strongest.metadata),
            )
            _set_candidate_metadata(capture, item)
            captures.append(capture)
    except Exception:
        radio.failed = True
        raise
    summary['host_total_elapsed_us'] = (time.monotonic_ns() - total_start) / 1000
    summary['nominal_host_rf_duty_percent'] = (
        100 * summary['total_samples'] / rate_hz / (summary['host_total_elapsed_us'] / 1e6)
    )
    summary['nominal_host_decision_duty_percent'] = (
        100
        * max(0, summary['captures'] - 16)
        * (samples // 64)
        * 64
        / rate_hz
        / (summary['host_total_elapsed_us'] / 1e6)
    )
    summary['retained_event_count'] = len(captures)
    return summary, captures


def _set_candidate_metadata(capture: Capture, candidate: dict[str, int]) -> None:
    capture.metadata.update(
        retained_candidate=dict(candidate),
        trigger_device_us=candidate['trigger_device_us'],
        retained_generation=candidate['generation'],
        crop_offset_samples=candidate['offset_samples'],
        crop_timing_note=(
            'trigger_device_us is original acquisition trigger uptime; crop offset/fs '
            'is nominal sample timing, not calibrated RF arrival'
        ),
    )
