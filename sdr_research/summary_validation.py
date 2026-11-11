"""Shared validation for finite detector summaries, before IQ retrieval.

Only documented wire fields are required. Additional versioned fields survive
validation so old clients can retain telemetry from newer firmware.
"""

from typing import Any

from .protocol import ProtocolError

_COMMON_INTEGERS = (
    'version',
    'status',
    'captures',
    'detections',
    'warmup_captures',
    'errors',
    'wall_elapsed_us',
    'total_samples',
    'analyzed_samples',
    'retained_samples',
    'sample_rate_hz',
    'frequency_mhz',
)
_PIPELINE_INTEGERS = (
    'kernel',
    'processed_captures',
    'background_adc2',
    'best_ratio_milli',
    'completion_observed_us',
    'acquire_call_us_includes_overlap',
    'energy_compute_us',
    'copy_us',
    'decision_us',
    'retention_copy_us',
)


def validate_run_summary(
    summary: object,
    *,
    samples: int,
    rate_hz: int,
    frequency_mhz: int,
    retain: bool,
    pipeline: bool = False,
    kernel: int = 0,
    errors_received: bool = False,
    candidate_count: int = 1,
) -> dict[str, Any]:
    """Validate common counters and mode-specific fields without modifying input.

    JSON booleans must not pass as integer counters. A failed run may report
    completed captures, but its status and error count must agree. The caller
    remains responsible for policy readbacks and retained-payload CRC checks.
    """
    mode = 'pipeline' if pipeline else 'detector'
    fields = _COMMON_INTEGERS + (_PIPELINE_INTEGERS if pipeline else ())
    if not isinstance(summary, dict) or any(
        type(summary.get(key)) is not int or summary[key] < 0 for key in fields
    ):
        raise ProtocolError(f'Invalid {mode} summary types/ranges')
    if summary['version'] != 1:
        raise ProtocolError(f'Unsupported {mode} summary version')
    statuses = (0, 1, 2) if pipeline else (0, 1)
    if summary['status'] not in statuses or summary['errors'] != int(summary['status'] != 0):
        raise ProtocolError(f'Inconsistent {mode} status')
    # DET1 historically permits informational ERR lines with a successful END;
    # retain its compatibility contract while enforcing the pipeline contract.
    if pipeline and errors_received and summary['status'] == 0:
        raise ProtocolError('Pipeline error status mismatch')
    count = summary['captures']
    if (
        summary['total_samples'] != count * samples
        or summary['analyzed_samples'] != count * (samples // 64) * 64
        or (pipeline and summary['processed_captures'] != count)
    ):
        raise ProtocolError(f'Inconsistent {mode} counters')
    if summary['warmup_captures'] != min(count, 16) or summary['detections'] > max(0, count - 16):
        raise ProtocolError(f'Inconsistent {mode} warmup/detections')
    if summary['sample_rate_hz'] != rate_hz or summary['frequency_mhz'] != frequency_mhz:
        raise ProtocolError(f'{mode.capitalize()} settings mismatch')
    retained_size = min(samples // 8 * 8, 5120) if candidate_count == 3 else samples
    if not summary['wall_elapsed_us'] or summary['retained_samples'] not in (0, retained_size):
        raise ProtocolError(f'Invalid {mode} timing/retention')
    if summary['retained_samples'] and (not retain or not summary['detections']):
        raise ProtocolError(f'Unexpected retained {mode} event')
    if pipeline and summary['kernel'] != kernel:
        raise ProtocolError('Pipeline kernel mismatch')
    validate_policy_telemetry(summary)
    if candidate_count == 3:
        validate_candidates(summary, samples=samples, crop_samples=retained_size)
    return summary


def validate_policy_telemetry(summary: dict[str, Any]) -> None:
    """Policy 2 adds an all-or-nothing gain/timing telemetry contract.

    Device microseconds are unsynchronized monotonic uptime, sampled immediately
    before the dump-trigger register write. They are neither UTC nor calibrated
    RF arrival times. Only successful captures contribute first/last timestamps;
    retained_generation is one-based and zero when no IQ was retained.
    Historical firmware without background_policy does not require these fields.
    """
    if 'background_policy' not in summary:
        return
    limits = {
        'background_policy': 2,
        'background_q16': 2**35,
        'background_adc2': 2**19,
        'gain_register_start': 2**32 - 1,
        'gain_register_end': 2**32 - 1,
        'hardware_agc': 1,
        'gain_index_requested': 2**32 - 1,
        'first_trigger_device_us': 2**64 - 1,
        'last_trigger_device_us': 2**64 - 1,
        'retained_trigger_device_us': 2**64 - 1,
        'retained_generation': 2**32 - 1,
    }
    for key, maximum in limits.items():
        if type(summary.get(key)) is not int or not 0 <= summary[key] <= maximum:
            raise ProtocolError(f'Invalid detector telemetry: {key}')
    if summary['background_policy'] != 2:
        raise ProtocolError('Unsupported detector background_policy')
    if (
        not summary['background_q16']
        or summary['background_adc2'] != summary['background_q16'] // 65536
    ):
        raise ProtocolError('Inconsistent detector background_q16')
    first = summary['first_trigger_device_us']
    last = summary['last_trigger_device_us']
    retained = summary['retained_trigger_device_us']
    generation = summary['retained_generation']
    count = summary['captures']
    if count == 0:
        if first or last:
            raise ProtocolError('Trigger timestamps without captures')
    elif not first or last < first or last - first > summary['wall_elapsed_us']:
        raise ProtocolError('Invalid detector trigger timestamp range')
    if count == 1 and first != last:
        raise ProtocolError('Inconsistent single-capture trigger timestamps')
    if summary['retained_samples']:
        if not 16 < generation <= count or not first <= retained <= last:
            raise ProtocolError('Invalid retained trigger timestamp/generation')
    elif retained or generation:
        raise ProtocolError('Retained trigger telemetry without retained IQ')


def retained_trigger_metadata(summary: dict[str, Any]) -> dict[str, Any]:
    """Return extra device-timing metadata without relabeling host UTC timestamps."""
    if summary.get('background_policy') != 2 or not summary['retained_samples']:
        return {}
    return {
        'trigger_device_us': summary['retained_trigger_device_us'],
        'retained_generation': summary['retained_generation'],
        'trigger_timestamp_reference': (
            'unsynchronized device monotonic uptime in microseconds, sampled immediately '
            'before dump-trigger register write; not UTC or calibrated RF arrival'
        ),
    }


def validate_candidates(summary: dict[str, Any], *, samples: int, crop_samples: int) -> None:
    """Check explicitly requested three-crop telemetry before reading any payload."""
    if summary.get('background_policy') != 2:
        raise ProtocolError('Candidate retention requires policy 2 telemetry')
    candidates = summary.get('retained_candidates')
    if type(summary.get('retention_capacity')) is not int or summary['retention_capacity'] != 3:
        raise ProtocolError('Pipeline retention_capacity mismatch')
    if not isinstance(candidates, list) or len(candidates) > min(3, summary['detections']):
        raise ProtocolError('Invalid retained_candidates list')
    if bool(candidates) != bool(summary['retained_samples']):
        raise ProtocolError('Retained candidate count mismatch')
    slots, generations = set(), set()
    for item in candidates:
        if not isinstance(item, dict):
            raise ProtocolError('Invalid candidate descriptor')
        for key in (
            'slot',
            'samples',
            'offset_samples',
            'generation',
            'trigger_device_us',
            'score_milli',
            'capture_us',
        ):
            if type(item.get(key)) is not int or item[key] < 0:
                raise ProtocolError(f'Invalid candidate {key}')
        if item['slot'] >= 3 or item['slot'] in slots:
            raise ProtocolError('Invalid or duplicate candidate slot')
        if not 16 < item['generation'] <= summary['captures'] or item['generation'] in generations:
            raise ProtocolError('Invalid or duplicate candidate generation')
        if (
            item['samples'] != crop_samples
            or item['offset_samples'] + crop_samples > samples
            or item['offset_samples'] % 8
            or item['score_milli'] > 2**32 - 1
        ):
            raise ProtocolError('Invalid candidate crop bounds')
        if (
            not summary['first_trigger_device_us']
            <= item['trigger_device_us']
            <= summary['last_trigger_device_us']
        ):
            raise ProtocolError('Invalid candidate trigger timestamp')
        slots.add(item['slot'])
        generations.add(item['generation'])
    if candidates:
        best = [c for c in candidates if c['generation'] == summary['retained_generation']]
        if (
            len(best) != 1
            or best[0]['trigger_device_us'] != summary['retained_trigger_device_us']
            or best[0]['score_milli'] != max(c['score_milli'] for c in candidates)
            or best[0]['score_milli'] != summary['best_ratio_milli']
        ):
            raise ProtocolError('Inconsistent strongest candidate metadata')
