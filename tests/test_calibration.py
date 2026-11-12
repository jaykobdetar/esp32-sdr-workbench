import json

import pytest

from sdr_research.calibration import record_calibration


class RX:
    failed = False

    def __init__(self, **changes):
        self.value = dict(version=1, algorithm='sha256', bytes=1904, sha256='a' * 64, device_us=100)
        self.value.update(changes)
        self.commands = []

    def command(self, cmd):
        self.commands.append(cmd)
        return 'CALHASH ' + json.dumps(self.value)


def test_changes_and_clock_regression_are_observations_not_integrity_claims():
    rx, report, info = RX(), {}, {'caps': ['CALHASH']}
    first = record_calibration(report, rx, info, 'stage_start', required=True)
    assert first['changed_from_previous'] is None
    same = record_calibration(report, rx, info, 'run_0_after')
    assert same['changed_from_previous'] is False
    rx.value.update(sha256='b' * 64, device_us=1, secret='never copy this')
    changed = record_calibration(report, rx, info, 'stage_end')
    assert changed['changed_from_previous'] is True and changed['device_clock_regressed'] is True
    assert 'secret' not in changed and rx.commands == ['CALHASH?'] * 3


def test_legacy_is_explicitly_unsupported_and_new_variant_requires_capability():
    rx, report = RX(), {}
    assert record_calibration(report, rx, {}, 'stage_start')['status'] == 'unsupported'
    with pytest.raises(RuntimeError, match='capability missing'):
        record_calibration(report, rx, {}, 'stage_end', required=True)
    assert not rx.commands


@pytest.mark.parametrize(
    'change',
    [
        dict(version=True),
        dict(bytes=1903),
        dict(bytes=True),
        dict(device_us=-1),
        dict(sha256='bad'),
        dict(algorithm='md5'),
    ],
)
def test_invalid_observation_persisted_as_error(change):
    report = {}
    with pytest.raises(ValueError, match='fingerprint'):
        record_calibration(report, RX(**change), {'caps': ['CALHASH']}, 'stage_start')
    assert report['calibration_observations'][0]['status'] == 'error'


def test_failed_transport_does_not_attempt_another_command():
    rx, report = RX(), {}
    rx.failed = True
    with pytest.raises(RuntimeError, match='transport failure'):
        record_calibration(report, rx, {'caps': ['CALHASH']}, 'stage_end')
    assert not rx.commands and report['calibration_observations'][0]['status'] == 'unavailable'
