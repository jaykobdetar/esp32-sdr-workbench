import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import adapter as a


class Fake:
    def __init__(self):
        self.__dict__.update(vars(a.Settings()))
        self.timeout = self.write_timeout = None
        self.is_open = True
        self.in_waiting = 0
        self.calls = []
        self.queue = []
        self.write_count = None
        self.on_read = None
    def read(self, n):
        self.calls.append(('read', n))
        if self.on_read:
            self.on_read()
        return self.queue.pop(0) if self.queue else b''
    def write(self, b):
        self.calls.append(('write', b))
        return len(b) if self.write_count is None else self.write_count


def make(**limits):
    f = Fake()
    t = a.OpenObjectTransport(f, exclusive_idle=True, clock=lambda: 0,
                              limits=replace(a.AuditLimits(), **limits))
    return f, t


def records(t):
    return [json.loads(x) for x in t._records]


class Tests(unittest.TestCase):
    def test_schema_maximum(self):
        self.assertEqual(len(a.encode_record([a.MAX_U64] * 24)), 506)
        for bad in [True, 1.0, 1 << 64, -(1 << 63) - 1, 'x']:
            with self.assertRaises(a.AdapterError): a.encode_record([bad] * 24)
        self.assertLess(300128 * 512 + 2 * (215536 + 8192) + 2048 + 4096, 160 * 1024 * 1024)

    def test_operations_and_repeated_reject(self):
        f, t = make(operations=2)
        t.read(1, 0); t.read(1, 0)
        for _ in range(4):
            with self.assertRaises(a.AdapterError): t.write(b'X', 1)
        self.assertEqual(len(f.calls), 2)
        self.assertEqual(len(t._records), 2)
        self.assertEqual(len(t._terminal), 1)

    def test_empty_budget_clock_frozen(self):
        f, t = make(empty_reads=2)
        t.read(1, 0); t.read(1, 0)
        with self.assertRaises(a.AdapterError): t.read(1, 0)
        self.assertEqual(t._empty, 3)
        with self.assertRaises(a.AdapterError): t.read(1, 0)
        self.assertEqual(len(f.calls), 3)

    def test_one_byte_and_crossing(self):
        f, t = make(rx_bytes=3)
        f.queue = [b'a', b'', b'b', b'c', b'', b'de']
        for expected in [b'a', b'', b'b', b'c', b'']:
            self.assertEqual(t.read(4, 1), expected)
        with self.assertRaises(a.AdapterError): t.read(4, 1)
        self.assertEqual(b''.join(t._rx), b'abcde')
        self.assertEqual(records(t)[-1][11], 0)

    def test_write_budgets_and_partial(self):
        for limits in [{'writes': 1}, {'tx_bytes': 1}]:
            f, t = make(**limits)
            t.write(b'X', 1)
            with self.assertRaises(a.AdapterError): t.write(b'Y', 1)
            self.assertEqual(len(f.calls), 1)
        for count in [0, 1]:
            f, t = make()
            f.write_count = count
            with self.assertRaises(a.AdapterError): t.write(b'XY', 1)
            self.assertEqual(t._tx_n, 2)
            self.assertEqual(records(t)[0][10], count)

    def test_content_before_backend(self):
        f, t = make(content_bytes=6144 + 512 + 1)
        with self.assertRaises(a.AdapterError): t.write(b'X', 1)
        self.assertEqual(f.calls, [])
        self.assertEqual(t._ops, 0)

    def test_token_budget(self):
        f, t = make(token_checks=1)
        self.assertIsInstance(t.connection_token, str)
        with self.assertRaises(a.AdapterError): _ = t.connection_token
        f.is_open = False
        with self.assertRaises(a.AdapterError): t.write(b'X', 1)
        self.assertEqual(t._tokens, 1)

    def test_raw_survives_postread_clock(self):
        f, t = make()
        f.queue = [b'abc']
        def callback():
            t._clock = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        f.on_read = callback
        with self.assertRaises(KeyboardInterrupt): t.read(4, 1)
        self.assertEqual(b''.join(t._rx), b'abc')
        self.assertEqual(records(t)[0][11], 0)
        self.assertEqual(f.timeout, None)

    def test_raw_survives_restore_failure_and_clock(self):
        class Bad(Fake):
            def __setattr__(self, key, value):
                if key == 'timeout' and value is None and getattr(self, 'fail_restore', False):
                    raise OSError('restore')
                super().__setattr__(key, value)
        f = Bad()
        t = a.OpenObjectTransport(f, exclusive_idle=True, clock=lambda: 0)
        f.queue = [b'x']
        def callback():
            f.fail_restore = True
            t._clock = lambda: (_ for _ in ()).throw(ValueError('clock'))
        f.on_read = callback
        with self.assertRaises(ValueError): t.read(1, 1)
        self.assertEqual(t._rx, [b'x'])
        self.assertEqual(records(t)[0][15], a.RESTORE)
        self.assertEqual(records(t)[0][11], 0)

    def test_oversize_nonbytes_and_subclasses(self):
        f, t = make()
        f.queue = [b'abcdef']
        with self.assertRaises(a.AdapterError): t.read(2, 1)
        self.assertEqual(t._rx, [b'ab'])
        self.assertEqual(records(t)[0][8:10], [6, 2])
        class Evil(bytes):
            def __repr__(self): raise AssertionError()
        f, t = make(); f.queue = [Evil(b'a')]
        with self.assertRaises(a.AdapterError): t.read(1, 1)
        self.assertFalse(t._rx)
        f, t = make()
        with self.assertRaises(a.AdapterError): t.write(Evil(b'a'), 1)
        self.assertFalse(f.calls)

    def test_concurrent_latch_and_seal(self):
        f, t = make(); f.queue = [b'x']
        def callback():
            with self.assertRaises(a.AdapterError): t.seal()
            with self.assertRaises(a.AdapterError): t.write(b'Y', 1)
        f.on_read = callback
        with self.assertRaises(a.AdapterError): t.read(1, 1)
        self.assertEqual(t._rx, [b'x'])
        self.assertIsNone(f.timeout)
        self.assertEqual(records(t)[0][11], 0)
        t.seal(); before = list(t._terminal)
        t.seal()
        with self.assertRaises(a.AdapterError): t.read(1, 1)
        with self.assertRaises(a.AdapterError): _ = t.connection_token
        self.assertEqual(t._terminal, before)

    def test_encoding_failure_after_read(self):
        f, t = make(); f.queue = [b'x']
        real = a.encode_record
        def encode(v):
            if v[1] == 1 and v[2] == 5: raise MemoryError()
            return real(v)
        with patch.object(a, 'encode_record', encode):
            with self.assertRaises(MemoryError): t.read(1, 1)
        self.assertEqual(t._rx, [b'x'])
        self.assertFalse(t._audit_complete)

    def test_export_hashes_and_no_reuse(self):
        f, t = make(); f.queue = [b'a']
        t.read(1, 1); t.write(b'X', 1); t.seal()
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / 'audit'
            r = t.export_audit(dest)
            for name, item in r['files'].items():
                raw = (dest / name).read_bytes()
                self.assertEqual(len(raw), item['size'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item['sha256'])
            self.assertEqual((dest / 'rx.hex').read_bytes(), b'61')
            with self.assertRaises(a.AdapterError): t.export_audit(Path(folder) / 'again')

    def test_wrapper_exception_and_persistence(self):
        for export_fault in [False, True]:
            f, t = make(); f.queue = [b'x']
            original = KeyboardInterrupt()
            def invoke(ad, path):
                ad.read(1, 1)
                raise original
            with tempfile.TemporaryDirectory() as folder:
                if export_fault:
                    t.export_audit = lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
                with self.assertRaises(KeyboardInterrupt) as cm:
                    a.collect_with_audit(t, Path(folder) / 'session', invoke, status=a.CollectionStatus())
                self.assertIs(cm.exception, original)
                self.assertTrue(t._sealed)
                if not export_fault:
                    self.assertTrue((Path(folder) / 'session/adapter/receipt.json').exists())

    def test_wrapper_normal_and_export_failure(self):
        f, t = make()
        with tempfile.TemporaryDirectory() as folder:
            result = a.collect_with_audit(t, Path(folder) / 's', lambda ad, p: {'success': True}, status=a.CollectionStatus())
            self.assertTrue(result['collector']['success'])
        f, t = make()
        with tempfile.TemporaryDirectory() as folder:
            with patch('os.fsync', side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    a.collect_with_audit(t, Path(folder) / 's', lambda ad, p: {'success': True}, status=a.CollectionStatus())
            self.assertFalse((Path(folder) / 's/adapter/receipt.json').exists())
            self.assertTrue((Path(folder) / 's/adapter/operations.jsonl').exists())

    def test_original_exception_attribute_mutation_fails(self):
        class E(Exception):
            def __setattr__(self, name, value): raise RuntimeError('immutable')
        f, t = make(); original = E()
        t.export_audit = lambda *args, **kw: (_ for _ in ()).throw(OSError())
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(E) as cm:
                a.collect_with_audit(t, Path(folder) / 's', lambda ad, p: (_ for _ in ()).throw(original), status=a.CollectionStatus())
            self.assertIs(cm.exception, original)

    def test_hostile_exception_status_and_returned_false(self):
        class Hostile(Exception):
            def __str__(self): raise AssertionError('str')
            def __repr__(self): raise AssertionError('repr')
            def __setattr__(self, k, v): raise AssertionError('setattr')
        original = Hostile()
        f, t = make()
        status = a.CollectionStatus()
        t.export_audit = lambda *args, **kw: (_ for _ in ()).throw(OSError())
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(Hostile) as caught:
                a.collect_with_audit(t, Path(folder) / 's', lambda ad, p: (_ for _ in ()).throw(original), status=status)
            self.assertIs(caught.exception, original)
            self.assertTrue(status.collector_raised)
            self.assertTrue(status.persistence_attempted)
            self.assertFalse(status.persisted)
            self.assertEqual(status.failure_code, a.EXPORT)
        f, t = make()
        status = a.CollectionStatus()
        with tempfile.TemporaryDirectory() as folder:
            out = a.collect_with_audit(t, Path(folder) / 's', lambda ad, p: {'success': False}, status=status)
            self.assertFalse(out['success'])
            self.assertTrue(status.collector_returned)
            self.assertFalse(status.collector_raised)
            self.assertTrue(status.persisted)

    def test_swallowed_poison_never_wrapper_success(self):
        for fault in ['budget', 'partial_write']:
            f, t = make(operations=0) if fault == 'budget' else make()
            if fault == 'partial_write': f.write_count = 0
            def invoke(ad, path):
                try: ad.write(b'X', 1)
                except a.AdapterError: pass
                return {'success': True}
            status = a.CollectionStatus()
            with tempfile.TemporaryDirectory() as folder:
                result = a.collect_with_audit(t, Path(folder) / 's', invoke, status=status)
            self.assertFalse(result['success'])
            self.assertTrue(status.collector_success)
            self.assertTrue(status.in_memory_audit_complete)
            self.assertTrue(status.persisted)
            self.assertFalse(status.adapter_clean)
            self.assertNotEqual(result['adapter_audit']['first_failure'], 0)

    def test_reentrant_token_getter_poison(self):
        class Reentrant(Fake):
            def __getattribute__(self, name):
                if name == 'is_open':
                    hook = object.__getattribute__(self, '__dict__').get('hook')
                    if hook: hook()
                return super().__getattribute__(name)
        f = Reentrant()
        t = a.OpenObjectTransport(f, exclusive_idle=True, clock=lambda: 0)
        def hook():
            with self.assertRaises(a.AdapterError): t.read(1, 0)
        f.hook = hook
        with self.assertRaises(a.AdapterError): _ = t.connection_token
        self.assertTrue(t._failed)
        self.assertEqual(t._first_code, a.CONCURRENT)
        self.assertEqual(len(t._terminal), 1)
        self.assertEqual(f.calls, [])

    def test_final_deadline_is_not_missing_clock(self):
        f, t = make()
        f.queue = [b'x']
        f.on_read = lambda: setattr(t, '_clock', lambda: 2)
        with self.assertRaises(a.AdapterError) as caught: t.read(1, 1)
        self.assertEqual(caught.exception.code, a.DEADLINE)
        self.assertEqual(t._first_code, a.DEADLINE)
        r = records(t)[0]
        self.assertEqual(r[7], 2_000_000_000)
        self.assertEqual(r[15], a.DEADLINE)
        self.assertFalse(r[16] & a.TIME_MISSING)
        self.assertEqual(t._rx, [b'x'])

    def test_seal_linearization_and_export_contention(self):
        f, t = make()
        original_encode = a.encode_record
        def encode(v):
            if v[1] == 0 and v[2] == 8:
                with self.assertRaises(a.AdapterError) as caught: t.write(b'X', 1)
                self.assertEqual(caught.exception.code, a.SEALED)
                self.assertFalse(t._latch)
            return original_encode(v)
        with patch.object(a, 'encode_record', encode): t.seal()
        before = list(t._terminal)
        t._lock.acquire()
        try:
            with self.assertRaises(a.AdapterError): t.export_audit('must-not-create')
            with self.assertRaises(a.AdapterError): _ = t.connection_token
        finally: t._lock.release()
        self.assertFalse(t._latch)
        self.assertEqual(t._terminal, before)
        self.assertFalse(f.calls)
        f, t = make()
        t._latch = True
        t.seal()
        self.assertEqual(t._first_code, a.CONCURRENT)
        self.assertEqual(json.loads(t._terminal[-1])[14], a.CONCURRENT)

if __name__ == '__main__': unittest.main()
