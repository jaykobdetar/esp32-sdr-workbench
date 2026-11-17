"""Exactly three approved deterministic comparisons. No full session or native load."""
import hashlib
import json
import tempfile
from pathlib import Path
from test_layered import setup, collector, records
import adapter as a
ROOT=Path(__file__).resolve().parent
out=ROOT/'corrected-three.json'
if out.exists():raise SystemExit('existing comparison receipt; no rerun')
rows=[]
for name,payload,full in [('full_empty',b'',True),('full_partial',b'x',True),('early_empty',b'',False)]:
    clock,backend,t=setup(payload)
    if not full:backend.duration=10_000_000
    with tempfile.TemporaryDirectory() as folder:
        obj=collector(t,clock,Path(folder))
        delivered=obj.read(2,1)
        assert delivered==payload and obj.trust and not t._failed
        assert backend.timeout is None and backend.write_timeout is None
        assert obj.rx==payload
        assert obj.io_progress==(clock.ns/1e9 if payload else 0)
        rows.append({'case':name,'elapsed_ns':clock.ns,'assigned_seconds_hex':backend.assigned[0].hex(),
                     'assigned_seconds':backend.assigned[0],'backend_calls':len(backend.calls),
                     'delivered_hex':delivered.hex(),'adapter_retained_hex':b''.join(t._rx).hex(),
                     'collector_rx_hex':obj.rx.hex(),'collector_io_progress':obj.io_progress,
                     'collector_events':obj.events,'record':records(t)[0],'restored':True,
                     'first_failure':t._first_code})
receipt={'scope':'exactly three deterministic fake-clock comparisons; actual Collector.read but no constructor/native/full session',
         'adapter_sha256':hashlib.sha256((ROOT/'adapter.py').read_bytes()).hexdigest(),
         'collector_sha256':hashlib.sha256((ROOT/'frozen-collector/collector.py').read_bytes()).hexdigest(),
         'policy':a.TIMEOUT_POLICY,'cases':rows}
with out.open('x') as f:json.dump(receipt,f,indent=2);f.write('\n')
print(json.dumps(receipt,indent=2))
