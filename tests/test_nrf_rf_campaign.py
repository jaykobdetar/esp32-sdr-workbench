import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest
from sdr_research.protocol import Capture

spec=importlib.util.spec_from_file_location('nrf_rf_campaign',Path(__file__).parents[1]/'scripts/nrf_rf_campaign.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class TX:
    def __init__(self): self.running=False;self.completed=0;self.stops=0;self.cfg={}
    def status(self):
        if self.running:self.completed+=10
        return dict(self.cfg,running=self.running,scheduled=self.completed,attempted=self.completed,completed=self.completed)
    def stop(self):self.stops+=1;self.running=False;return {'running':False}
    def configure(self,**kwargs):self.cfg=kwargs;return kwargs
    def start(self,**kwargs):self.running=True;return dict(kwargs,running=True)

class RX:
    info={'version':'VERSION esp32-pipeline-optimized-v2','caps':[]}
    def connect(self):return self.info
    def configure(self,*args):self.frequency=args[0]
    def command(self,cmd):return 'OK'
    def capture(self,n):
        return Capture(np.zeros(n,dtype=np.complex64),16000000,self.frequency*1000000,'2026-11-11T00:00:00Z',0,1,1024,10,True,{})


def args(tmp_path):
    artifact=tmp_path/'receiver.bin';artifact.write_bytes(b'synthetic receiver test artifact')
    return m.parser().parse_args(['--rx-artifact',str(artifact),'--rx-port','fake','--tx-port','fake','--output-directory',str(tmp_path/'new'),'--pairs','2','--raw-pairs','1'])

def detector(radio,*args,**kwargs):
    return {'status':0,'captures':20,'warmup_captures':16,'detections':0,'total_samples':327600,'wall_elapsed_us':2000000},None

def test_plan_reproducible_and_counterbalanced(tmp_path):
    a=args(tmp_path);a.pairs=8
    assert m.plan(a)==m.plan(a)
    p=[r for r in m.plan(a) if r['mode']!='raw']
    assert len(p)==32
    for i in range(8):
        rows=[r for r in p if r['pair']==i]
        assert {(r['mode'],r['tx_on']) for r in rows}=={(x,y) for x in ('baseline','optimized') for y in (False,True)}
    assert sum(next(r for r in p if r['pair']==i)['tx_on'] for i in range(8))==4

def test_complete_saves_no_events_and_raw(tmp_path):
    a=args(tmp_path);tx=TX()
    result=m.execute(a,RX(),tx,sleep=lambda _:None,pipeline=detector,detector=detector)
    assert result['status']=='passed' and not tx.running
    assert len(result['runs'])==10
    assert len(list(a.output_directory.glob('*.sigmf-meta')))==2
    assert len(list(a.output_directory.glob('*-run.json')))==10
    assert (a.output_directory/'runs.csv').exists()
    assert json.loads((a.output_directory/'results.json').read_text())['cleanup_status']['running'] is False
    assert all(r['tx_completed_delta']==(10 if r['tx_on'] else 0) for r in result['runs'])

def test_receiver_failure_stops_and_persists(tmp_path):
    a=args(tmp_path);a.raw_pairs=0;tx=TX()
    def fail(*args,**kwargs):raise RuntimeError('CRC mismatch')
    with pytest.raises(RuntimeError,match='CRC mismatch'):
        m.execute(a,RX(),tx,sleep=lambda _:None,pipeline=fail,detector=fail)
    result=json.loads((a.output_directory/'results.json').read_text())
    assert result['status']=='failed' and not tx.running
    assert result['runs'][-1]['status']=='failed'

def test_config_mismatch_stops(tmp_path):
    class Bad(TX):
        def configure(self,**kwargs):kwargs['frequency_mhz']=2402;return super().configure(**kwargs)
    a=args(tmp_path);tx=Bad()
    with pytest.raises(RuntimeError,match='configuration mismatch'):
        m.execute(a,RX(),tx,sleep=lambda _:None)
    assert not tx.running

def test_existing_output_not_overwritten(tmp_path):
    a=args(tmp_path);a.output_directory.mkdir();sentinel=a.output_directory/'results.json';sentinel.write_text('original');tx=TX()
    with pytest.raises(FileExistsError):m.execute(a,RX(),tx)
    assert sentinel.read_text()=='original' and tx.stops==1

def test_state_mismatch_and_invalid_counters():
    tx=TX()
    with pytest.raises(RuntimeError,match='running mismatch'):m.checked_status(tx,True)
    tx.completed=-1
    with pytest.raises(RuntimeError,match='counter'):m.checked_status(tx,False)

def test_no_source_progress_is_failure(tmp_path):
    class Stalled(TX):
        def status(self):return dict(self.cfg,running=self.running,scheduled=0,attempted=0,completed=0)
    a=args(tmp_path);a.raw_pairs=0;tx=Stalled()
    with pytest.raises(RuntimeError,match='counter delta'):
        m.execute(a,RX(),tx,sleep=lambda _:None,pipeline=detector,detector=detector)
    assert not tx.running

def test_source_expiration_fails_closed(tmp_path):
    class Expiring(TX):
        checks=0
        def status(self):
            if self.running:
                self.checks+=1
                if self.checks==2:self.running=False
            return super().status()
    a=args(tmp_path);a.raw_pairs=0;tx=Expiring()
    with pytest.raises(RuntimeError,match='running mismatch'):
        m.execute(a,RX(),tx,sleep=lambda _:None,pipeline=detector,detector=detector)
    assert not tx.running

def test_cleanup_failure_marks_report_failed(tmp_path):
    a=args(tmp_path);a.raw_pairs=0;a.pairs=1
    tx=TX();original=tx.stop
    def stop():
        # Initial + two stops per observation; the final cleanup is the tenth.
        if tx.stops==9:raise RuntimeError('Disconnected')
        return original()
    tx.stop=stop
    result=m.execute(a,RX(),tx,sleep=lambda _:None,pipeline=detector,detector=detector)
    assert result['status']=='failed' and 'Disconnected' in result['cleanup_error']

def test_retention_policy_readback_and_summary(tmp_path):
    class RetentionRX(RX):
        policy=0;seed=0
        def command(self,cmd):
            if cmd.startswith('PIPESEED '):self.seed=int(cmd.split()[1]);return cmd
            if cmd.startswith('PIPEKEEP '):self.policy=int(cmd.split()[1])
            if cmd.startswith('PIPEKEEP'):return f'PIPEKEEP {self.policy} {self.seed}'
            return 'OK'
    def pipe(r,*aa,**kw):
        s,c=detector(r,*aa,**kw);s.update(retention_policy=r.policy,retention_seed=r.seed);return s,c
    a=args(tmp_path);a.receiver_modes=['strongest','reservoir'];a.raw_pairs=0
    result=m.execute(a,RetentionRX(),TX(),sleep=lambda _:None,pipeline=pipe)
    assert result['status']=='passed'
    for row in result['runs']:
        assert row['summary']['retention_policy']==int(row['mode']=='reservoir')
        assert row['summary']['retention_seed']==a.seed+row['pair']*104729

def test_retention_policy_requires_readback(tmp_path):
    a=args(tmp_path);a.receiver_modes=['reservoir'];a.raw_pairs=0;t=TX()
    with pytest.raises(RuntimeError,match='Retention seed acknowledgement'):
        m.execute(a,RX(),t,sleep=lambda _:None,pipeline=detector)
    assert not t.running
