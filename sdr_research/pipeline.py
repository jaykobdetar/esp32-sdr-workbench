"""Experimental DETPIPE1 client. No flashing; caller owns configured Radio."""
from datetime import datetime, timezone
import json
import re
import time
import zlib
from sdr_research.protocol import Capture, ProtocolError, RATES, decode_iq


def run_pipeline(radio, milliseconds=2000, samples=16380, rate_hz=16000000,
                 ratio_milli=4000, retain=True, kernel=0, optimized=False, copy_option=None):
    if any(type(v) is not int for v in (milliseconds, samples, rate_hz, ratio_milli)):
        raise ValueError('Integer request fields required')
    if not 1 <= milliseconds <= 5000 or not 256 <= samples <= 16380 or not 1000 <= ratio_milli <= 1000000:
        raise ValueError('Invalid pipeline request')
    if rate_hz not in (16000000, 40000000, 80000000) or type(retain) is not bool:
        raise ValueError('Invalid rate or retention flag')
    if type(kernel) is not int or kernel not in (0, 3):
        raise ValueError('Pipeline kernel must be 0 or 3')
    if type(optimized) is not bool: raise ValueError('optimized must be bool')
    if optimized and kernel != 3: raise ValueError('Optimized mode requires kernel 3')
    if copy_option is not None and (type(copy_option) is not int or copy_option not in (0, 1)):
        raise ValueError('copy_option must be None, 0 or 1')
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
    stamp = datetime.now(timezone.utc).isoformat()
    start = time.monotonic_ns()
    command = f'DETPIPE1 {milliseconds} {samples} {RATES[rate_hz]} {ratio_milli} {int(retain)}'
    try:
        begin = radio.command(command)
        if begin != f'DETPIPE1 BEGIN {milliseconds} {samples} {RATES[rate_hz]} {ratio_milli} {int(retain)} {frequency}':
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
            summary = json.loads(line[len('DETPIPE1 END '):])
            break
        fields = ['version', 'kernel', 'status', 'captures', 'processed_captures', 'detections',
                  'background_adc2', 'best_ratio_milli', 'wall_elapsed_us',
                  'completion_observed_us', 'acquire_call_us_includes_overlap',
                  'energy_compute_us', 'copy_us', 'decision_us', 'retention_copy_us',
                  'retained_samples', 'frequency_mhz', 'total_samples',
                  'analyzed_samples', 'sample_rate_hz', 'errors', 'warmup_captures']
        if not isinstance(summary, dict) or any(type(summary.get(k)) is not int or summary[k] < 0 for k in fields):
            raise ProtocolError('Invalid pipeline summary types/ranges')
        for selector, field in [('ACQOPT', 'acquisition_option'), ('CLEAROPT', 'clear_option')]:
            policy = policies[selector]
            if policy['supported'] and (type(summary.get(field)) is not int or
                                        summary[field] != policy['returned']):
                raise ProtocolError(f'Pipeline {field} summary mismatch or missing field')
        if copy_option is not None:
            expected_fused = int(copy_option == 1 and samples == 16380)
            if (type(summary.get('copy_option')) is not int or summary['copy_option'] != copy_option or
                    type(summary.get('fused_active')) is not int or summary['fused_active'] != expected_fused):
                raise ProtocolError('Pipeline copy_option/fused_active summary mismatch or missing field')
        count = summary['captures']
        if summary['version'] != 1 or summary['status'] not in (0, 1, 2):
            raise ProtocolError('Unsupported pipeline summary version/status')
        if summary['kernel'] != kernel:
            raise ProtocolError('Pipeline kernel mismatch')
        if summary['frequency_mhz'] != frequency or summary['sample_rate_hz'] != rate_hz:
            raise ProtocolError('Pipeline settings mismatch')
        if summary['processed_captures'] != count or summary['total_samples'] != count * samples or summary['analyzed_samples'] != count * (samples // 64) * 64:
            raise ProtocolError('Inconsistent pipeline counters')
        if summary['warmup_captures'] != min(count, 16) or summary['detections'] > max(0, count - 16):
            raise ProtocolError('Inconsistent pipeline warmup/detections')
        if not summary['wall_elapsed_us'] or summary['retained_samples'] not in (0, samples) or (not retain and summary['retained_samples']):
            raise ProtocolError('Invalid pipeline timing/retention')
        if summary['retained_samples'] and not summary['detections']:
            raise ProtocolError('Retained pipeline IQ without candidate')
        if summary['errors'] != int(summary['status'] != 0) or (errors and summary['status'] == 0):
            raise ProtocolError('Pipeline error status mismatch')
        summary['errors_received'] = errors
        summary['host_request_timestamp'] = stamp
        summary['host_run_elapsed_us'] = (time.monotonic_ns() - start) / 1000
        capture = None
        if summary['status'] == 0 and summary['retained_samples']:
            line = radio.command('DETPIPEGET')
            header = re.fullmatch(r'DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)', line)
            if not header or int(header[1]) != samples:
                raise ProtocolError('Invalid retained pipeline header')
            payload = radio._read((samples * 20 + 7) // 8)
            if zlib.crc32(payload) != int(header[2], 16):
                raise ProtocolError('Retained pipeline CRC mismatch')
            capture = Capture(decode_iq(payload, samples, 10), rate_hz, frequency * 1000000,
                              stamp, start, time.monotonic_ns(), int(header[3]), 10, True,
                              {'detector_summary': summary, 'device': radio.info,
                               'timestamp_reference': 'pipeline run start, not RF arrival',
                               'firmware_capture_us_semantics': 'trigger to observed completion, may include overlapped prior processing; not RF duration'})
        summary['copy_policy'] = copy_policy
        summary['acquisition_policies'] = policies
        summary['kernel_requested'] = kernel
        summary['kernel_returned'] = summary['kernel']
        summary['host_total_elapsed_us'] = (time.monotonic_ns() - total_start) / 1000
        for label, duration in [('local', summary['wall_elapsed_us']), ('host', summary['host_total_elapsed_us'])]:
            summary[f'nominal_{label}_rf_duty_percent'] = 100 * summary['total_samples'] / rate_hz / (duration / 1e6)
            summary[f'nominal_{label}_decision_duty_percent'] = 100 * max(0, count - 16) * (samples // 64) * 64 / rate_hz / (duration / 1e6)
        summary['nominal_rf_duty_percent'] = summary['nominal_local_rf_duty_percent']
        summary['nominal_decision_duty_percent'] = summary['nominal_local_decision_duty_percent']
        summary['nominal_analyzed_duty_percent'] = 100 * summary['analyzed_samples'] / rate_hz / (summary['wall_elapsed_us']/1e6)
        summary['retained_crc_valid'] = capture is not None
        summary['timing_note'] = 'Acquisition includes overlapped energy; do not sum it with energy compute time. RF aperture is N/fs, never observed completion latency.'
        return summary, capture
    except Exception:
        radio.failed = True
        raise


def select_acquisition_policy(radio, optimized=False):
    """Never probe absent legacy capabilities or silently accept sticky policies."""
    caps = set(radio.info.get('caps', []))
    requested = {'ACQOPT': 3 if optimized else 0, 'CLEAROPT': 1 if optimized else 0}
    if optimized and not set(requested).issubset(caps):
        raise ProtocolError('Optimized pipeline requires ACQOPT and CLEAROPT capabilities; nothing flashed')
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


def select_copy_policy(radio, copy_option):
    """None deliberately preserves legacy experiment behavior without probing."""
    policy = {'requested': copy_option, 'returned': None,
              'supported': 'PIPECOPY' in radio.info.get('caps', [])}
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
