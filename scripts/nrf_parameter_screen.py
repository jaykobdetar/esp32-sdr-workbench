#!/usr/bin/env python3
"""One-factor controlled screening, not an exhaustive factorial sensitivity certification."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rx-port',required=True);parser.add_argument('--tx-port',required=True)
parser.add_argument('--rx-artifact',required=True);parser.add_argument('--output-directory',type=Path,required=True)
parser.add_argument('--geometry',required=True,help='Measured placement description; keep unchanged during screening')
a=parser.parse_args();out=a.output_directory;out.mkdir(parents=True,exist_ok=False)
variants=[
 ('reference',[]),('power-minus40',['--power-dbm','-40']),('power-minus20',['--power-dbm','-20']),('power-minus8',['--power-dbm','-8']),
 ('payload8',['--length','8']),('payload32',['--length','32']),('payload128',['--length','128']),
 ('interval10ms',['--interval-us','10000']),('rate40',['--rate-hz','40000000']),('rate80',['--rate-hz','80000000']),
 ('bandwidth24',['--bandwidth-mhz','24']),('threshold2',['--ratio-milli','2000']),('threshold8',['--ratio-milli','8000']),
 ('buffer8192',['--samples','8192']),('mode1',['--mode-mbps','1']),
 ('hopping',['--hop-list','2420,2440,2460','--hop-every','1']),('burst5',['--burst-count','5','--burst-gap-us','20000'])]
base=[sys.executable,'-m','nrf_campaigns.nrf_rf_campaign','--rx-port',a.rx_port,'--tx-port',a.tx_port,'--rx-artifact',a.rx_artifact,'--pairs','3','--raw-pairs','1','--milliseconds','1000','--power-dbm','0','--gain','60','--length','64','--interval-us','2000','--jitter-us','150','--geometry',a.geometry]
report={'started_ns':time.time_ns(),'status':'running','variants':[]}
try:
 for name,args in variants:
  cmd=base+['--output-directory',str(out/name)]+args
  row={'name':name,'command':cmd,'started_ns':time.time_ns()};report['variants'].append(row)
  (out/'screen.json').write_text(json.dumps(report,indent=2))
  with (out/f'{name}.log').open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
  row['ended_ns']=time.time_ns();row['status']='passed';print(name,'passed',flush=True)
 report['status']='passed'
except BaseException as e:report['status']='failed';report['error']=repr(e);raise
finally:report['ended_ns']=time.time_ns();(out/'screen.json').write_text(json.dumps(report,indent=2))
