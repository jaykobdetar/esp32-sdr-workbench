from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import threading
import numpy as np
import pytest
from sdr_research.multireceiver import ReceiverConfig, describe_plan, run_plan, validate_plan
from sdr_research.protocol import Capture

class FakeRadio:
    def __init__(self,port):self.port=port;self.owner=threading.get_ident();self.closed=False
    def connect(self):return {'port':self.port}
    def configure(self,frequency,rate,bandwidth,gain,bits):
        assert threading.get_ident()==self.owner
        self.frequency=frequency;self.rate=rate
    def capture(self,n):
        assert threading.get_ident()==self.owner
        return Capture(np.zeros(n,dtype=np.complex64),self.rate,self.frequency*1000000,
                       '2026-11-11T00:00:00Z',0,1,1000,10,True,{})
    def close(self):self.closed=True


def test_independent_config_and_close(tmp_path):
    radios=[]
    def factory(port):
        r=FakeRadio(port);radios.append(r);return r
    configs=[ReceiverConfig('a','/fake/a',captures=2),ReceiverConfig('b','/fake/b',frequency_mhz=2470,rate_hz=40000000,samples=2048,start_offset_ms=1)]
    result=run_plan(configs,radio_factory=factory,output_directory=tmp_path/'new')
    assert result['status']=='passed' and len(radios)==2 and all(r.closed for r in radios)
    assert [len(r['captures']) for r in result['receivers']]==[2,1]
    assert [r.frequency for r in sorted(radios,key=lambda r:r.port)]==[2440,2470]
    assert len(list((tmp_path/'new').glob('*.sigmf-meta')))==3
    assert result['receivers'][1]['successful_nominal_rf_seconds']==2048/40000000
    assert 'continuous reception cannot' in result['timing_note']
    json.dumps(result)


def test_failure_does_not_hide_other_receiver_and_closes():
    radios=[]
    class Bad(FakeRadio):
        def connect(self):
            if self.port=='bad':raise RuntimeError('connect failed')
            return super().connect()
    def factory(port):
        r=Bad(port);radios.append(r);return r
    result=run_plan([ReceiverConfig('a','bad'),ReceiverConfig('b','good')],radio_factory=factory)
    assert result['status']=='failed'
    assert [r['status'] for r in result['receivers']]==['failed','passed']
    assert all(r.closed for r in radios)


@pytest.mark.parametrize('kwargs',[{'samples':1},{'start_offset_ms':-1},{'captures':0},{'captures':101},{'frequency_mhz':2501},{'rate_hz':123},{'gain':True},{'receiver_id':'../bad'}])
def test_invalid_config_never_opens(kwargs):
    c=replace(ReceiverConfig('a','fake'),**kwargs)
    with pytest.raises(ValueError):run_plan([c],radio_factory=lambda _:pytest.fail('hardware factory called'))


def test_duplicate_ids_ports_and_symlink(tmp_path):
    c=ReceiverConfig('a',str(tmp_path/'serial'))
    with pytest.raises(ValueError):validate_plan([c,replace(c,port='another')])
    with pytest.raises(ValueError):validate_plan([c,replace(c,receiver_id='b')])
    alias=tmp_path/'alias';alias.symlink_to(tmp_path/'serial')
    with pytest.raises(ValueError):validate_plan([c,replace(c,receiver_id='b',port=str(alias))])


def test_offset_host_bound():
    now=[1000000000]
    def clock():return now[0]
    def sleep(seconds):now[0]+=int(seconds*1e9)
    r=run_plan([ReceiverConfig('a','fake',start_offset_ms=50)],radio_factory=FakeRadio,clock=clock,sleep=sleep)
    row=r['receivers'][0]
    assert row['actual_worker_start_ns']==1050000000
    assert row['host_start_lateness_ns']==0


def test_dry_run_cli_does_not_open_nonexistent_port(tmp_path):
    plan=tmp_path/'plan.json';plan.write_text('[{"receiver_id":"one","port":"/no/such/serial"}]')
    script=Path(__file__).parents[1]/'scripts/multi_receiver_capture.py'
    p=subprocess.run([sys.executable,str(script),'--plan',str(plan),'--dry-run'],capture_output=True,text=True)
    assert p.returncode==0 and 'no hardware opened' in p.stdout
    assert 'one:' in p.stdout


def test_close_and_crc_errors_reported():
    class Bad(FakeRadio):
        def capture(self,n):
            c=super().capture(n);c.crc_ok=False;return c
        def close(self):raise RuntimeError('close failed')
    r=run_plan([ReceiverConfig('a','fake')],radio_factory=Bad)['receivers'][0]
    assert r['status']=='failed' and 'CRC failed' in r['error'] and 'close failed' in r['close_error']
