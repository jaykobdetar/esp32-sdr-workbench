#!/usr/bin/env python3
"""Summarize independently acquired one-factor screen; no hardware actions."""
import argparse,datetime,json
from pathlib import Path
import numpy as np

def main():
 ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);args=ap.parse_args();rows=[]
 for directory in sorted(p for p in args.directory.iterdir() if p.is_dir()):
  aa=sorted(directory.glob('analysis-*/analysis.json'))
  if not aa:continue
  data=json.loads(aa[-1].read_text());rec=data['records'];runs={p.name[:4]:json.loads(p.read_text()) for p in directory.glob('*-run.json')}
  source=next((r.get('tx_start') for r in runs.values() if r.get('tx_start')), {})
  groups={}
  for mode in sorted(set(r['mode'] for r in rec)):
   g={}
   for state in [True,False]:
    rr=[r for r in rec if r['mode']==mode and r['tx_on']==state];ss=[r['receiver_summary'] for r in rr if r['receiver_summary']]
    g['on' if state else 'off']=dict(n=len(rr),full_payload_buffers=sum(bool(r['decoder']['full_payload_matches']) for r in rr),
     address_crc_buffers=sum(any(h['crc_verified'] and h['address_verified'] for h in r['decoder']['full_payload_matches']) for r in rr),
     exact_header_buffers=sum(bool(r['decoder']['exact_sync_candidates']) for r in rr),
     candidate_rate=float(np.mean([s['detections']/(s['wall_elapsed_us']/1e6) for s in ss])) if ss else None,
     local_rf_duty=float(np.mean([s['nominal_rf_duty_percent'] for s in ss])) if ss else None,
     host_rf_duty=float(np.mean([s.get('nominal_host_rf_duty_percent',s.get('nominal_host_duty_percent')) for s in ss])) if ss else None)
   if g['on']['candidate_rate'] is not None:g['candidate_excess']=g['on']['candidate_rate']-g['off']['candidate_rate']
   groups[mode]=g
  timing=[]
  for r in runs.values():
   if not r['tx_on']:continue
   before=r.get('tx_before',{});after=r.get('tx_after',{})
   timing.append(dict(index=r['index'],missed_slots_delta=after.get('missed_slots',0)-before.get('missed_slots',0),completed_delta=after.get('completed',0)-before.get('completed',0),scheduled_delta=after.get('scheduled',0)-before.get('scheduled',0),timing_saturated=after.get('timing_saturated'),max_launch_lateness_us=after.get('launch_lateness_max_us'),max_completion_latency_us=after.get('completion_latency_max_us')))
  rows.append(dict(variant=directory.name,analysis=str(aa[-1]),records=len(rec),source_configuration={k:source.get(k) for k in ['mode_mbps','payload_len','power_dbm','frequency_mhz','interval_us','jitter_us','hop_list','burst_count','burst_gap_us']},aperture_us=sorted(set(r['metrics']['aperture_us'] for r in rec)),groups=groups,timing=timing))
 out=args.directory/('summary-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json');out.write_text(json.dumps(dict(variants=rows,cautions=['Three ON/OFF pairs per detector mode, one raw pair per variant.','Sequential one-factor screen is time-confounded and not calibrated sensitivity certification.','No candidate count is packet recall.','Only address plus complete payload plus CRC establishes complete-frame validation; 8-byte payload has no deterministic suffix beyond RFTX and unconstrained sequence.']),indent=2));print(out)
 for r in rows:
  print(r['variant'],r['aperture_us'],{m:dict(excess=g.get('candidate_excess'),payload=g['on']['full_payload_buffers'],crc=g['on']['address_crc_buffers'],offheaders=g['off']['exact_header_buffers']) for m,g in r['groups'].items()},'missed',sum(t['missed_slots_delta'] for t in r['timing']))
if __name__=='__main__':main()
