import tempfile
import unittest
from pathlib import Path

import codec
from test_collector import Fake

import collector


class CompactFake(Fake):
    def __init__(self):
        super().__init__()
        self.v, _ = collector.reference()
        m, n, t = self.v.frame(self.result)
        p = codec.compact_prefix(n, m[6])
        m = (2, 3) + m[2:]
        import struct
        import zlib

        b = struct.pack("<64Q", *m) + p
        self.result = (
            f"PEXFRAME 2 3 {m[2]} {m[3]} 512 {len(p)} {zlib.crc32(b):08x}\n".encode()
            + b
            + f"\nPEXEND 2 3 {m[2]} {m[3]}\nPEXCOST 2 3 {m[3]} {t[0]} {t[1]}\n".encode()
        )
        self.cap_reply = None

    def write(self, data, timeout_s):
        if (data.startswith(b"PEXCOMPACT2 ") and self.mode == "compact_error") or (
            data.startswith(b"PEXGET ") and self.mode == "get_error"
        ):
            import zlib

            raw = (
                Path(__file__).resolve().parent / "mock-result.bin.error"
            ).read_bytes()
            lines = []
            for line in raw.splitlines():
                fields = line.rsplit(b" ", 1)[0].split(b" ")
                fields[1] = b"2" if self.mode == "compact_error" else b"1"
                if self.mode == "compact_error":
                    fields[2] = b"0"
                prefix = b" ".join(fields)
                lines.append(prefix + f" {zlib.crc32(prefix):08x}\n".encode())
            self.commands.append(data)
            self.queue.extend(b"".join(lines))
            self.retained = False
            return len(data)
        if data == b"PEXCOMPACT2?\n":
            self.commands.append(data)
            self.queue.extend(
                self.cap_reply
                if self.cap_reply is not None
                else f"PEXCOMPACT2 2 3 512 52 28 64 LEGACY1 {self.boot} 0\n".encode()
            )
            return len(data)
        if data.startswith(b"PEXCOMPACT2 "):
            # Reuse the frozen fake transport fault injection; retain actual opcode.
            n = super().write(data.replace(b"PEXCOMPACT2 ", b"PEX ", 1), timeout_s)
            self.commands[-1] = data
            return n + 8
        return super().write(data, timeout_s)


class Tests(unittest.TestCase):
    def collect(self, f=None, cancel=lambda: False, event_stall=False):
        f = f or CompactFake()
        root = Path(__file__).resolve().parent / "test-runs"
        root.mkdir(exist_ok=True)
        out = Path(tempfile.mkdtemp(dir=root)) / "session"
        c = collector.Collector(
            f,
            out,
            exclusive_idle=True,
            mode="compact",
            clock=f.clock,
            cancel_requested=cancel,
        )
        if event_stall:
            original = c.event

            def event(name, **kw):
                if name == "write_attempt" and b"PEXGET" in bytes.fromhex(
                    kw.get("hex", "")
                ):
                    f.now += 5.5
                return original(name, **kw)

            c.event = event
        return c.run(), f

    def test_normal_replay(self):
        r, f = self.collect()
        self.assertTrue(r["success"], r)
        self.assertEqual(r["verification"]["observed_records"], 3)
        self.assertIn(b"PEXCOMPACT2?\n", f.commands)
        self.assertIn(b"PEXCOMPACT2 64\n", f.commands)
        self.assertNotIn(b"PEX 64\n", f.commands)

    def test_unknown_capability_no_capture(self):
        for response in (
            b"ERR\n",
            b"x\n",
            b"PEXCOMPACT2 2 3 512 52 28 64 LEGACY1 0 0\n",
        ):
            f = CompactFake()
            f.cap_reply = response
            r, f = self.collect(f)
            self.assertFalse(r["success"])
            self.assertNotIn(b"PEXCOMPACT2 64\n", f.commands)

    def test_zero_boot_initialization(self):
        f = CompactFake()
        actual = f.boot
        f.boot = 0

        def after(cmd):
            if cmd == b"PEX 64\n":
                f.boot = actual

        f.after_command = after
        r, f = self.collect(f)
        self.assertTrue(r["success"], r)

    def test_faults_no_fallback(self):
        for mode in (
            "truncated",
            "missing_cost",
            "bad_crc",
            "oversized",
            "partial_write",
            "drop_failure",
            "release_failure",
            "stale_gen",
            "stale_boot",
            "lost_owner",
        ):
            f = CompactFake()
            f.mode = mode
            r, f = self.collect(f)
            self.assertFalse(r["success"], mode)
            self.assertNotIn(b"PEX 64\n", f.commands)
            self.assertEqual(f.commands.count(b"PEXCOMPACT2 64\n"), 1)

    def test_logging_stall_no_get(self):
        r, f = self.collect(event_stall=True)
        self.assertFalse(r["success"])
        self.assertFalse(any(x.startswith(b"PEXGET") for x in f.commands))

    def test_operation_errors(self):
        for mode in ("compact_error", "get_error"):
            f = CompactFake()
            f.mode = mode
            r, f = self.collect(f)
            self.assertFalse(r["success"])
            self.assertIn("failed_attempt", r)
            if mode == "compact_error":
                self.assertEqual(r["failed_attempt"]["operation_version"], 2)
                self.assertFalse(r["failed_attempt"]["boot_identity_known"])
                self.assertFalse(any(x.startswith(b"PEXGET") for x in f.commands))

    def test_old_identity_rejected(self):
        import json

        f = CompactFake()
        f.version = json.loads(
            Path(
                "/home/jaykob/esp32-pex-collector-candidate/collector-v1-final/expected-version.json"
            ).read_text()
        )
        self.assertNotEqual(f.version, json.loads(
            (Path(__file__).resolve().parent / "expected-version.json").read_text()
        ))
        r, f = self.collect(f)
        self.assertFalse(r["success"])
        self.assertEqual(f.commands, [b"VERSION?\n"])

    def test_cancel(self):
        r, f = self.collect(cancel=lambda: True)
        self.assertFalse(r["success"])
        self.assertIn(b"STOP\n", f.commands)


if __name__ == "__main__":
    unittest.main()
