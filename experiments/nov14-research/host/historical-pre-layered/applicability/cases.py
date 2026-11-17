"""Three deterministic fake-clock cases only; no sleeps or device backends."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path('/home/jaykob/esp32-pex-bounded-adapter-v2/bounded-adapter-v2-final')
PINS = {'adapter.py': '65ed42c92550270358e2aeca385c58b7f74b9076109a931a13b0e5431254768d',
        'frozen-collector/collector.py': '4eb3232da0a302010e83fd1766934b38263cd307dbd3b68c62547e0fe2ca8e4d'}
mods = []
for name, (file, digest) in zip(['timeout_adapter', 'timeout_collector'], PINS.items()):
    assert hashlib.sha256((ROOT/file).read_bytes()).hexdigest() == digest
    spec = importlib.util.spec_from_file_location(name, ROOT/file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    mods.append(mod)
a, c = mods

class Clock:
    ns = 0
    def __call__(self): return self.ns / 1_000_000_000

class Fake:
    def __init__(self, clock, payload, full):
        self.__dict__.update(vars(a.Settings()))
        self.__dict__.update(timeout=None, write_timeout=None, is_open=True, in_waiting=0,
                             clock=clock, payload=payload, full=full, calls=0, armed=False)
    def __setattr__(self, key, val):
        if key == 'timeout' and self.__dict__.get('armed'):
            self.clock.ns += 1_000_000
        object.__setattr__(self, key, val)
    def read(self, n):
        self.calls += 1
        self.clock.ns += round(self.timeout * 1_000_000_000) if self.full else 10_000_000
        return self.payload

outputs = []
for name, payload, full in [('full_empty', b'', True), ('full_partial', b'x', True), ('early_empty', b'', False)]:
    clock = Clock(); backend = Fake(clock, payload, full)
    adapter = a.OpenObjectTransport(backend, exclusive_idle=True, clock=clock)
    # Exercise actual Collector.read/remaining/connection without constructor's
    # native verifier or session initialization: this is not a full collector run.
    collector = c.Collector.__new__(c.Collector)
    collector.transport = adapter; collector.clock = clock
    collector.token = adapter.connection_token
    collector.deadline = 45; collector.io_progress = 0
    collector.trust = True; collector.rx_total = 0
    collector.rx = bytearray()
    backend.armed = True
    error = None; delivered = None
    try: delivered = collector.read(2, 1)
    except a.AdapterError as e: error = e.code
    record = json.loads(adapter._records[0])
    if full:
        assert error == a.DEADLINE and not collector.trust
        assert delivered is None and record[11] == 0
        assert b''.join(adapter._rx) == payload and not collector.rx
        before = backend.calls
        try: adapter.read(1, .1)
        except a.AdapterError: pass
        else: raise AssertionError('poison did not reject')
        assert backend.calls == before
    else:
        assert error is None and delivered == b'' and collector.trust and record[11] == 1
    assert backend.timeout is None and backend.write_timeout is None
    outputs.append(dict(case=name, fake_elapsed_ns=clock.ns, backend_calls=backend.calls,
                        configured_wait_ns=100_000_000, error_code=error,
                        first_failure=adapter._first_code, collector_trust=collector.trust,
                        delivered_hex=None if delivered is None else delivered.hex(),
                        adapter_retained_hex=b''.join(adapter._rx).hex(), collector_rx_hex=collector.rx.hex(),
                        record=record, restored=True))
print(json.dumps({'scope':'three deterministic fakes; actual collector read methods only, no full session/native decoder/device',
                  'pins':PINS,'cases':outputs}, indent=2))
