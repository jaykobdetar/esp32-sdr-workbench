#!/usr/bin/env python3
"""Offline-only SigMF diagnostics and conservative unwhitened Nordic payload search.
Requires numpy. No serial, network, firmware modification or hardware control.
"""
import argparse, datetime, hashlib, json
from pathlib import Path
import numpy as np

def db(x): return float(10*np.log10(max(float(x),1e-30)))
def bits(b): return np.unpackbits(np.frombuffer(b,dtype=np.uint8),bitorder='little').astype(np.int16)
def payload(seq,length): return b'RFTX'+int(seq).to_bytes(4,'little')+bytes((k+seq)&255 for k in range(8,length))
def decode(x,fs,mbps,length,cfo_step=125000):
    # Differential phase removes absolute phase. Boxcar integrates one symbol.
    # Search all integer symbol phases, polarity, and CFO decision thresholds.
    sps=int(round(fs/(mbps*1e6)))
    disc=np.angle(x[1:]*np.conj(x[:-1]))*fs/(2*np.pi)
    sync=bits(bytes([length])+b'RFTX'); target=2*sync-1
    hits={}; near=0; best=40; partials=[]
    for phase in range(sps):
        d=disc[phase:]; d=d[:len(d)//sps*sps].reshape(-1,sps).mean(1)
        if len(d)<len(sync): continue
        for cfo in np.arange(-2000000,2000001,cfo_step):
            for polarity in (1,-1):
                b=(polarity*(d-cfo)>0).astype(np.int16)
                errors=(len(sync)-np.correlate(2*b-1,target,'valid'))//2
                best=min(best,int(errors.min()))
                for idx in np.flatnonzero(errors<=3):
                    near+=1
                    end=idx+8*(length+1)
                    if errors[idx]==0 and idx+72<=len(b):
                        probe=np.packbits(b[idx+8:idx+72],bitorder='little').tobytes()
                        seq0=int.from_bytes(probe[4:8],'little')
                        expected=bits(payload(seq0,length)); avail=min(len(expected),len(b)-idx-8)
                        err=int(np.count_nonzero(b[idx+8:idx+8+avail]!=expected[:avail]))
                        partials.append(dict(sequence=seq0,start_sample=int(phase+idx*sps),available_payload_bits=int(avail),expected_payload_bits=len(expected),known_payload_bit_errors=err,exact_prefix_bits=int(np.flatnonzero(b[idx+8:idx+8+avail]!=expected[:avail])[0]) if err else int(avail),observed_payload_hex=np.packbits(b[idx+8:idx+8+avail],bitorder='little').tobytes().hex(),expected_payload_hex=payload(seq0,length).hex(),cfo_threshold_hz=int(cfo),polarity=polarity))
                    if end>len(b): continue
                    raw=np.packbits(b[idx:end],bitorder='little').tobytes()
                    if raw[0]!=length or raw[1:5]!=b'RFTX': continue
                    seq=int.from_bytes(raw[5:9],'little')
                    if raw[1:]!=payload(seq,length): continue
                    start=int(phase+idx*sps)
                    # Deduplicate repeated timing/CFO hypotheses of the same packet.
                    key=seq
                    crc_info=dict(crc_verified=False,address_verified=False,address_available=bool(idx>=40),crc_available=bool(end+16<=len(b)))
                    if idx>=40:
                        address=np.packbits(b[idx-40:idx],bitorder='little').tobytes()
                        crc_info.update(address_hex=address.hex(),address_verified=address.hex()=='efcdab89c3')
                    if idx>=40 and end+16<=len(b):
                        wire=b[idx-40:end+16];address=np.packbits(wire[:40],bitorder='little').tobytes()
                        crc=0xffff
                        for bit in wire[:-16]:
                            fb=((crc>>15)&1)^int(bit);crc=(crc<<1)&0xffff
                            if fb: crc^=0x1021
                        observed_crc=int(''.join(str(int(v)) for v in wire[-16:]),2)
                        crc_info.update(crc_verified=bool(crc==observed_crc),crc_computed=f'{crc:04x}',crc_received_msb_first=f'{observed_crc:04x}')
                    candidate=dict(sequence=seq,payload_start_sample=start+sps*8,
                        length=length,symbol_phase=phase,cfo_threshold_hz=int(cfo),polarity=polarity,
                        full_known_payload_match=True,observed_payload_hex=raw[1:].hex(),expected_payload_hex=payload(seq,length).hex(),**crc_info)
                    if key not in hits or candidate['crc_verified']: hits[key]=candidate
    return dict(full_payload_matches=list(hits.values()),sync_min_bit_errors=best,
                sync_hypotheses_with_at_most_3_errors=near,exact_sync_candidates=sorted(partials,key=lambda p:(p['known_payload_bit_errors'],-p['available_payload_bits']))[:12],crc_note='CRC-16 poly1021 initffff over address+length+payload in on-air bit order; received CRC MSB-first. Transport retained_crc_valid is unrelated.')

def metrics(x,fs):
    p=abs(x)**2; block=128
    bp=p[:len(x)//block*block].reshape(-1,block).mean(1)
    # Descriptive, per-record threshold only, not a calibrated detector.
    floor=float(np.percentile(bp,20)); active=bp>max(floor*4,1e-20)
    edges=np.diff(np.r_[False,active,False].astype(int)); starts=np.where(edges==1)[0]; ends=np.where(edges==-1)[0]
    nfft=min(1024,len(x)); hop=nfft//2; win=np.hanning(nfft)
    frames=np.array([x[i:i+nfft] for i in range(0,len(x)-nfft+1,hop)])
    ps=np.mean(abs(np.fft.fftshift(np.fft.fft(frames*win,axis=1),axes=1))**2,axis=0)/(fs*np.sum(win**2))
    f=np.fft.fftshift(np.fft.fftfreq(nfft,1/fs))
    disc=np.angle(x[1:]*np.conj(x[:-1]))*fs/(2*np.pi)
    return dict(samples=len(x),aperture_us=len(x)/fs*1e6,rms=float(np.sqrt(p.mean())),
      mean_power_db_relative=db(p.mean()),dc_power_fraction=float(abs(x.mean())**2/max(p.mean(),1e-30)),
      peak_amplitude=float(abs(x).max()),component_clip_fraction=float(np.mean((abs(x.real)>=.999)|(abs(x.imag)>=.999))),
      block_peak_to_median_db=db(bp.max()/max(np.median(bp),1e-30)),
      energy_windows=[dict(start_sample=int(a*block),end_sample=int(b*block),duration_us=(b-a)*block/fs*1e6) for a,b in zip(starts,ends)],
      phase_frequency_quantiles_hz=np.percentile(disc,[5,50,95]).tolist(),
      spectral_peak_offset_hz=float(f[np.argmax(ps)]),central_2mhz_power_fraction=float(ps[abs(f)<=1e6].sum()/max(ps.sum(),1e-30)),
      plot=dict(time_us=(np.arange(len(bp))*block/fs*1e6).tolist(),block_power_db=(10*np.log10(np.maximum(bp,1e-30))).tolist(),
       frequency_mhz=(f/1e6).tolist(),psd_db=(10*np.log10(np.maximum(ps,1e-30))).tolist(),
       discriminator_us=(np.arange(0,len(disc),32)/fs*1e6).tolist(),discriminator_mhz=(disc[::32]/1e6).tolist()))

def svg(rows,path):
    out=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="%d">'% (len(rows)*180+30),'<rect width="100%" height="100%" fill="white"/>']
    for i,r in enumerate(rows):
        y=i*180+30;p=r['metrics']['plot']
        out.append(f'<text x="10" y="{y}" font-size="14">{r["file"]}</text>')
        for j,(xx,yy,label) in enumerate([(p['time_us'],p['block_power_db'],'Power vs time (us)'),(p['frequency_mhz'],p['psd_db'],'PSD vs offset (MHz)'),(p['discriminator_us'],p['discriminator_mhz'],'Phase frequency (MHz) vs us')]):
            lo=min(yy);hi=max(yy);span=max(hi-lo,1e-10);xmin=min(xx);xspan=max(max(xx)-xmin,1e-10)
            pts=' '.join(f'{10+j*400+(a-xmin)/xspan*380:.1f},{y+130-(b-lo)/span*100:.1f}' for a,b in zip(xx,yy))
            out.append(f'<polyline points="{pts}" fill="none" stroke="#246" stroke-width="1"/><text x="{10+j*400}" y="{y+150}" font-size="11">{label}; y [{lo:.2f}, {hi:.2f}]</text>')
    path.write_text('\n'.join(out+['</svg>']))

def selftest():
    # Independent synthetic payload, Gaussian-smoothed FSK with noise and CFO.
    rng=np.random.default_rng(271828); results=[]
    for mbps in (1,2):
        fs=16000000;sps=16//mbps;seq=1234;data=bytes([64])+payload(seq,64)
        frame_bits=bits(bytes.fromhex('efcdab89c3')+data)
        crc=0xffff
        for bit in frame_bits:
            fb=((crc>>15)&1)^int(bit);crc=(crc<<1)&0xffff
            if fb:crc^=0x1021
        frame_bits=np.r_[frame_bits,np.array([(crc>>shift)&1 for shift in range(15,-1,-1)])]
        symbols=np.repeat(2*frame_bits-1,sps).astype(float)
        t=np.arange(-2*sps,2*sps+1);kernel=np.exp(-.5*(t/(.24*sps))**2);kernel/=kernel.sum()
        freq=np.convolve(symbols,kernel,'same')*(250000*mbps)+375000
        x=np.exp(1j*np.cumsum(2*np.pi*freq/fs));x+=.015*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
        x=np.r_[np.zeros(43),x,np.zeros(64)]
        d=decode(x,fs,mbps,64);ok=any(h['sequence']==seq and h['crc_verified'] and h['address_verified'] for h in d['full_payload_matches'])
        assert ok, (mbps,d)
        noise=rng.normal(size=len(x))+1j*rng.normal(size=len(x))
        assert not decode(noise,fs,mbps,64)['full_payload_matches']
        results.append(dict(mbps=mbps,synthetic_payload_address_crc_recovered=ok,noise_negative=True))
    return results

def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--cfo-step-hz',type=int,default=125000);args=ap.parse_args()
    if args.cfo_step_hz<=0:ap.error('--cfo-step-hz must be positive')
    out=args.output or args.directory/('analysis-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True,exist_ok=False)
    test=selftest();rows=[]
    for p in sorted(args.directory.glob('*.sigmf-data')):
        mp=p.with_suffix('.sigmf-meta')
        if not mp.exists():continue
        meta=json.loads(mp.read_text());runp=p.parent/(p.name.split('-')[0]+'-run.json')
        md=meta['global'].get('sdr_research:metadata',{})
        if runp.exists(): run=json.loads(runp.read_text())
        elif 'controlled_source' in md:
            run=dict(md['controlled_source']);run.setdefault('mode','raw');run.setdefault('frequency_mhz',run.get('rx_frequency_mhz'))
        else: continue
        fs=meta['global']['core:sample_rate']
        assert meta['global']['core:datatype']=='cf32_le'
        x=np.fromfile(p,dtype='<c8');tx=run.get('tx_start') or run.get('tx_stopped') or run.get('tx_before') or {}
        r=dict(file=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),tx_on=run['tx_on'],mode=run['mode'],frequency_mhz=run['frequency_mhz'],gain=md.get('settings',{}).get('gain',md.get('controlled_source',{}).get('settings',{}).get('gain')),
          tx_completed_delta=run.get('tx_completed_delta'),receiver_summary=run.get('summary',{}),metrics=metrics(x,fs),
          decoder=decode(x,fs,tx.get('mode_mbps',2),tx.get('payload_len',64),args.cfo_step_hz))
        rows.append(r)
    summary=[]
    for freq,mode,gain in sorted(set((r['frequency_mhz'],r['mode'],r['gain']) for r in rows)):
        s=dict(frequency_mhz=freq,mode=mode,gain=gain)
        for state in (True,False):
            rr=[r for r in rows if r['frequency_mhz']==freq and r['mode']==mode and r['gain']==gain and r['tx_on']==state]
            if rr:s['on' if state else 'off']=dict(n=len(rr),median_rms=float(np.median([r['metrics']['rms'] for r in rr])),
                mean_power_db=db(np.mean([r['metrics']['rms']**2 for r in rr])),
                energy_window_count=sum(len(r['metrics']['energy_windows']) for r in rr),
                full_payload_match_hypotheses=sum(len(r['decoder']['full_payload_matches']) for r in rr),
                address_and_crc_verified_packets=sum(sum(h['crc_verified'] and h['address_verified'] for h in r['decoder']['full_payload_matches']) for r in rr),
                detections=[r['receiver_summary'].get('detections') for r in rr])
        if 'on' in s and 'off' in s:s['on_minus_off_mean_power_db']=s['on']['mean_power_db']-s['off']['mean_power_db']
        if len(s)>3:summary.append(s)
    (out/'analysis.json').write_text(json.dumps(dict(cfo_step_hz=args.cfo_step_hz,analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),synthetic_tests=test,summary=summary,records=rows),indent=2))
    svg(rows,out/'diagnostics.svg')
    print(json.dumps(dict(output=str(out),synthetic_tests=test,summary=summary),indent=2))
if __name__=='__main__':main()
