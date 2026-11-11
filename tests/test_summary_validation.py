"""Common detector/pipeline wire-contract checks without a serial device."""

import copy

import pytest

from sdr_research.protocol import ProtocolError
from sdr_research.summary_validation import validate_run_summary


def summary(pipeline=False):
    result = {
        'version': 1,
        'status': 0,
        'captures': 20,
        'detections': 2,
        'warmup_captures': 16,
        'errors': 0,
        'wall_elapsed_us': 100,
        'total_samples': 20 * 260,
        'analyzed_samples': 20 * 256,
        'retained_samples': 260,
        'sample_rate_hz': 16000000,
        'frequency_mhz': 2440,
    }
    if pipeline:
        result.update(
            {
                'kernel': 3,
                'processed_captures': 20,
                'background_adc2': 1,
                'best_ratio_milli': 4001,
                'completion_observed_us': 1,
                'acquire_call_us_includes_overlap': 1,
                'energy_compute_us': 1,
                'copy_us': 1,
                'decision_us': 1,
                'retention_copy_us': 1,
            }
        )
    return result


def validate(value, pipeline=False, retain=True):
    return validate_run_summary(
        value,
        samples=260,
        rate_hz=16000000,
        frequency_mhz=2440,
        retain=retain,
        pipeline=pipeline,
        kernel=3,
    )


@pytest.mark.parametrize('pipeline', [False, True])
def test_preserves_extension_fields_and_does_not_mutate(pipeline):
    value = summary(pipeline)
    value['future_telemetry'] = {'measurement': 123}
    before = copy.deepcopy(value)
    assert validate(value, pipeline) is value
    assert value == before


@pytest.mark.parametrize('pipeline', [False, True])
@pytest.mark.parametrize('bad', [None, [], 1, True, 'summary'])
def test_rejects_non_objects(pipeline, bad):
    with pytest.raises(ProtocolError):
        validate(bad, pipeline)


@pytest.mark.parametrize('pipeline', [False, True])
@pytest.mark.parametrize('bad', [True, False, -1, 1.0, None, '1'])
def test_rejects_non_integer_fields(pipeline, bad):
    for field in summary(pipeline):
        value = summary(pipeline)
        value[field] = bad
        with pytest.raises(ProtocolError):
            validate(value, pipeline)


@pytest.mark.parametrize('pipeline', [False, True])
@pytest.mark.parametrize(
    'field,bad',
    [
        ('version', 2),
        ('status', 3),
        ('errors', 1),
        ('captures', 21),
        ('warmup_captures', 15),
        ('detections', 5),
        ('total_samples', 0),
        ('analyzed_samples', 5200),
        ('wall_elapsed_us', 0),
        ('retained_samples', 256),
        ('sample_rate_hz', 40000000),
        ('frequency_mhz', 2400),
    ],
)
def test_rejects_inconsistent_counters(pipeline, field, bad):
    value = summary(pipeline)
    value[field] = bad
    with pytest.raises(ProtocolError):
        validate(value, pipeline)


@pytest.mark.parametrize('pipeline', [False, True])
def test_retention_requires_permission_and_candidate(pipeline):
    value = summary(pipeline)
    with pytest.raises(ProtocolError):
        validate(value, pipeline, retain=False)
    value['detections'] = 0
    with pytest.raises(ProtocolError):
        validate(value, pipeline)
    value['retained_samples'] = 0
    validate(value, pipeline, retain=False)


@pytest.mark.parametrize('pipeline', [False, True])
def test_short_failed_run(pipeline):
    value = summary(pipeline)
    value.update(
        status=1,
        errors=1,
        captures=4,
        warmup_captures=4,
        detections=0,
        retained_samples=0,
        total_samples=1040,
        analyzed_samples=1024,
    )
    if pipeline:
        value['processed_captures'] = 4
    validate(value, pipeline)


def telemetry():
    return dict(
        background_policy=2,
        background_q16=65536,
        background_adc2=1,
        gain_register_start=0xFFFFFFFF,
        gain_register_end=0,
        hardware_agc=1,
        gain_index_requested=40,
        first_trigger_device_us=1000,
        last_trigger_device_us=1050,
        retained_trigger_device_us=1040,
        retained_generation=18,
    )


@pytest.mark.parametrize('pipeline', [False, True])
def test_policy2_metadata(pipeline):
    from sdr_research.summary_validation import retained_trigger_metadata

    value = summary(pipeline)
    value.update(telemetry())
    validate(value, pipeline)
    metadata = retained_trigger_metadata(value)
    assert metadata['trigger_device_us'] == 1040
    assert metadata['retained_generation'] == 18
    assert 'not UTC' in metadata['trigger_timestamp_reference']
    assert retained_trigger_metadata(summary(pipeline)) == {}


@pytest.mark.parametrize(
    'field,bad',
    [
        ('background_policy', True),
        ('background_policy', 3),
        ('background_q16', 0),
        ('background_q16', 65535),
        ('background_adc2', 2),
        ('gain_register_start', 2**32),
        ('gain_register_end', -1),
        ('hardware_agc', 2),
        ('gain_index_requested', True),
        ('first_trigger_device_us', 1051),
        ('last_trigger_device_us', 1200),
        ('retained_trigger_device_us', 0),
        ('retained_trigger_device_us', 1051),
        ('retained_generation', 0),
        ('retained_generation', 16),
        ('retained_generation', 21),
    ],
)
def test_policy2_rejects_bad_telemetry(field, bad):
    value = summary()
    value.update(telemetry())
    value[field] = bad
    with pytest.raises(ProtocolError):
        validate(value)


def test_policy2_requires_complete_telemetry():
    for field in telemetry():
        if field == 'background_policy':
            continue
        value = summary()
        value.update(telemetry())
        del value[field]
        with pytest.raises(ProtocolError):
            validate(value)


def test_policy2_empty_run():
    value = summary()
    value.update(telemetry())
    value.update(
        captures=0,
        detections=0,
        warmup_captures=0,
        retained_samples=0,
        total_samples=0,
        analyzed_samples=0,
        first_trigger_device_us=0,
        last_trigger_device_us=0,
        retained_trigger_device_us=0,
        retained_generation=0,
    )
    validate(value)
    value['first_trigger_device_us'] = 1
    with pytest.raises(ProtocolError):
        validate(value)
