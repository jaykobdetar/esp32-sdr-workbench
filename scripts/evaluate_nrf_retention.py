#!/usr/bin/env python3
"""Offline selection proxy on independently saved raw buffers, NOT firmware replay.
Labels are used only for evaluation; selectors inspect energy/boundaries, never decoded bits.
"""
import argparse,json,datetime
from pathlib import Path
import numpy as np

def blocks(x):
 z=x[:len(x)//64*64].reshape(-1,64)
 return np.mean(abs(z-z.mean(axis=1,keepdims=True))**2,axis=1)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('analysis_json',type=Path);ap.add_argument('--gain',type=int,default=60);args=ap.parse_args()
 data=json.loads(args.analysis_json.read_text());root=args.analysis_json.parent.parent
 rr=[r for r in data['records'] if r['mode']=='raw' and r['gain']==args.gain]
 energies={r['file']:blocks(np.fromfile(root/r['file'],dtype='<c8')) for r in rr}
 off=[v for r in rr if not r['tx_on'] for v in energies[r['file']]]
 floor=float(np.median(off));threshold=floor*4
 candidates=[]
 for r in rr:
  if not r['tx_on']:continue
  e=energies[r['file']];mask=e>threshold;diff=np.diff(np.r_[False,mask,False].astype(int));a=np.flatnonzero(diff==1);b=np.flatnonzero(diff==-1)
  # 64 samples at16MS/s =4us; full64B frame is292us at2Mbps.
  complete=[(int(i),int(j)) for i,j in zip(a,b) if i>=2 and j<=len(e)-2 and (j-i)*4>=292]
  candidates.append(dict(file=r['file'],peak_ratio=float(e.max()/floor),boundary_eligible=bool(complete),interior_runs=complete,
   valid_packet=any(h['crc_verified'] and h['address_verified'] for h in r['decoder']['full_payload_matches'])))
 if not candidates:raise ValueError('No ON candidates')
 best=max(candidates,key=lambda c:c['peak_ratio']);eligible=[c for c in candidates if c['boundary_eligible']]
 result=dict(input=str(args.analysis_json),gain=args.gain,dc_removed_block_size=64,off_median_block_power=floor,threshold=threshold,candidates=candidates,
  strongest_peak_proxy=dict(selected=best['file'],valid_packet=best['valid_packet']),
  uniform_reservoir=dict(expected_valid_fraction=float(np.mean([c['valid_packet'] for c in candidates])),population=len(candidates)),
  boundary_then_uniform=dict(eligible=len(eligible),expected_valid_fraction=float(np.mean([c['valid_packet'] for c in eligible])) if eligible else None),
  caveats=['Tiny convenience sample of independent raw buffers, not all actual detector events.','Fixed pooled-OFF reference differs from online EWMA; strongest_peak_proxy is NOT exact firmware retention replay.','292us duration assumes64-byte2Mbps frame; threshold/boundary rule is preliminary and may reject valid low-SNR or fragmented-energy packets.','No policy is proven better; confirm on held-out multi-candidate captures with equal retention byte budgets.'])
 out=args.analysis_json.parent/('retention-proxy-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json');out.write_text(json.dumps(result,indent=2));print(out);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
