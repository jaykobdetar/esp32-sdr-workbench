import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'paused_extract'))
import codec
import verify as legacy

FROZEN = Path('/home/jaykob/esp32-pex-collector-candidate/collector-v1-final')


def wire(m, native, times=(1000000, 1000100), preserve_crc=False):
    prefix = codec.compact_prefix(native, m[6])
    m = list(m)
    m[:2] = [2, 3]
    if not preserve_crc:
        m[8] = zlib.crc32(native)
    body = struct.pack('<64Q', *m) + prefix
    return (
        f'PEXFRAME 2 3 {m[2]} {m[3]} 512 {len(prefix)} {zlib.crc32(body):08x}\n'.encode()
        + body
        + f'\nPEXEND 2 3 {m[2]} {m[3]}\nPEXCOST 2 3 {m[3]} {times[0]} {times[1]}\n'.encode()
    )


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FROZEN / 'mock-result.bin').read_bytes()
        cls.iq = (FROZEN / 'mock-result.bin.iq').read_bytes()
        cls.m, cls.native, cls.times = legacy.frame(cls.raw)

    def test_all_caps_counts(self):
        for cap in range(65):
            for count in range(cap + 1):
                m = list(self.m)
                m[6] = cap
                native = bytearray(1844)
                struct.pack_into(
                    '<13I', native, 0, 0, count, 0xFFFFFFFF, count, 0, 0, *([0xFFFFFFFF] * 7)
                )
                for j in range(count):
                    struct.pack_into(
                        '<II16sHBb', native, 52 + 28 * j, 0xFFFFFFFF, j, b'x' * 16, 65535, 14, -1
                    )
                encoded = wire(m, bytes(native), self.times)
                out = codec.frame(encoded, legacy)
                self.assertEqual(out[1], bytes(native))
        # cap zero still preserves detection/drop accounting.
        n = bytearray(1844)
        struct.pack_into('<6I', n, 0, 0, 0, 4, 4, 0, 4)
        m = list(self.m)
        m[6] = 0
        self.assertEqual(codec.frame(wire(m, bytes(n), self.times), legacy)[1], bytes(n))

    def test_every_tail_byte(self):
        for count in range(65):
            n = bytearray(1844)
            struct.pack_into('<II', n, 0, 0, count)
            for j in range(52 + 28 * count, 1844):
                n[j] = 1
                with self.assertRaises(ValueError):
                    codec.compact_prefix(bytes(n), 64)
                n[j] = 0

    def test_bad_native(self):
        for cap in (-1, 65, True):
            with self.assertRaises(ValueError):
                codec.compact_prefix(self.native, cap)
        for field, value in [(0, 1), (4, 65)]:
            n = bytearray(self.native)
            struct.pack_into('<I', n, field, value)
            with self.assertRaises(ValueError):
                codec.compact_prefix(bytes(n), 64)

    def test_malformed(self):
        good = wire(self.m, self.native, self.times)
        bad = [
            b'',
            good[:-1],
            good + b'x',
            good.replace(b'PEXFRAME 2 3', b'PEXFRAME 1 3', 1),
            good.replace(b'PEXFRAME 2 3', b'PEXFRAME 2 1', 1),
            good.replace(b' 512 ', b' 511 ', 1),
            good.replace(b'PEXEND 2 3', b'PEXEND 2 2'),
            good.split(b'PEXCOST')[0],
            b'PEXFRAME ' + b'9' * 600 + b'\n',
        ]
        for x in bad:
            with self.assertRaises(ValueError):
                codec.frame(x, legacy)
        for i in [good.index(b'\n') + 1, good.index(b'\n') + 513]:
            b = bytearray(good)
            b[i] ^= 1
            with self.assertRaises(ValueError):
                codec.frame(bytes(b), legacy)
        # CRC-correct mismatches: full-native CRC, length, counters.
        h, rest = good.split(b'\n', 1)
        bodylen = 512 + 52 + 28 * 3
        for offset in [8 * 8, 512 + 4, 512 + 12]:
            b = bytearray(rest[:bodylen])
            b[offset] ^= 1
            hh = h.rsplit(b' ', 1)[0] + f' {zlib.crc32(b):08x}\n'.encode()
            with self.assertRaises(ValueError):
                codec.frame(hh + bytes(b) + rest[bodylen:], legacy)

    def test_capability(self):
        self.assertEqual(codec.capability(b'PEXCOMPACT2 2 3 512 52 28 64 LEGACY1 0 0\n'), (0, 0))
        for x in [
            b'ERR\n',
            b'PEXCOMPACT2 2 3 512 52 28 64 LEGACY1 0 1\n',
            b'PEXCOMPACT2 2 3 512 52 28 64 LEGACY1 -1 0\n',
            b'x' * 1000,
        ]:
            with self.assertRaises(ValueError):
                codec.capability(x)

    def test_legacy_strict(self):
        with self.assertRaises(ValueError):
            legacy.frame(wire(self.m, self.native, self.times))
        self.assertEqual(legacy.frame(self.raw)[1], self.native)

    def test_pair_metadata(self):
        class Stub:
            frame = staticmethod(legacy.frame)

            @staticmethod
            def verify_pair(r, i, lib):
                rm, rb, rt = legacy.frame(r)
                im, ib, it = legacy.frame(i)
                assert rm[2:] == im[2:] and rb == Tests.native
                return {'evidence': 'mock pairing only, no replay'}

        good = wire(self.m, self.native, self.times)
        codec.verify_pair(good, self.iq, None, Stub)
        for slot in range(2, 64):
            m = list(self.m)
            m[slot] ^= 1
            # Some modifications fail transport-level semantic checks first.
            with self.assertRaises((ValueError, AssertionError)):
                codec.verify_pair(
                    wire(m, self.native, self.times, preserve_crc=True), self.iq, None, Stub
                )

    def test_error_version(self):
        raw = (FROZEN / 'mock-result.bin.error').read_bytes()
        lines = []
        for line in raw.splitlines():
            p = line.rsplit(b' ', 1)[0].replace(b' 1 ', b' 2 ', 1)
            lines.append(p + f' {zlib.crc32(p):08x}\n'.encode())
        err = b''.join(lines)
        self.assertEqual(codec.failed_attempt(err, legacy)['operation_version'], 2)
        for b in [err[:-1], err + b'x', raw, err.replace(b'PEXMEM 2', b'PEXMEM 1')]:
            with self.assertRaises(ValueError):
                codec.failed_attempt(b, legacy)


if __name__ == '__main__':
    unittest.main()
