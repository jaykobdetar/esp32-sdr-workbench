#!/usr/bin/env python3
"""Counterbalanced strongest/reservoir controlled trial; never flashes hardware."""
from nrf_campaigns import nrf_rf_campaign as c

def main():
 p=c.parser();p.description=__doc__;p.set_defaults(pairs=12,raw_pairs=0,gain=60,power_dbm=0,length=64,interval_us=2000,jitter_us=150)
 a=p.parse_args();a.receiver_modes=['strongest','reservoir'];a.expected_variant='esp32-pipeline-retention-experiment'
 from nrf_tx.rf_tx import Transmitter
 r=c.Radio(a.rx_port)
 try:
  with Transmitter(a.tx_port) as t:report=c.execute(a,r,t)
  return 0 if report['status']=='passed' else 1
 finally:r.close()
if __name__=='__main__':raise SystemExit(main())
