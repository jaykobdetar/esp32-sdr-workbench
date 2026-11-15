"""One-capture injected-transport collector. No serial module or live adapter."""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED_IMAGE = "fc629ff663647f3e27c4b9494ef78e220ce74ac46cf5137ac8362edf3a73bea5"


def verification_disclosures(native, cap):
    """Report only: caller supplies an already verified native result, not source truth."""
    names = "status count sync_hits valid_hypotheses duplicates output_drops payload_rejects crc_rejects incomplete busy_syncs samples_processed differential_products symbol_decisions".split()
    counters = dict(zip(names, struct.unpack_from("<13I", native)))
    return {
        "native_counters": counters,
        "configured_output_cap": cap,
        "decoder_output_drops_present": counters["output_drops"] > 0,
        "native_result_byte_equal": True,
        "observed_body_records_checked": counters["count"],
        "observed_body_crc_consistent": True if counters["count"] else None,
        "symbol_support_evaluated": False,
        "source_association_evaluated": False,
        "transmitter_attestation": False,
        "counter_scope": "decoder hypotheses and retained records, not missed source packets",
        "verification_scope": "collection and replay verified; not full-support or source-truth certification",
    }


class CollectionError(Exception):
    pass


def reference():
    pins = json.loads((ROOT / "REFERENCE-PINS.json").read_text())
    for name, digest in pins.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise CollectionError("reference pin mismatch: " + name)
    folder = ROOT / "reference/research/paused_extract"
    # Exact frozen code, separate module names; no serial/device imports.
    for name, file in [
        ("observed_bits", "observed_bits.py"),
        ("pex_frozen_verifier", "verify.py"),
    ]:
        spec = importlib.util.spec_from_file_location(name, folder / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module, module.library(folder / "native")


class Collector:
    def __init__(
        self,
        transport,
        output,
        *,
        exclusive_idle=False,
        cap=64,
        mode="legacy",
        clock=time.monotonic,
        deadline_s=45,
        cancel_requested=lambda: False,
    ):
        if exclusive_idle is not True:
            raise CollectionError(
                "externally established idle/exclusive session required"
            )
        if type(cap) is not int or not 0 <= cap <= 64:
            raise CollectionError("invalid cap")
        if not 0 < deadline_s <= 45:
            raise CollectionError("invalid total deadline")
        if mode not in ("legacy", "compact"):
            raise CollectionError("explicit mode required")
        self.mode = mode
        self.transport = transport
        self.token = transport.connection_token
        if not isinstance(self.token, str) or not self.token:
            raise CollectionError("connection identity required")
        self.path = Path(output)
        self.path.mkdir(exist_ok=False)
        self.clock = clock
        self.deadline = clock() + deadline_s
        self.cap = cap
        self.cancel_requested = cancel_requested
        self.last = None
        self.pending = False
        self.trust = True
        self.retention = None
        self.last_retention = None
        self.retention_freed = False
        self.last_read_return = None
        self.io_progress = None
        self.released = False
        self.rx_total = 0
        self.rx = bytearray()
        self.tx = bytearray()
        self.events = []
        self.report = {
            "host_session": str(uuid.uuid4()),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "caller_idle_exclusive_assertion": True,
            "connection_token": self.token,
            "expected_application_sha256": EXPECTED_IMAGE,
            "image_attestation": "reported VERSION only, not flash attestation",
            "success": False,
            "selected_mode": self.mode,
            "cleanup": "not attempted",
            "errors": [],
        }
        self.v, self.lib = reference()
        import codec

        self.compact_codec = codec
        self.expected = json.loads((ROOT / "expected-version.json").read_text())

    def event(self, kind, **values):
        row = {"host_monotonic_s": self.clock(), "kind": kind, **values}
        self.events.append(row)
        with (self.path / "events.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")

    def connection(self):
        if self.transport.connection_token != self.token:
            self.trust = False
            raise CollectionError("connection changed; no reconnect cleanup")
        if not self.trust:
            raise CollectionError("connection no longer trusted")

    def remaining(self, limit):
        self.connection()
        left = self.deadline - self.clock()
        if left <= 0:
            self.trust = False
            raise CollectionError("total deadline")
        return min(limit, left)

    def quiet(self):
        self.connection()
        start = self.clock()
        try:
            extra = self.transport.read(1, 0)
        except BaseException:
            self.trust = False
            raise
        if not isinstance(extra, bytes) or len(extra) > 1:
            self.trust = False
            raise CollectionError("invalid nonblocking read")
        if extra:
            self.rx.extend(extra)
            self.rx_total += len(extra)
            with (self.path / "rx.bin").open("ab") as f:
                f.write(extra)
            self.event("unexpected_idle_byte", hex=extra.hex())
            self.trust = False
            raise CollectionError("unexpected queued output")
        if self.clock() - start > 0.01:
            self.trust = False
            raise CollectionError("nonblocking read blocked")
        self.connection()

    def send(self, data):
        timeout = self.remaining(1)
        if self.last is not None and self.clock() - self.last >= 4:
            self.trust = False
            raise CollectionError("ownership margin expired")
        if self.pending:
            raise CollectionError("transaction still pending")
        self.quiet()
        self.event("write_attempt", hex=data.hex())
        # Logging/quiet checks can stall: re-admit immediately before writing.
        timeout = self.remaining(1)
        if self.last is not None and self.clock() - self.last >= 4:
            self.trust = False
            raise CollectionError("ownership margin expired after prewrite work")
        self.pending = True
        started = self.clock()
        try:
            n = self.transport.write(data, timeout)
            returned = self.clock()
            self.io_progress = returned
        except BaseException:
            self.trust = False
            raise
        if type(n) is not int or not 0 <= n <= len(data):
            self.trust = False
            raise CollectionError("invalid write count")
        self.tx.extend(data[:n])
        (self.path / "tx.bin").write_bytes(self.tx)
        self.event("write_return", accepted=n, transport_return_monotonic_s=returned)
        if n != len(data) or returned - started > timeout:
            self.trust = False
            raise CollectionError("partial or late write")
        self.connection()
        if self.clock() - returned >= 4:
            self.trust = False
            raise CollectionError("postwrite persistence stalled")

    def read(self, n, deadline):
        if self.clock() >= deadline:
            self.trust = False
            raise CollectionError("read deadline")
        if self.io_progress is not None and self.clock() - self.io_progress >= 4:
            self.trust = False
            raise CollectionError("four-second IO silence")
        timeout = self.remaining(min(0.1, deadline - self.clock()))
        start = self.clock()
        try:
            data = self.transport.read(n, timeout)
            returned = self.clock()
        except BaseException:
            self.trust = False
            raise
        if not isinstance(data, bytes):
            self.trust = False
            raise CollectionError("invalid read result type")
        if len(data) > n:
            kept = data[: max(0, 150000 - self.rx_total)]
            self.rx.extend(kept)
            self.rx_total += len(kept)
            with (self.path / "rx.bin").open("ab") as f:
                f.write(kept)
            self.event(
                "oversized_transport_read", returned=len(data), preserved=len(kept)
            )
            self.trust = False
            raise CollectionError("invalid read size")
        if data:
            self.last_read_return = returned
            self.io_progress = returned
            self.rx.extend(data)
            self.rx_total += len(data)
            with (self.path / "rx.bin").open("ab") as f:
                f.write(data)
            self.event(
                "read",
                bytes=len(data),
                offset=len(self.rx) - len(data),
                transport_return_monotonic_s=returned,
            )
        if self.rx_total > 150000:
            self.trust = False
            raise CollectionError("session byte limit")
        if returned - start > timeout + 1e-6:
            self.trust = False
            raise CollectionError("transport exceeded read timeout")
        self.connection()
        if self.clock() - returned >= 4:
            self.trust = False
            raise CollectionError("postread persistence stalled")
        return data

    def exact(self, n, deadline):
        out = bytearray()
        while len(out) < n:
            out.extend(self.read(min(4096, n - len(out)), deadline))
        return bytes(out)

    def line(self, deadline, limit=512):
        out = bytearray()
        while len(out) < limit:
            c = self.read(1, deadline)
            if not c:
                continue
            out.extend(c)
            if c == b"\n":
                return bytes(out)
        raise CollectionError("oversized line")

    def complete(self):
        if self.last_read_return is None or self.clock() - self.last_read_return >= 4:
            self.trust = False
            raise CollectionError("response processing exceeded ownership margin")
        self.pending = False
        self.last = self.last_read_return

    def query(self, command, timeout=2):
        self.send(command)
        line = self.line(min(self.deadline, self.clock() + timeout))
        self.complete()
        if line.startswith(b"ERR "):
            self.trust = False
            raise CollectionError(
                "device rejected command: " + line.decode(errors="replace").strip()
            )
        return line

    def status(self):
        line = self.query(b"PEX?\n")
        m = re.fullmatch(rb"PEX 1 16380 64 ([0-9]+) ([0-9]+)\n", line)
        if not m:
            self.trust = False
            raise CollectionError("invalid PEX status")
        boot, gen = map(int, m.groups())
        if boot >= 2**64 or gen >= 2**64:
            self.trust = False
            raise CollectionError("status identity range")
        return boot, gen

    def frame(self, name):
        start = len(self.rx)
        limit = min(self.deadline, self.clock() + 22)
        head = self.line(limit)
        if head.startswith(b"PEXERR "):
            second = self.line(limit)
            raw = head + second
            # Error-looking bytes are not a completed response until BOTH lines
            # validate. Keep pending and revoke trust on malformed error output.
            try:
                failed_attempt = (
                    self.compact_codec.failed_attempt(raw, self.v)
                    if self.mode == "compact" and name == "result.bin"
                    else self.v.failed_attempt(raw)
                )
            except BaseException:
                self.trust = False
                raise
            self.complete()
            self.report["failed_attempt"] = failed_attempt
            self.report["failed_attempt"]["boot_identity_known"] = bool(
                self.report["failed_attempt"]["boot"]
            )
            raise CollectionError("firmware failed attempt")
        compact = self.mode == "compact" and name == "result.bin"
        match = (self.compact_codec.HEADER if compact else self.v.HEADER).fullmatch(
            head
        )
        if not match:
            raise CollectionError("invalid frame header")
        size = int(match[3] if compact else match[4])
        kind = 3 if compact else int(match[1])
        if (compact and not 52 <= size <= 1844) or (
            not compact and size != {1: 1844, 2: 65520}[kind]
        ):
            raise CollectionError("frame kind/size")
        body = self.exact(512 + size, limit)
        blank = self.line(limit)
        terminal = self.line(limit)
        cost = self.line(limit)
        raw = head + body + blank + terminal + cost
        (self.path / name).write_bytes(raw)
        metadata, _payload, _timing = (
            self.compact_codec.frame(raw, self.v) if compact else self.v.frame(raw)
        )
        self.complete()
        self.event(
            "frame_validated",
            file=name,
            rx_start=start,
            bytes=len(raw),
            frame_kind=kind,
            boot=metadata[2],
            generation=metadata[3],
        )
        return raw, metadata

    def guard(self):
        if self.retention is None or self.pending or not self.trust:
            return False
        if self.last is None or self.clock() - self.last >= 4:
            return False
        self.connection()
        if self.status() != self.retention:
            self.trust = False
            raise CollectionError("retention boot/generation changed")
        return True

    def release(self):
        if self.query(b"RELEASE\n") != b"OK\n":
            raise CollectionError("RELEASE not acknowledged")
        self.released = True
        self.quiet()

    def cleanup(self):
        if self.released or self.retention_freed:
            return
        try:
            if not self.guard():
                self.report["cleanup"] = "deferred: ambiguous state; no commands sent"
                return
            if self.query(b"STOP\n") != b"OK\n":
                raise CollectionError("STOP not acknowledged")
            self.retention = None
            self.retention_freed = True
            self.report["cleanup"] = "STOP acknowledged"
            self.release()
            self.report["cleanup"] = "STOP and RELEASE acknowledged"
        except BaseException as e:  # noqa: BLE001 - retain interrupted transaction evidence
            self.report["cleanup"] = "failed or unconfirmed"
            self.report["errors"].append("cleanup: " + repr(e))

    def run(self):
        try:
            line = self.query(b"VERSION?\n")
            if not line.startswith(b"VERSION "):
                raise CollectionError("missing VERSION")

            def unique(pairs):
                d = {}
                for k, value in pairs:
                    if k in d:
                        raise CollectionError("duplicate VERSION key")
                    d[k] = value
                return d

            actual = json.loads(line[8:], object_pairs_hook=unique)
            self.report["reported_version"] = actual
            if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(
                self.expected, sort_keys=True, allow_nan=False
            ):
                raise CollectionError("unexpected application identity")
            initial = self.status()
            self.report["initial_status"] = list(initial)
            if initial[1]:
                raise CollectionError("preexisting retention; no takeover")
            if self.mode == "compact":
                declared = self.compact_codec.capability(self.query(b"PEXCOMPACT2?\n"))
                if declared != initial:
                    raise CollectionError("capability/status identity mismatch")
            opcode = "PEXCOMPACT2" if self.mode == "compact" else "PEX"
            self.send(f"{opcode} {self.cap}\n".encode())
            result, rm = self.frame("result.bin")
            if (
                rm[:2] != ((2, 3) if self.mode == "compact" else (1, 1))
                or rm[6] != self.cap
                or (initial[0] and rm[2] != initial[0])
            ):
                raise CollectionError("result identity/config mismatch")
            self.retention = (rm[2], rm[3])
            self.last_retention = self.retention
            if self.cancel_requested():
                raise CollectionError("caller cancellation at safe boundary")
            self.send(f"PEXGET {rm[3]}\n".encode())
            iq, im = self.frame("iq.bin")
            paired = (
                rm[2:] == im[2:]
                if self.mode == "compact"
                else rm[:1] + rm[2:] == im[:1] + im[2:]
            )
            if im[:2] != (1, 2) or not paired:
                self.trust = False
                raise CollectionError("IQ identity/metadata mismatch")
            if self.cancel_requested():
                raise CollectionError("caller cancellation at safe boundary")
            if not self.guard():
                raise CollectionError("cleanup guard failed")
            if self.query(f"PEXDROP {rm[3]}\n".encode()) != b"OK\n":
                self.trust = False
                raise CollectionError("DROP not acknowledged")
            self.retention = None
            self.retention_freed = True
            self.report["cleanup"] = "DROP acknowledged"
            self.release()
            self.report["cleanup"] = "DROP and RELEASE acknowledged"
            self.report["verification"] = (
                self.compact_codec.verify_pair(result, iq, self.lib, self.v)
                if self.mode == "compact"
                else self.v.verify_pair(result, iq, self.lib)
            )
            # Only disclose counters after unchanged paired-IQ/native/observed-bit verification.
            verified_meta, verified_native, _ = (
                self.compact_codec.frame(result, self.v)
                if self.mode == "compact"
                else self.v.frame(result)
            )
            self.report["verification"].update(
                verification_disclosures(verified_native, verified_meta[6])
            )
            if self.clock() > self.deadline:
                raise CollectionError("verification exceeded total deadline")
            self.report["success"] = True
        except BaseException as e:  # noqa: BLE001 - retain interrupted transaction evidence
            self.report["errors"].append(repr(e))
            self.event("failure", error=repr(e))
            self.cleanup()
        finally:
            self.report.update(
                connection_trusted=self.trust,
                transaction_pending=self.pending,
                last_verified_retention_identity=list(self.last_retention)
                if self.last_retention
                else None,
                retention_release_acknowledged=self.retention_freed,
                retained_state="release acknowledged"
                if self.retention_freed
                else "unknown; no release acknowledged",
                release_acknowledged=self.released,
                finished_monotonic_s=self.clock(),
                rx_sha256=hashlib.sha256(self.rx).hexdigest(),
                tx_sha256=hashlib.sha256(self.tx).hexdigest(),
            )
            (self.path / "report.json").write_text(
                json.dumps(self.report, indent=2) + "\n"
            )
        return self.report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--port")
    p.add_argument("--expected-application-sha256")
    args = p.parse_args()
    if not args.execute:
        p.error(
            "no live adapter: use the injected core with externally verified idle/exclusive transport"
        )
    if not args.port or args.expected_application_sha256 != EXPECTED_IMAGE:
        p.error("explicit port and matching expected application identity required")
    p.error("live adapter intentionally unavailable; no port was opened")


if __name__ == "__main__":
    main()
