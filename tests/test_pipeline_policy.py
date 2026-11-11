import pytest

from sdr_research.pipeline import select_acquisition_policy
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
