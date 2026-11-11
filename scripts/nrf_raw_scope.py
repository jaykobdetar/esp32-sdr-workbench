#!/usr/bin/env python3
"""Finite randomized direct-IQ RF contrast sweep; no packet-recall inference."""
import sys,json,time,random,argparse
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'nrf52840-transmitter/host'))
from rf_tx import Transmitter
from sdr_research.protocol import Radio
from sdr_research.recording import save_capture
p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--rx-port",required=True);p.add_argument("--tx-port",required=True)
p.add_argument('--output',type=Path,required=True);p.add_argument('--gains',type=int,nargs='+',default=[0,20,40,60,80]);p.add_argument('--powers',type=int,nargs='+',default=[0]);p.add_argument('--frequencies',type=int,nargs='+',default=[2440]);p.add_argument('--pairs',type=int,default=6);p.add_argument('--length',type=int,default=252);p.add_argument('--interval-us',type=int,default=1500);p.add_argument('--jitter-us',type=int,default=100);p.add_argument('--mode-mbps',type=int,default=2)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
report={'status':'running','host_start_ns':time.time_ns(),'settings':{**vars(a),'output':str(a.output)},'runs':[]}
def save():
 tmp=a.output/'results.tmp';tmp.write_text(json.dumps(report,indent=2));tmp.replace(a.output/'results.json')
r=Radio(a.rx_port);tx=None
rng=random.Random(52841)
try:
 tx=Transmitter(a.tx_port);report['tx_hello']=tx.hello();tx.stop();report['rx']=r.connect()
 for gain in a.gains:
  for power in a.powers:
   for freq in a.frequencies:
    tx.stop();tx.configure(frequency_mhz=2440,mode_mbps=a.mode_mbps,power_dbm=power,payload_len=a.length,interval_us=a.interval_us,jitter_us=a.jitter_us)
    r.configure(freq,16000000,12,gain,10)
    for pair in range(a.pairs):
     states=[False,True];rng.shuffle(states)
     for on in states:
      tx.stop()
      if on:tx.start(count=20000,duration_ms=5000)
      time.sleep(.07+rng.random()*.03)
      before=tx.status();start=time.monotonic_ns();c=r.capture(16380);end=time.monotonic_ns();after=tx.status()
      tx.stop();assert before['running']==on and after['running']==on and c.crc_ok
      row={'index':len(report['runs']),'gain':gain,'power_dbm':power,'rx_frequency_mhz':freq,'tx_on':on,'pair':pair,'tx_before':before,'tx_after':after,'crc_valid':bool(c.crc_ok),'capture_host_ns':end-start,'mean_power':float(np.mean(abs(c.iq)**2)),'peak_power':float(np.max(abs(c.iq)**2)),'rms':float(np.sqrt(np.mean(abs(c.iq)**2)))}
      c.metadata['controlled_source']=row
      row['sigmf']=str(save_capture(c,a.output/f"{row['index']:04d}-g{gain}-p{power}-f{freq}-{'on' if on else 'off'}"))
      report['runs'].append(row);save()
    print('gain',gain,'power',power,'frequency',freq,'runs',len(report['runs']),flush=True)
 report['status']='passed'
except BaseException as e:report['status']='failed';report['error']=repr(e);raise
finally:
 r.close()
 if tx:
  try:report['cleanup']=tx.stop();tx.close()
  except Exception as e:report['cleanup_error']=repr(e);report['status']='failed'
 report['host_end_ns']=time.time_ns();save()
