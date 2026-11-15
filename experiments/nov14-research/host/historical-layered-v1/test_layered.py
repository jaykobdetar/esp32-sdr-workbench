"""Tiny scalar clock cases only. No native verifier/full collector session."""
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import adapter as a
from test_adapter import Fake, make, records

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('layered_collector', ROOT/'frozen-collector/collector.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class Clock:
    def __init__(self): self.ns = 0
    def __call__(self): return self.ns / 1e9

class TimedFake(Fake):
    def __init__(self, clock, payload=b'', setup=1_000_000, restore=1_000_000):
        super().__init__()
        self.clock, self.payload = clock, payload
        self.setup_ns, self.restore_ns = setup, restore
        self.duration = None
        self.assigned = []
        self.armed = False
    def __setattr__(self, key, value):
        if key in ('timeout', 'write_timeout') and self.__dict__.get('armed'):
            self.clock.ns += self.restore_ns if value is None else self.setup_ns
            if value is not None: self.assigned.append(value)
        super().__setattr__(key, value)
    def read(self, n):
        self.calls.append(('read', n))
        self.clock.ns += round(self.timeout * 1e9) if self.duration is None else self.duration
        return self.payload
    def write(self, data):
        self.calls.append(('write', data))
        self.clock.ns += round(self.write_timeout * 1e9) if self.duration is None else self.duration
        return len(data) if self.write_count is None else self.write_count


def setup(payload=b'', **kw):
    clock = Clock(); backend = TimedFake(clock, payload, **kw)
    transport = a.OpenObjectTransport(backend, exclusive_idle=True, clock=clock)
    backend.armed = True
    return clock, backend, transport


def collector(transport, clock, path):
    obj = c.Collector.__new__(c.Collector)
    obj.transport, obj.clock, obj.path = transport, clock, path
    obj.token = transport.connection_token
    obj.deadline, obj.io_progress = 45, 0
    obj.trust, obj.rx_total = True, 0
    obj.rx, obj.events = bytearray(), []
    obj.last_read_return = None
    return obj

class Layered(unittest.TestCase):
    def test_policy_integer_and_quiet(self):
        for t in [0, 8e-9, 17e-9, .1, 1.0]:
            req,b,i,ad,f,assigned = a.timeout_policy(t)
            self.assertEqual(ad,b//4);self.assertEqual(f,(7*b)//8)
            self.assertEqual(i,b//2 if t else 0)
            self.assertEqual(assigned,math.nextafter(i/1e9,0) if i else 0)
        for t in [1e-9, 7e-9]:
            with self.assertRaises(a.AdapterError): a.timeout_policy(t)
        self.assertEqual(a.timing_code(-1,100,50,25,87,setup=True),a.CLOCK_BACKWARD)
        self.assertEqual(a.timing_code(101,100,50,25,87,setup=False),a.DEADLINE)
        self.assertEqual(a.timing_code(88,100,50,25,87,setup=False),a.RETURN_HEADROOM)
        self.assertEqual(a.timing_code(87,100,50,25,87,setup=False),0)

    def test_setup_exact_and_late_no_io(self):
        for ns in [25_000_000,26_000_000]:
            clock,backend,t=setup(setup=ns)
            with self.assertRaises(a.AdapterError) as e:t.read(1,.1)
            self.assertEqual(e.exception.code,a.SETUP_HEADROOM)
            self.assertEqual(backend.calls,[])
            self.assertIsNone(backend.timeout)
        f,t=make()
        with self.assertRaises(a.AdapterError):t.read(1,1e-9)
        self.assertEqual(f.calls,[])

    def test_admission_encoding_before_getters(self):
        clock,backend,t=setup()
        real=a.encode_record
        def encode(v):
            if v==[a.MAX_U64]*24:clock.ns=25_000_000
            return real(v)
        with patch.object(a,'encode_record',encode):
            with self.assertRaises(a.AdapterError) as e:t.read(1,.1)
        self.assertEqual(e.exception.code,a.SETUP_HEADROOM)
        self.assertEqual(backend.assigned,[])
        self.assertEqual(backend.calls,[])

    def test_outer_overrun_and_restore_overrun(self):
        for duration,restore in [(110_000_000,1_000_000),(50_000_000,60_000_000)]:
            clock,backend,t=setup(b'x',restore=restore);backend.duration=duration
            with self.assertRaises(a.AdapterError) as e:t.read(2,.1)
            self.assertEqual(e.exception.code,a.DEADLINE)
            self.assertEqual(t._rx,[b'x'])
            self.assertEqual(records(t)[0][11],0)
            self.assertFalse(records(t)[0][16]&a.TIME_MISSING)
            self.assertIsNone(backend.timeout)

    def test_final_headroom_boundary_and_negative_clock(self):
        for total,ok in [(87_500_000,True),(87_500_001,False)]:
            clock,backend,t=setup();backend.duration=total-2_000_000
            if ok:self.assertEqual(t.read(1,.1),b'')
            else:
                with self.assertRaises(a.AdapterError) as e:t.read(1,.1)
                self.assertEqual(e.exception.code,a.RETURN_HEADROOM)
        clock,backend,t=setup(setup=-1)
        with self.assertRaises(a.AdapterError) as e:t.read(1,.1)
        self.assertEqual(e.exception.code,a.CLOCK_BACKWARD)
        self.assertFalse(backend.calls)

    def test_late_encoding_headroom(self):
        clock,backend,t=setup();backend.duration=1_000_000
        real=a.encode_record;advanced=False
        def encode(v):
            nonlocal advanced
            if v[1]==1 and v[2]==5 and not advanced:
                advanced=True;clock.ns=90_000_000
            return real(v)
        with patch.object(a,'encode_record',encode):
            with self.assertRaises(a.AdapterError) as e:t.read(1,.1)
        self.assertEqual(e.exception.code,a.RETURN_HEADROOM)
        self.assertEqual(records(t)[0][7],90_000_000)
        self.assertEqual(records(t)[0][11],0)

    def test_quiet_nonblocking_and_unexpected(self):
        for payload in [b'',b'x']:
            clock,backend,t=setup(payload)
            with tempfile.TemporaryDirectory() as folder:
                obj=collector(t,clock,Path(folder))
                if payload:
                    with self.assertRaises(c.CollectionError):obj.quiet()
                else:obj.quiet()
            self.assertEqual(backend.assigned,[0.0])
        clock,backend,t=setup(setup=2_500_000)
        with self.assertRaises(a.AdapterError):t.read(1,0)
        self.assertFalse(backend.calls)
        clock,backend,t=setup();backend.duration=11_000_000
        with self.assertRaises(a.AdapterError) as e:t.read(1,0)
        self.assertEqual(e.exception.code,a.DEADLINE)

    def test_writes_inner_partial_and_admission(self):
        for count in [None,0,1]:
            clock,backend,t=setup();backend.write_count=count
            if count is None:self.assertEqual(t.write(b'XX',1),2)
            else:
                with self.assertRaises(a.AdapterError):t.write(b'XX',1)
            self.assertEqual(backend.assigned,[math.nextafter(.5,0)])
            self.assertEqual(len(backend.calls),1)
            self.assertIsNone(backend.write_timeout)
        clock,backend,t=setup(setup=250_000_000)
        with self.assertRaises(a.AdapterError):t.write(b'X',1)
        self.assertFalse(backend.calls)

    def test_silence_not_reset_by_empty(self):
        clock,backend,t=setup()
        with tempfile.TemporaryDirectory() as folder:
            obj=collector(t,clock,Path(folder))
            self.assertEqual(obj.read(1,10),b'')
            self.assertEqual(obj.io_progress,0)
            clock.ns=4_000_000_000
            before=len(backend.calls)
            with self.assertRaises(c.CollectionError):obj.read(1,10)
            self.assertEqual(len(backend.calls),before)

    def test_receipt_schema_three(self):
        f,t=make();t.read(1,0);t.seal()
        with tempfile.TemporaryDirectory() as folder:
            r=t.export_audit(Path(folder)/'audit')
            self.assertEqual(r['schema'],3)
            self.assertEqual(r['timeout_policy'],a.TIMEOUT_POLICY)
            self.assertLessEqual((Path(folder)/'audit/receipt.json').stat().st_size,4096)

if __name__=='__main__':unittest.main()
