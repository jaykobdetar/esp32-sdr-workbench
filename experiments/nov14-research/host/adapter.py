"""Bounded injected already-open transport. No serial import or live entrypoint."""
import hashlib
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


class AdapterError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('bounded adapter failure code ' + str(code))


@dataclass(frozen=True)
class Settings:
    baudrate: int = 1_000_000
    bytesize: int = 8
    parity: str = 'N'
    stopbits: int = 1
    xonxoff: bool = False
    rtscts: bool = False
    dsrdtr: bool = False
    inter_byte_timeout: object = None


@dataclass(frozen=True)
class AuditLimits:
    operations: int = 300128
    writes: int = 64
    tx_bytes: int = 8192
    rx_bytes: int = 150000
    empty_reads: int = 150000
    token_checks: int = 1000000
    content_bytes: int = 160 * 1024 * 1024


# Schema errors and stages are closed enums. No exception text/type introspection.
ARG, SEALED, POISON, CONCURRENT, BUDGET, SETTINGS, SETUP, BACKEND = range(1, 9)
RETURN, DEADLINE, RESTORE, CLOCK, AUDIT, INTERRUPT, EXPORT, COLLECTOR, UNKNOWN = range(9, 18)
# Flags: incomplete, return unknown, truncated, timeout unknown, time missing,
# concurrent poison, persistence unknown. Stages: 0 admitted,1 setup,2 I/O,
# 3 returned,4 restored,5 committed,6 failed,7 first poison,8 sealed.
INCOMPLETE, RETURN_UNKNOWN, TRUNCATED, TIMEOUT_UNKNOWN, TIME_MISSING, RACE, PERSIST_UNKNOWN = [1 << n for n in range(7)]
SETUP_HEADROOM, RETURN_HEADROOM, CLOCK_BACKWARD = 18, 19, 20
OUTER_OVERRUN_OBSERVED = 1 << 7
CLOCK_REVERSED_OBSERVED = 1 << 8
TIMEOUT_POLICY = 'HALF_WAIT_QUARTER_SETUP_V1'


