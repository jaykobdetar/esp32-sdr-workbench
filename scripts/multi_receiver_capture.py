#!/usr/bin/env python3
"""Read a finite JSON receiver plan; dry-run by default, --run opens hardware."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sdr_research.multireceiver import ReceiverConfig, describe_plan, run_plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True,help='JSON array of ReceiverConfig objects')
    p.add_argument('--output-directory',type=Path,help='New directory required with --run')
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--run',action='store_true',help='Explicitly open configured receiver ports')
    mode.add_argument('--dry-run',action='store_true',help='Validate and print without hardware (default)')
    a=p.parse_args()
    values=json.loads(a.plan.read_text())
    if not isinstance(values,list):p.error('Plan must be a JSON array')
    try:
        configs=[ReceiverConfig(**value) for value in values]
        description=describe_plan(configs)
    except (TypeError,ValueError) as exc:p.error(str(exc))
    if not a.run:
        print(description);return 0
    if a.output_directory is None:p.error('--run requires --output-directory')
    result=run_plan(configs,output_directory=a.output_directory)
    (a.output_directory/'results.json').write_text(json.dumps(result,indent=2))
    for receiver in result['receivers']:
        print(f'{receiver["receiver_id"]}: {receiver["status"]}; {len(receiver["captures"])} CRC-valid captures')
        if receiver.get('error'):print(receiver['error'])
    print(result['timing_note'])
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
