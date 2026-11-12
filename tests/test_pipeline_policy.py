import pytest

from sdr_research.pipeline import (
    check_background_summary,
    select_acquisition_policy,
    select_background_policy,
)
from sdr_research.protocol import ProtocolError


class Radio:
    def __init__(self, caps=('ACQOPT', 'CLEAROPT'), bad=None):
        self.info = {'caps': caps}
        self.calls = []
        self.values = {}
        self.bad = bad
        self.failed = False

    def command(self, cmd):
        self.calls.append(cmd)
        if cmd == self.bad:
            return 'ERR unsupported'
        if cmd.endswith('?'):
            name = cmd[:-1]
            return f'{name} {self.values[name]}'
        name, value = cmd.split()
        self.values[name] = int(value)
        return 'OK'


def test_policy_optimized_then_baseline_restore():
    r = Radio()
    p = select_acquisition_policy(r, True)
    assert p['ACQOPT'] == dict(requested=3, returned=3, supported=True)
    assert r.values == dict(ACQOPT=3, CLEAROPT=1)
    select_acquisition_policy(r, False)
    assert r.values == dict(ACQOPT=0, CLEAROPT=0)
    assert r.calls == [
        'ACQOPT 3',
        'ACQOPT?',
        'CLEAROPT 1',
        'CLEAROPT?',
        'ACQOPT 0',
        'ACQOPT?',
        'CLEAROPT 0',
        'CLEAROPT?',
    ]


def test_legacy_no_commands_and_optimized_refuses():
    r = Radio(caps=())
    select_acquisition_policy(r, False)
    assert not r.calls
    with pytest.raises(ProtocolError):
        select_acquisition_policy(r, True)
    assert not r.calls


@pytest.mark.parametrize('cmd', ['ACQOPT 3', 'ACQOPT?', 'CLEAROPT 1', 'CLEAROPT?'])
def test_ack_or_readback_failure_fails_closed(cmd):
    r = Radio(bad=cmd)
    with pytest.raises(ProtocolError):
        select_acquisition_policy(r, True)
    assert r.failed


class PolicyRadio:
    """Firmware selector model: BGPOLICY echoes its value and is sticky."""

    def __init__(self, caps=('BGPOLICY',), stored=2, readback=None):
        self.info = {'caps': caps}
        self.calls = []
        self.stored = stored
        self.readback = readback
        self.failed = False

    def command(self, cmd):
        self.calls.append(cmd)
        if cmd == 'BGPOLICY?':
            return f'BGPOLICY {self.stored if self.readback is None else self.readback}'
        name, value = cmd.split()
        assert name == 'BGPOLICY'
        if value not in ('1', '2'):
            return 'ERR background_policy'
        self.stored = int(value)
        return cmd


@pytest.mark.parametrize('requested,selected', [(None, 2), (1, 1), (2, 2)])
def test_background_policy_is_always_set_and_read_back_when_selectable(requested, selected):
    # Start from a stale legacy selection: the default must not inherit it.
    r = PolicyRadio(stored=1)
    selection = select_background_policy(r, requested)
    assert selection == dict(requested=requested, returned=selected, supported=True)
    assert r.calls == [f'BGPOLICY {selected}', 'BGPOLICY?'] and r.stored == selected
    check_background_summary({'background_policy': selected}, selection)
    with pytest.raises(ProtocolError, match='does not match'):
        check_background_summary({'background_policy': 3 - selected}, selection)
    assert not r.failed


def test_background_policy_without_capability_is_unprobed_or_refused():
    r = PolicyRadio(caps=())
    selection = select_background_policy(r, None)
    assert selection == dict(requested=None, returned=None, supported=False) and not r.calls
    # Historical firmware reports no policy or a fixed one; neither is second-guessed.
    check_background_summary({}, selection)
    check_background_summary({'background_policy': 2}, selection)
    for explicit in (1, 2):
        with pytest.raises(ProtocolError, match='BGPOLICY capability required'):
            select_background_policy(r, explicit)
    assert not r.calls and not r.failed


def test_background_policy_readback_mismatch_marks_connection_unusable():
    r = PolicyRadio(readback=2)
    with pytest.raises(ProtocolError, match='readback'):
        select_background_policy(r, 1)
    assert r.failed and r.calls == ['BGPOLICY 1', 'BGPOLICY?']


@pytest.mark.parametrize('bad', [0, 3, True, '1', 1.0])
def test_background_policy_rejects_invalid_values_before_any_command(bad):
    r = PolicyRadio()
    with pytest.raises(ValueError):
        select_background_policy(r, bad)
    assert not r.calls