def timeout_policy(timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 1:
        raise AdapterError(ARG)
    requested = int(timeout * 1_000_000_000)
    b = requested if timeout else 10_000_000
    if b < 8:
        raise AdapterError(SETUP_HEADROOM)
    i = b // 2 if timeout else 0
    a, f = b // 4, (7 * b) // 8
    assigned = math.nextafter(i / 1_000_000_000, 0.0) if i else 0.0
    return requested, b, i, a, f, assigned


def timing_code(elapsed, b, i, a, f, *, setup):
    if elapsed < 0:
        return CLOCK_BACKWARD
    if elapsed > b:
        return DEADLINE
    if setup:
        if elapsed >= a or b - elapsed < i + (f - a - i) + (b - f):
            return SETUP_HEADROOM
    elif elapsed > f:
        return RETURN_HEADROOM
    return 0


MAX_U64 = (1 << 64) - 1
TERMINAL_RESERVE = 2048
RECEIPT_RESERVE = 4096


def encode_record(values):
    if type(values) is not list or len(values) != 24:
        raise AdapterError(AUDIT)
    for x in values:
        if x is not None and (type(x) is not int or not -(1 << 63) <= x <= MAX_U64):
            raise AdapterError(AUDIT)
    b = (json.dumps(values, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    if len(b) > 512:
        raise AdapterError(AUDIT)
    return b


class OpenObjectTransport:
    def __init__(self, backend, *, exclusive_idle=False, expected=Settings(),
                 limits=AuditLimits(), clock=time.monotonic):
        if exclusive_idle is not True or type(expected) is not Settings or type(limits) is not AuditLimits:
            raise AdapterError(ARG)
        for k, v in vars(limits).items():
            if type(v) is not int or not 0 <= v <= getattr(AuditLimits(), k):
                raise AdapterError(ARG)
        if limits.content_bytes < TERMINAL_RESERVE + RECEIPT_RESERVE:
            raise AdapterError(ARG)
        if type(expected.baudrate) is not int or expected.baudrate <= 0:
            raise AdapterError(ARG)
        for k, v in vars(Settings()).items():
            if type(getattr(expected, k)) is not type(v):
                raise AdapterError(ARG)
        self._backend, self._expected, self._limits, self._clock = backend, expected, limits, clock
        self._lock = threading.Lock()
        self._failed = self._sealed = self._latch = self._exported = False
        self._audit_complete = True
        self._clock_fault = False
        self._token = str(uuid.uuid4())
        self._records, self._rx, self._tx, self._terminal = [], [], [], []
        self._ops = self._writes = self._tx_n = self._rx_n = self._empty = self._tokens = 0
        self._used = self._rx_hex = self._tx_hex = 0
        self._first_code = 0
        self._settings()
        pending = backend.in_waiting
        if type(pending) is not int or pending != 0:
            raise AdapterError(SETTINGS)
        self._original = (backend.timeout, backend.write_timeout)
        for x in self._original:
            if x is not None and (type(x) not in (int, float) or not math.isfinite(x) or x < 0):
                raise AdapterError(SETTINGS)

    def _settings(self):
        if self._backend.is_open is not True:
            raise AdapterError(SETTINGS)
        for k, v in vars(self._expected).items():
            x = getattr(self._backend, k)
            if type(x) is not type(v) or x != v:
                raise AdapterError(SETTINGS)

    def _available(self):
        if self._sealed:
            raise AdapterError(SEALED)
        if self._failed or self._latch:
            raise AdapterError(POISON)

    def _poison(self, code):
        self._failed = True
        if not self._first_code:
            self._first_code = code
            r = [None] * 24
            r[1], r[2], r[14] = 0, 7, code
            try:
                self._terminal.append(encode_record(r))
            except BaseException:
                self._audit_complete = False

    def _acquire(self):
        if not self._lock.acquire(blocking=False):
            if self._sealed:
                raise AdapterError(SEALED)
            self._latch = True
            raise AdapterError(CONCURRENT)

    @property
    def connection_token(self):
        self._acquire()
        try:
            self._available()
            if self._tokens >= self._limits.token_checks:
                raise AdapterError(BUDGET)
            self._tokens += 1
            self._settings()
            if self._latch:
                raise AdapterError(CONCURRENT)
            return self._token
        except BaseException as e:
            if not self._sealed:
                self._poison(e.code if type(e) is AdapterError else SETTINGS)
            raise
        finally:
            self._lock.release()

    def _ns(self):
        try:
            x = self._clock()
            if type(x) not in (int, float) or not math.isfinite(x):
                raise AdapterError(CLOCK)
            n = int(x * 1_000_000_000)
            if not -(1 << 63) <= n < (1 << 63):
                raise AdapterError(CLOCK)
            return n
        except BaseException:
            self._clock_fault = True
            raise

    def read(self, size, timeout_s):
        return self._operation(1, size, timeout_s)

    def write(self, data, timeout_s):
        return self._operation(2, data, timeout_s)

    def _operation(self, op, arg, timeout):
        self._acquire()
        r = None
        primary = secondary = None
        raw = b''
        attempted = False
        previous = None
        result = None
        prop = 'timeout' if op == 1 else 'write_timeout'
        stage = 0
        try:
            self._available()
            self._clock_fault = False
            start = self._ns()  # after owner lock, before admission/encoding, no backend getters
            last_observed = start
            def validate_observation(now):
                nonlocal last_observed
                if now < last_observed:
                    raise AdapterError(CLOCK_BACKWARD)
                last_observed = now
                return now
            requested, budget, inner, admit, finish, assigned = timeout_policy(timeout)
            if op == 1:
                if type(arg) is not int or not 0 <= arg <= 65536:
                    raise AdapterError(ARG)
                size = arg
            else:
                if type(arg) is not bytes or not 1 <= len(arg) <= 128:
                    raise AdapterError(ARG)
                size = len(arg)
            reserve = 512 + 2 * size
            lim = self._limits
            if self._ops >= lim.operations or self._used + reserve + TERMINAL_RESERVE + RECEIPT_RESERVE > lim.content_bytes:
                raise AdapterError(BUDGET)
            if op == 2 and (self._writes >= lim.writes or self._tx_n + size > lim.tx_bytes):
                raise AdapterError(BUDGET)
            # Validate eventual scalar maximum before touching backend.
            encode_record([MAX_U64] * 24)
            self._ops += 1
            r = [None] * 24
            r[0:5] = [self._ops, op, 0, size, requested]
            r[11:17] = [0, self._rx_hex, self._tx_hex, 0, 0, 0]
            r[22:24] = [512, 2 * size]
            if op == 2:
                self._writes += 1
                self._tx_n += size
                self._tx.append(arg)
                self._tx_hex += 2 * size
            r[5] = start
            def check_setup():
                code = timing_code(validate_observation(self._ns()) - start, budget, inner, admit, finish, setup=True)
                if code:
                    raise AdapterError(code)
            check_setup()
            self._settings()
            if (self._backend.timeout, self._backend.write_timeout) != self._original:
                raise AdapterError(SETTINGS)
            previous = getattr(self._backend, prop)
            check_setup()
            attempted = True
            stage = 1
            setattr(self._backend, prop, assigned)
            if getattr(self._backend, prop) != assigned:
                raise AdapterError(SETUP)
            self._settings()
            check_setup()
            if self._latch:
                raise AdapterError(CONCURRENT)
            stage = 2
            result = self._backend.read(arg) if op == 1 else self._backend.write(arg)
            # Keep reference before clock/getters. There is an unavoidable interruption gap.
            raw = result if op == 1 and type(result) is bytes else b''
            stage = 3
            if op == 1:
                if type(result) is not bytes:
                    r[16] |= RETURN_UNKNOWN
                    raise AdapterError(RETURN)
                r[8] = len(raw)
                if len(raw) > size:
                    raw = raw[:size]
                    r[16] |= TRUNCATED | INCOMPLETE
                self._rx.append(raw)
                r[9] = len(raw)
                self._rx_n += len(raw)
                self._rx_hex += 2 * len(raw)
                if len(result) > size:
                    raise AdapterError(RETURN)
                if not raw:
                    self._empty += 1
                if self._rx_n > lim.rx_bytes or self._empty > lim.empty_reads:
                    raise AdapterError(BUDGET)
            else:
                if type(result) is not int or not 0 <= result <= size:
                    raise AdapterError(RETURN)
                r[8] = r[10] = result
                if result != size:
                    raise AdapterError(RETURN)
            r[6] = self._ns()
            validate_observation(r[6])
            self._settings()
        except BaseException as e:
            primary = e
            code = e.code if type(e) is AdapterError else (CLOCK if self._clock_fault else INTERRUPT if isinstance(e, (KeyboardInterrupt, SystemExit)) else BACKEND)
            if r is not None:
                r[14] = code
                if code == CLOCK_BACKWARD:
                    r[16] |= CLOCK_REVERSED_OBSERVED
                if code == DEADLINE:
                    r[16] |= OUTER_OVERRUN_OBSERVED
                if self._clock_fault:
                    r[16] |= TIME_MISSING
                if stage == 2 or (op == 1 and stage == 3 and r[9] is None):
                    r[16] |= INCOMPLETE | RETURN_UNKNOWN
            if not self._sealed:
                self._poison(code)
        finally:
            if attempted:
                try:
                    setattr(self._backend, prop, previous)
                    if getattr(self._backend, prop) != previous or (self._backend.timeout, self._backend.write_timeout) != self._original:
                        raise AdapterError(RESTORE)
                    stage = 4
                except BaseException as e:
                    secondary = e
                    if r is not None:
                        r[15] = RESTORE
                        r[16] |= TIMEOUT_UNKNOWN
                    self._poison(RESTORE)
            if r is not None:
                def observe_final():
                    nonlocal secondary
                    end = None
                    try:
                        end = self._ns()
                        r[7] = end - start  # last observed elapsed checkpoint, not method-return latency
                        validate_observation(end)
                        code = timing_code(r[7], budget, inner, admit, finish, setup=False)
                        if code:
                            raise AdapterError(code)
                    except BaseException as e:
                        code = e.code if type(e) is AdapterError else CLOCK
                        if code == DEADLINE:
                            r[16] |= OUTER_OVERRUN_OBSERVED
                        if code == CLOCK_BACKWARD:
                            r[16] |= CLOCK_REVERSED_OBSERVED
                        if secondary is None or (code == DEADLINE and type(secondary) is AdapterError and secondary.code == RETURN_HEADROOM):
                            secondary = e
                            r[15] = code
                        if end is None:
                            r[16] |= TIME_MISSING
                        self._poison(code)
                observe_final()
                if self._latch:
                    r[16] |= RACE
                    if primary is None:
                        primary = AdapterError(CONCURRENT)
                        r[14] = CONCURRENT
                    self._poison(CONCURRENT)
                if r[16] & (INCOMPLETE | RETURN_UNKNOWN):
                    self._audit_complete = False
                r[11] = int(primary is None and secondary is None and not self._failed)
                r[2] = 5 if r[11] else 6
                r[17:22] = [self._ops, self._empty, self._rx_n, self._tx_n, self._tokens]
                try:
                    encode_record(r)  # bounded first encoding is included in the last observation
                    observe_final()
                    if self._latch:
                        r[16] |= RACE
                        if primary is None:
                            primary = AdapterError(CONCURRENT)
                            r[14] = CONCURRENT
                        self._poison(CONCURRENT)
                    r[11] = int(primary is None and secondary is None and not self._failed)
                    r[2] = 5 if r[11] else 6
                    encoded = encode_record(r)  # final encoding/commit/return rely on reserved headroom
                    self._records.append(encoded)
                    self._used += len(encoded) + 2 * (len(raw) if op == 1 else size)
                except BaseException as e:
                    self._audit_complete = False
                    self._poison(AUDIT)
                    if primary is None:
                        primary = e
            self._lock.release()
        if primary is not None:
            raise primary
        if secondary is not None:
            raise secondary
        return result

    def seal(self):
        self._acquire()
        try:
            if self._sealed:
                return
            # Admission closes here, before snapshot encoding or any callback.
            self._sealed = True
            if self._latch:
                self._poison(CONCURRENT)
            r = [None] * 24
            r[1], r[2], r[14] = 0, 8, self._first_code
            r[17:22] = [self._ops, self._empty, self._rx_n, self._tx_n, self._tokens]
            try:
                self._terminal.append(encode_record(r))
            except BaseException:
                self._audit_complete = False
                raise
        finally:
            self._lock.release()

    def export_audit(self, destination, *, collector_returned=False, collector_raised=False):
        self._acquire()
        try:
            if not self._sealed or self._exported:
                raise AdapterError(EXPORT)
            if type(collector_returned) is not bool or type(collector_raised) is not bool:
                raise AdapterError(ARG)
            self._exported = True
            root = Path(destination)
            root.mkdir()  # exclusive fresh subdirectory, never reuse or clean
            files = {}
            for name, items, as_hex in [('operations.jsonl', self._records, False), ('terminal.jsonl', self._terminal, False), ('rx.hex', self._rx, True), ('tx.hex', self._tx, True)]:
                h = hashlib.sha256()
                n = 0
                with (root / name).open('xb') as f:
                    for b in items:
                        part = b.hex().encode('ascii') if as_hex else b
                        written = f.write(part)
                        if written != len(part):
                            raise AdapterError(EXPORT)
                        h.update(part)
                        n += len(part)
                    f.flush()
                    import os
                    os.fsync(f.fileno())
                files[name] = {'size': n, 'sha256': h.hexdigest()}
            receipt = {'schema': 3, 'timeout_policy': TIMEOUT_POLICY, 'host_session': self._token, 'files': files,
                       'operations': self._ops, 'rx_bytes': self._rx_n, 'tx_bytes': self._tx_n,
                       'empty_reads': self._empty, 'token_checks': self._tokens,
                       'collector_returned': collector_returned, 'collector_raised': collector_raised,
                       'in_memory_audit_complete': self._audit_complete,
                       'persisted_files_complete': True, 'first_failure': self._first_code}
            payload = (json.dumps(receipt, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
            if len(payload) > RECEIPT_RESERVE:
                raise AdapterError(EXPORT)
            with (root / 'receipt.json').open('xb') as f:
                if f.write(payload) != len(payload):
                    raise AdapterError(EXPORT)
                f.flush()
                os.fsync(f.fileno())
            return receipt
        finally:
            self._lock.release()


@dataclass
class CollectionStatus:
    used: bool = False
    collector_returned: bool = False
    collector_raised: bool = False
    collector_success: object = None
    sealed: bool = False
    persistence_attempted: bool = False
    persisted: bool = False
    in_memory_audit_complete: bool = False
    adapter_clean: bool = False
    failure_code: int = 0
    success: bool = False


def collect_with_audit(adapter, destination, invoke, *, status):
    """One callback; caller-owned status survives even hostile exception objects."""
    if type(status) is not CollectionStatus or status.used is not False:
        raise AdapterError(ARG)
    status.used = True
    root = Path(destination)
    try:
        root.mkdir()
    except BaseException:
        status.failure_code = EXPORT
        raise
    original = persistence = None
    result = receipt = None
    try:
        result = invoke(adapter, root / 'collector')
        status.collector_returned = True
        status.collector_success = (result.get('success') is True) if type(result) is dict else None
    except BaseException as e:
        original = e
        status.collector_raised = True
        status.failure_code = COLLECTOR
    finally:
        try:
            adapter.seal()
            status.sealed = True
            status.persistence_attempted = True
            receipt = adapter.export_audit(root / 'adapter', collector_returned=status.collector_returned,
                                           collector_raised=status.collector_raised)
            status.persisted = True
            status.in_memory_audit_complete = receipt['in_memory_audit_complete']
            status.adapter_clean = receipt['first_failure'] == 0
            if not status.adapter_clean and status.failure_code == 0:
                status.failure_code = receipt['first_failure']
        except BaseException as e:
            persistence = e
            status.failure_code = EXPORT
    if original is not None:
        raise original  # never call str/repr or mutate an arbitrary exception
    if persistence is not None:
        raise persistence
    if not status.in_memory_audit_complete:
        status.failure_code = AUDIT
        raise AdapterError(AUDIT)
    status.success = status.collector_success is True and status.persisted and status.adapter_clean
    return {'success': status.success, 'collector': result, 'adapter_audit': receipt}
