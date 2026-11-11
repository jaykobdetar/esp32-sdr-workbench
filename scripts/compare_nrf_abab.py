#!/usr/bin/env python3
"""Read-only ABAB run-level comparison. Bootstrap units are ON/OFF pairs, not samples."""
import argparse,json,datetime
from pathlib import Path
import numpy as np

def ci(a,rng):
 a=np.asarray(a,dtype=float)
 if not len(a):return None
 boot=a[rng.integers(0,len(a),size=(20000,len(a)))].mean(1)
 return dict(n=len(a),mean=float(a.mean()),bootstrap_percentile_95=np.percentile(boot,[2.5,97.5]).tolist(),values=a.tolist())
def main():
 ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);args=ap.parse_args();rng=np.random.default_rng(52840);phases=[]
 for directory in sorted(args.directory.iterdir()):
  if not directory.is_dir():continue
  runs=[json.loads(p.read_text()) for p in sorted(directory.glob('*-run.json'))]
  if not runs:continue
  metrics={};deltas=[]
  for r in runs:
   s=r['summary'];m=dict(candidate_rate=s['detections']/(s['wall_elapsed_us']/1e6),local_rf_duty=s.get('nominal_rf_duty_percent'),host_rf_duty=s.get('nominal_host_rf_duty_percent',s.get('nominal_host_duty_percent')))
   metrics[(r['pair'],r['tx_on'])]=m
  for pair in sorted(set(k[0] for k in metrics)):
   if (pair,True) in metrics and (pair,False) in metrics:deltas.append(metrics[(pair,True)]['candidate_rate']-metrics[(pair,False)]['candidate_rate'])
  states={}
  for on in [True,False]:
   rr=[v for (p,state),v in metrics.items() if state==on]
   states['on' if on else 'off']={key:ci([v[key] for v in rr if v[key] is not None],rng) for key in ['candidate_rate','local_rf_duty','host_rf_duty']}
  phases.append(dict(phase=directory.name,runs=len(runs),paired_candidate_excess=ci(deltas,rng),states=states))
 effects=[]
 for cycle in [1,2]:
  h=next((p for p in phases if p['phase']==f'historical-{cycle}'),None);o=next((p for p in phases if p['phase']==f'optimized-{cycle}'),None)
  if not(h and o):continue
  ha=np.array(h['paired_candidate_excess']['values']);oa=np.array(o['paired_candidate_excess']['values'])
  if not len(ha) or not len(oa):continue
  hb=ha[rng.integers(0,len(ha),(20000,len(ha)))].mean(1);ob=oa[rng.integers(0,len(oa),(20000,len(oa)))].mean(1)
  effects.append(dict(cycle=cycle,optimized_minus_historical_excess_per_second=float(oa.mean()-ha.mean()),bootstrap_percentile_95=np.percentile(ob-hb,[2.5,97.5]).tolist()))
 out=args.directory/('comparison-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
 result=dict(phases=phases,cycle_effects=effects,cautions=['Small n: percentile-bootstrap intervals are descriptive and can undercover.','Each ON/OFF pair is the resampling unit; phases resampled independently for cycle differences.','ABAB time order is confounded with environment; only two temporal replications, no robust causal confidence interval.','Candidate counts are not packet counts. OFF activity is not a per-packet false-positive probability.','Nominal aperture duty is not actual continuous-symbol availability.'])
 out.write_text(json.dumps(result,indent=2));print(out);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
