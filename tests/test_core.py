import struct,zlib
import numpy as np
import pytest
from sdr_research.protocol import decode_iq,ProtocolError,Capture
from sdr_research.analysis import spectrum,detect_event
from sdr_research.recording import save_capture,load_capture

def test_iq8_q_sign_and_min():
    a=decode_iq(bytes([127,128,128,127]),2,8)
    np.testing.assert_allclose(a,[127/128+1j,-1-127j/128])

def test_iq10_odd_and_even():
    for n in (1,2,3,257):
        rng=np.random.default_rng(n);pairs=rng.integers(-512,512,(n,2));bits=0
        for k,(i,q) in enumerate(pairs):bits|=((int(i)&1023)|((int(q)&1023)<<10))<<(20*k)
        data=bits.to_bytes((20*n+7)//8,'little')
        np.testing.assert_allclose(decode_iq(data,n,10),(pairs[:,0]-1j*pairs[:,1])/512)

def test_bad_length():
    with pytest.raises(ProtocolError):decode_iq(b'',5,8)

def test_spectrum_tone_direction():
    n=4096;x=.5*np.exp(2j*np.pi*np.arange(n)/16)
    f,p=spectrum(x,16_000_000)
    assert f[p.argmax()]==1_000_000
    assert abs(p.max()+6.02)<.02

def test_energy_detector_dc_robust():
    rng=np.random.default_rng(5);x=.02*(rng.normal(size=4096)+1j*rng.normal(size=4096))
    assert not detect_event(x+(.8+.5j),16_000_000)['detected']
    x[1500:2000]+=.3*np.exp(2j*np.pi*np.arange(500)/8)
    assert detect_event(x,16_000_000)['detected']

def test_sigmf_roundtrip(tmp_path):
    c=Capture(np.array([.1+.2j,-.7-.4j],np.complex64),16_000_000,2440000000,'2026-11-10T21:00:00+00:00',100,200,3)
    p=save_capture(c,tmp_path/'example');r=load_capture(p)
    np.testing.assert_equal(c.iq,r.iq);assert r.frequency_hz==c.frequency_hz
    with pytest.raises(FileExistsError):save_capture(c,tmp_path/'example')

def test_sigmf_reject_partial_sample(tmp_path):
    c=Capture(np.array([.1j],np.complex64),16_000_000,2440000000,'2026-11-10T21:00:00+00:00',100,200,3)
    p=save_capture(c,tmp_path/'partial')
    with p.with_suffix('.sigmf-data').open('ab') as f:f.write(b'x')
    with pytest.raises(ValueError,match='Truncated'):load_capture(p)
