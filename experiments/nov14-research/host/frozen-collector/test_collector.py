import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import collector

ROOT = Path(__file__).resolve().parent


class Fake:
    def __init__(self):
        self.connection_token = "mock-connection-A"
        self.now = 1.0
        self.queue = bytearray()
        self.commands = []
        self.status_calls = 0
        self.version = json.loads((ROOT / "expected-version.json").read_text())
        self.result = (ROOT / "mock-result.bin").read_bytes()
        self.iq = (ROOT / "mock-result.bin.iq").read_bytes()
        self.boot = int(self.result.split(b"\n", 1)[0].split()[3])
        self.gen = 1
        self.retained = False
        self.mode = None
        self.after_command = None
        self.disconnect_at = None
        self.read_bytes = 0

    def clock(self):
        return self.now

    def write(self, data, timeout_s):
        self.commands.append(data)
        assert not self.queue, "collector wrote while output pending"
        if self.mode == "partial_write" and data.startswith(b"PEX "):
            return len(data) - 1
        if self.mode == "write_timeout":
            self.now += timeout_s + 0.1
            return len(data)
        if data == b"VERSION?\n":
            response = b"VERSION " + json.dumps(self.version).encode() + b"\n"
        elif data == b"PEX?\n":
            self.status_calls += 1
            if self.mode == "lost_owner" and self.status_calls > 1:
                response = b"ERR busy\n"
            elif self.mode == "malformed_status" and self.status_calls > 1:
                response = b"not-status\n"
            else:
                boot = self.boot
                gen = self.gen if self.retained else 0
                if self.mode == "stale_boot" and self.status_calls > 1:
                    boot += 1
                if self.mode == "stale_gen" and self.status_calls > 1:
                    gen += 1
                response = f"PEX 1 16380 64 {boot} {gen}\n".encode()
        elif data.startswith(b"PEX "):
            self.retained = True
            response = self.result
            if self.mode == "truncated":
                response = response[:100]
            if self.mode == "missing_cost":
                response = response[: response.index(b"PEXCOST")]
            if self.mode == "bad_crc":
                response = response[:100] + bytes([response[100] ^ 1]) + response[101:]
            if self.mode == "oversized":
                response = b"PEXFRAME 1 1 1 1 512 99999999 deadbeef\n"
            if self.mode == "long_line":
                response = b"x" * 600 + b"\n"
            if self.mode == "duplicate":
                response += response
            if self.mode == "firmware_error":
                response = (ROOT / "mock-result.bin.error").read_bytes()
            if self.mode == "interrupt_read":
                self.disconnect_at = self.read_bytes + 40
        elif data == b"PEXGET 1\n":
            response = self.iq
            if self.mode == "get_disconnect":
                raise OSError("mock disconnected")
            if self.mode == "get_reconnect":
                self.connection_token = "mock-connection-B"
            if self.mode == "wrong_iq_kind":
                response = self.result
        elif data == b"PEXDROP 1\n":
            response = b"ERR bad_drop\n" if self.mode == "drop_failure" else b"OK\n"
            if self.mode != "drop_failure":
                self.retained = False
        elif data == b"STOP\n":
            response = b"ERR stop_failure\n" if self.mode == "stop_failure" else b"OK\n"
            if self.mode != "stop_failure":
                self.retained = False
        elif data == b"RELEASE\n":
            response = (
                b"ERR release_failure\n" if self.mode == "release_failure" else b"OK\n"
            )
        else:
            raise AssertionError(data)
        self.queue.extend(response)
        if self.after_command:
            self.after_command(data)
        return len(data)

    def read(self, n, timeout_s):
        if self.disconnect_at is not None and self.read_bytes >= self.disconnect_at:
            raise KeyboardInterrupt("mock interruption")
        if not self.queue:
            self.now += timeout_s
            return b""
        if timeout_s:
            self.now += min(0.00001, timeout_s)
        result = bytes(self.queue[:n])
        del self.queue[:n]
        self.read_bytes += len(result)
        return result


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "test-runs").mkdir(exist_ok=True)
        cls.output_run = Path(tempfile.mkdtemp(prefix="run-", dir=ROOT / "test-runs"))

    def collect(self, fake=None, cancel=lambda: False):
        fake = fake or Fake()
        folder = self.output_run / (
            self._testMethodName + "-" + str(len(list(self.output_run.iterdir())))
        )
        c = collector.Collector(
            fake, folder, exclusive_idle=True, clock=fake.clock, cancel_requested=cancel
        )
        report = c.run()
        self.assertEqual(report, json.loads((folder / "report.json").read_text()))
        self.assertTrue((folder / "events.jsonl").exists())
        self.assertNotIn(b"CLAIM\n", fake.commands)
        return report, fake, folder

    def test_normal(self):
        r, f, p = self.collect()
        self.assertTrue(r["success"])
        self.assertFalse(f.retained)
        self.assertEqual(
            f.commands,
            [
                b"VERSION?\n",
                b"PEX?\n",
                b"PEX 64\n",
                b"PEXGET 1\n",
                b"PEX?\n",
                b"PEXDROP 1\n",
                b"RELEASE\n",
            ],
        )
        self.assertEqual(r["verification"]["observed_records"], 3)
        self.assertIsNone(r["verification"]["source_recall"])
        self.assertEqual((p / "result.bin").read_bytes(), f.result)
        self.assertEqual((p / "iq.bin").read_bytes(), f.iq)

    def test_preconditions(self):
        with self.assertRaises(collector.CollectionError):
            collector.Collector(Fake(), self.output_run / "no", exclusive_idle=False)
        self.assertFalse((self.output_run / "no").exists())

    def test_wrong_version(self):
        f = Fake()
        f.version["firmware_variant"] = "wrong"
        r, f, _ = self.collect(f)
        self.assertFalse(r["success"])
        self.assertEqual(f.commands, [b"VERSION?\n"])

    def test_boolean_protocol_is_not_integer_identity(self):
        f = Fake()
        f.version["paused_packet_extract_protocol"] = True
        r, f, _ = self.collect(f)
        self.assertFalse(r["success"])
        self.assertEqual(f.commands, [b"VERSION?\n"])

    def test_preexisting_retention(self):
        f = Fake()
        f.retained = True
        r, f, _ = self.collect(f)
        self.assertFalse(r["success"])
        self.assertEqual(len(f.commands), 2)
        self.assertTrue(f.retained)

    def test_malformed_partial_corrupt_no_blind_cleanup(self):
        for mode in (
            "truncated",
            "missing_cost",
            "bad_crc",
            "oversized",
            "long_line",
            "duplicate",
            "partial_write",
            "interrupt_read",
            "wrong_iq_kind",
        ):
            with self.subTest(mode=mode):
                f = Fake()
                f.mode = mode
                r, f, p = self.collect(f)
                self.assertFalse(r["success"])
                self.assertFalse(
                    any(
                        x.startswith((b"STOP", b"PEXDROP", b"RELEASE"))
                        for x in f.commands
                    )
                )
                self.assertTrue((p / "rx.bin").stat().st_size > 0)

    def test_disconnect_and_reconnect_no_cleanup(self):
        for mode in ("get_disconnect", "get_reconnect"):
            f = Fake()
            f.mode = mode
            r, f, _ = self.collect(f)
            self.assertFalse(r["success"])
            self.assertFalse(r["connection_trusted"])
            self.assertFalse(
                any(x.startswith((b"STOP", b"PEXDROP", b"RELEASE")) for x in f.commands)
            )

    def test_stale_or_lost_ownership(self):
        for mode in ("stale_boot", "stale_gen", "lost_owner", "malformed_status"):
            f = Fake()
            f.mode = mode
            r, f, _ = self.collect(f)
            self.assertFalse(r["success"])
            self.assertEqual(f.commands.count(b"PEX?\n"), 2)
            self.assertFalse(
                any(x.startswith((b"STOP", b"PEXDROP", b"RELEASE")) for x in f.commands)
            )

    def test_safe_boundary_cancel(self):
        r, f, _ = self.collect(cancel=lambda: True)
        self.assertFalse(r["success"])
        self.assertFalse(f.retained)
        self.assertEqual(f.commands[-3:], [b"PEX?\n", b"STOP\n", b"RELEASE\n"])
        self.assertNotIn(b"PEXGET 1\n", f.commands)

    def test_stop_failure(self):
        f = Fake()
        f.mode = "stop_failure"
        r, f, _ = self.collect(f, cancel=lambda: True)
        self.assertFalse(r["success"])
        self.assertEqual(f.commands[-1], b"STOP\n")
        self.assertTrue(f.retained)

    def test_drop_release_failures(self):
        for mode in ("drop_failure", "release_failure"):
            f = Fake()
            f.mode = mode
            r, f, _ = self.collect(f)
            self.assertFalse(r["success"])
            self.assertNotIn(b"STOP\n", f.commands)

    def test_ownership_delay_before_cleanup(self):
        f = Fake()

        def cancel():
            f.now += 5
            return True

        r, f, _ = self.collect(f, cancel=cancel)
        self.assertFalse(r["success"])
        self.assertTrue(f.retained)
        self.assertEqual(f.commands[-1], b"PEX 64\n")

    def test_write_timeout(self):
        f = Fake()
        f.mode = "write_timeout"
        r, f, _ = self.collect(f)
        self.assertFalse(r["success"])
        self.assertFalse(r["connection_trusted"])
        self.assertEqual(len(f.commands), 1)

    def test_boot_zero_failure_is_host_session_bound(self):
        f = Fake()
        f.mode = "firmware_error"
        # Existing failure fixture has a boot token. Rewrite both CRC-covered lines as BOOT0.
        original = (ROOT / "mock-result.bin.error").read_bytes()
        import zlib

        lines = []
        for line in original.splitlines():
            fields = line.rsplit(b" ", 1)[0].split(b" ")
            fields[2] = b"0"
            prefix = b" ".join(fields)
            lines.append(prefix + f" {zlib.crc32(prefix):08x}\n".encode())
        # Inject response without modifying any frozen fixture.
        old = f.write

        def write(data, timeout):
            n = old(data, timeout)
            if data.startswith(b"PEX "):
                f.queue = bytearray(b"".join(lines))
            return n

        f.write = write
        r, f, _ = self.collect(f)
        self.assertFalse(r["success"])
        self.assertFalse(r["failed_attempt"]["boot_identity_known"])
        self.assertTrue(r["host_session"])
        self.assertNotIn(b"STOP\n", f.commands)

    def test_fragmented_reads(self):
        f = Fake()
        original = f.read
        f.read = lambda n, t: original(min(n, 3), t)
        r, f, _ = self.collect(f)
        self.assertTrue(r["success"])

    def test_total_deadline(self):
        f = Fake()
        folder = self.output_run / "short-deadline"
        c = collector.Collector(
            f, folder, exclusive_idle=True, clock=f.clock, deadline_s=0.0001
        )
        r = c.run()
        self.assertFalse(r["success"])
        self.assertFalse(r["connection_trusted"])
        self.assertEqual(f.commands, [b"VERSION?\n"])

    def test_unexpected_initial_output_is_not_probed(self):
        f = Fake()
        f.queue.extend(b"OLD FRAME\n")
        r, f, p = self.collect(f)
        self.assertFalse(r["success"])
        self.assertEqual(f.commands, [])
        self.assertEqual((p / "rx.bin").read_bytes(), b"O")

    def test_transport_read_contract_violation(self):
        f = Fake()
        original = f.read

        def oversized(n, t):
            data = original(n, t)
            return data + b"X" if t and data else data

        f.read = oversized
        r, f, p = self.collect(f)
        self.assertFalse(r["success"])
        self.assertFalse(r["connection_trusted"])
        self.assertIn(b"X", (p / "rx.bin").read_bytes())

    def test_connection_changes_at_cleanup_boundary(self):
        f = Fake()

        def cancel():
            f.connection_token = "new-connection"
            return True

        r, f, _ = self.collect(f, cancel=cancel)
        self.assertFalse(r["success"])
        self.assertFalse(
            any(x.startswith((b"STOP", b"PEXDROP", b"RELEASE")) for x in f.commands)
        )

    def test_prewrite_logging_stall_cannot_refresh_lease(self):
        f = Fake()
        folder = self.output_run / "write-log-stall"
        c = collector.Collector(f, folder, exclusive_idle=True, clock=f.clock)
        original = c.event

        def event(kind, **values):
            original(kind, **values)
            if kind == "write_attempt" and values.get("hex") == b"PEXGET 1\n".hex():
                f.now += 5.5

        c.event = event
        r = c.run()
        self.assertFalse(r["success"])
        self.assertFalse(r["connection_trusted"])
        self.assertNotIn(b"PEXGET 1\n", f.commands)
        self.assertNotIn(b"STOP\n", f.commands)
        self.assertFalse(r["transaction_pending"])

    def test_frame_validation_stall_does_not_refresh_completion(self):
        f = Fake()
        folder = self.output_run / "frame-validation-stall"
        c = collector.Collector(f, folder, exclusive_idle=True, clock=f.clock)
        original = c.v.frame

        def frame(raw):
            result = original(raw)
            f.now += 5.5
            return result

        c.v.frame = frame
        r = c.run()
        self.assertFalse(r["success"])
        self.assertNotIn(b"PEXGET 1\n", f.commands)
        self.assertFalse(r["connection_trusted"])

    def test_postread_logging_stall_is_rejected(self):
        f = Fake()
        folder = self.output_run / "read-log-stall"
        c = collector.Collector(f, folder, exclusive_idle=True, clock=f.clock)
        original = c.event

        def event(kind, **values):
            original(kind, **values)
            if kind == "read":
                f.now += 5.5

        c.event = event
        r = c.run()
        self.assertFalse(r["success"])
        self.assertEqual(f.commands, [b"VERSION?\n"])

    def test_drop_ack_survives_release_failure(self):
        f = Fake()
        f.mode = "release_failure"
        r, f, _ = self.collect(f)
        self.assertFalse(r["success"])
        self.assertTrue(r["retention_release_acknowledged"])
        self.assertFalse(r["release_acknowledged"])
        self.assertEqual(r["cleanup"], "DROP acknowledged")
        self.assertEqual(r["last_verified_retention_identity"], [f.boot, 1])
        self.assertEqual(r["retained_state"], "release acknowledged")

    def test_import_help_default_no_serial(self):
        code = "import sys; import collector; assert 'serial' not in sys.modules; assert 'numpy' not in sys.modules"
        p = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        p = subprocess.run(
            [sys.executable, "collector.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p.returncode, 0)
        p = subprocess.run(
            [sys.executable, "collector.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(p.returncode, 0)
        p = subprocess.run(
            [
                sys.executable,
                "collector.py",
                "--execute",
                "--port",
                "NEVER_OPEN",
                "--expected-application-sha256",
                collector.EXPECTED_IMAGE,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no port was opened", p.stderr)


if __name__ == "__main__":
    unittest.main()
