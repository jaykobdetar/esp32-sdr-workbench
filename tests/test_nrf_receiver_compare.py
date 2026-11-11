import importlib.util
from pathlib import Path
import pytest
from test_nrf_rf_campaign import TX, RX, detector

spec=importlib.util.spec_from_file_location('compare',Path(__file__).parents[1]/'scripts/nrf_receiver_compare.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def args(tmp_path, mode='historical'):
    artifact=tmp_path/'receiver.bin';artifact.write_bytes(b'synthetic receiver test artifact')
    return m.prepare(m.parser().parse_args(['--rx-artifact',str(artifact),'--rx-port','fake','--tx-port','fake','--output-directory',str(tmp_path/'new'),'--receiver-mode',mode,'--label',mode+'-A1']))

def test_sixteen_observations_and_label(tmp_path):
    a=args(tmp_path)
    p=m.campaign.plan(a)
    assert len(p)==16 and {r['mode'] for r in p}=={'historical'}
    assert sum(r['tx_on'] for r in p)==8
    assert a.label=='historical-A1' and a.raw_pairs==0


def test_historical_never_probes_pipeline_and_logs_actual_version(tmp_path):
    class Historical(RX):
        info={'version':'old VERSION without variant','caps':[]}
        def command(self,cmd):raise AssertionError('Historical must not issue '+cmd)
    a=args(tmp_path)
    r=m.campaign.execute(a,Historical(),TX(),sleep=lambda _:None,detector=detector)
    assert r['status']=='passed' and r['device']['version']=='old VERSION without variant'
    assert r['local_rx_artifact_sha256']==__import__('hashlib').sha256(b'synthetic receiver test artifact').hexdigest()
    row=r['runs'][0]
    assert row['nominal_rf_seconds']==pytest.approx(327600/16000000)
    assert row['nominal_local_rf_duty_percent']==pytest.approx(1.02375)
    assert row['nominal_receiver_host_rf_duty_percent']>0


def test_optimized_calls_only_pipeline_with_exact_policy(tmp_path):
    def pipeline(*args,**kwargs):
        assert kwargs==dict(kernel=3,optimized=True,copy_option=1)
        return detector(*args,**kwargs)
    def forbidden(*args,**kwargs):raise AssertionError('Wrong receiver mode')
    a=args(tmp_path,'optimized')
    r=m.campaign.execute(a,RX(),TX(),sleep=lambda _:None,pipeline=pipeline,detector=forbidden)
    assert r['status']=='passed' and {x['mode'] for x in r['runs']}=={'optimized'}


def test_optional_variant_mismatch_fails(tmp_path):
    a=args(tmp_path);a.expected_variant='not-present';tx=TX()
    with pytest.raises(RuntimeError,match='Expected receiver variant'):
        m.campaign.execute(a,RX(),tx,sleep=lambda _:None)
    assert not tx.running
