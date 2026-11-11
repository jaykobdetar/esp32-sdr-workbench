#!/usr/bin/env python3
"""Paired, run-level offline retention trial summary. Never accesses hardware."""
import argparse,json,datetime,math
from pathlib import Path
import numpy as np

def wilson(k,n):
 z=1.959963984540054;p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
 return [c-h,c+h]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('analysis_json',type=Path);args=ap.parse_args();a=json.loads(args.analysis_json.read_text());root=args.analysis_json.parent.parent;rng=np.random.default_rng(52840);rows=[]
 for r in a['records']:
  run=json.loads((root/(r['file'].split('-')[0]+'-run.json')).read_text());s=r['receiver_summary'];h=r['decoder']['full_payload_matches']
  rows.append(dict(file=r['file'],pair=run['pair'],mode=r['mode'],tx_on=r['tx_on'],full_payload=bool(h),full_crc=any(x['crc_verified'] and x['address_verified'] for x in h),exact_header=bool(r['decoder']['exact_sync_candidates']),candidate_rate=s['detections']/(s['wall_elapsed_us']/1e6),local_duty=s['nominal_rf_duty_percent'],host_duty=s['nominal_host_rf_duty_percent'],component_clip_fraction=r['metrics']['component_clip_fraction'],metadata={k:s.get(k) for k in ['retention_policy','selected_candidate_index','retention_replacements','retention_seed','retained_generation','detections','errors','pack_failed','retained_crc_valid']},retention_copy_us=s['retention_copy_us']))
 summaries=[]
 for mode in ['strongest','reservoir']:
  for on in [True,False]:
   rr=[r for r in rows if r['mode']==mode and r['tx_on']==on];n=len(rr);k=sum(r['full_crc'] for r in rr)
   if not n:continue
   summaries.append(dict(mode=mode,tx_on=on,n=n,full_crc=k,full_crc_wilson_95=wilson(k,n),full_payload=sum(r['full_payload'] for r in rr),exact_header=sum(r['exact_header'] for r in rr),**{key:float(np.mean([r[key] for r in rr])) for key in ['candidate_rate','local_duty','host_duty','retention_copy_us','component_clip_fraction']}))
 pairs=[]
 for pair in sorted(set(r['pair'] for r in rows)):
  rr={r['mode']:r for r in rows if r['pair']==pair and r['tx_on']}
  if len(rr)!=2:continue
  pairs.append(dict(pair=pair,strongest_crc=rr['strongest']['full_crc'],reservoir_crc=rr['reservoir']['full_crc'],rate_difference=rr['reservoir']['candidate_rate']-rr['strongest']['candidate_rate'],host_duty_difference=rr['reservoir']['host_duty']-rr['strongest']['host_duty']))
 diff=np.array([int(p['reservoir_crc'])-int(p['strongest_crc']) for p in pairs]);boot=diff[rng.integers(0,len(diff),(20000,len(diff)))].mean(1)
 win=sum(d==1 for d in diff);lose=sum(d==-1 for d in diff);n=win+lose;pval=min(1.,2*sum(math.comb(n,k) for k in range(min(win,lose)+1))/2**n) if n else 1.
 result=dict(input=str(args.analysis_json),groups=summaries,pairs=pairs,paired_crc_difference=float(diff.mean()),paired_bootstrap_percentile_95=np.percentile(boot,[2.5,97.5]).tolist(),discordant_reservoir_only=int(win),discordant_strongest_only=int(lose),exact_mcnemar_two_sided_p=pval,records=rows,cautions=['Small paired trial; wide intervals and temporal/random-seed effects.','Capture-level retained-frame yield is not RF packet recall.','No claim of policy improvement solely from a numerically higher sample yield.'])
 out=args.analysis_json.parent/('retention-summary-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json');out.write_text(json.dumps(result,indent=2));print(out);print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
if __name__=='__main__':main()
