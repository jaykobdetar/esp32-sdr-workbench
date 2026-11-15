import struct
import unittest
import zlib
from pathlib import Path

import verify as v

P = Path(__file__).resolve().parent


def make(m, payload, cost):
    m = list(m)
    kind = m[1]
    m[7 if kind == 2 else 8] = zlib.crc32(payload)
    body = struct.pack('<64Q', *m) + payload
    return (
        f'PEXFRAME 1 {kind} {m[2]} {m[3]} 512 {len(payload)} {zlib.crc32(body):08x}\n'.encode()
        + body
        + f'\nPEXEND 1 {kind} {m[2]} {m[3]}\nPEXCOST 1 {kind} {m[3]} {cost[0]} {cost[1]}\n'.encode()
    )


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = (P / 'mock-result.bin').read_bytes()
        cls.i = (P / 'mock-result.bin.iq').read_bytes()
        cls.lib = v.library(P / 'native-v4')

    def test_known_packets(self):
        result = v.verify_pair(self.r, self.i, self.lib)
        self.assertEqual(result['observed_records'], 3)
        self.assertIsNone(result['coverage'])
        self.assertIsNone(result['source_recall'])

    def test_crc_convention(self):
        self.assertEqual(zlib.crc32(b'123456789'), 0xCBF43926)
        self.assertEqual(zlib.crc32(b'456789', zlib.crc32(b'123')), 0xCBF43926)

    def test_transport_corrupt(self):
        for wire in (self.r, self.i):
            for index in (0, len(wire) // 2, len(wire) - 1):
                bad = bytearray(wire)
                bad[index] ^= 1
                with self.subTest(index=index), self.assertRaises(ValueError):
                    v.frame(bytes(bad))

    def test_truncation_duplicate_extra(self):
        for bad in (
            self.r[:-1],
            self.r[:100],
            self.r + self.r,
            self.r + b'junk',
            self.r[: self.r.index(b'PEXCOST')],
        ):
            with self.assertRaises(ValueError):
                v.frame(bad)

    def test_forged_ranges_stages(self):
        m, p, c = v.frame(self.r)
        for index, value in (
            (4, 8188),
            (5, 0),
            (6, 65),
            (9, 0),
            (43, 0),
            (46, 1),
            (31, 2**32),
            (38, 2**32),
            (42, 0),
            (41, 0),
            (15, 0),
            (14, m[13] ^ 1),
            (22, m[21] + 20000),
            (29, m[28] + 100000),
            (15, m[30] + 1),
        ):
            a = list(m)
            a[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                v.frame(make(a, p, c))

    def test_cross_generation_and_out_of_order(self):
        m, p, c = v.frame(self.i)
        a = list(m)
        a[3] += 1
        with self.assertRaises(ValueError):
            v.verify_pair(self.r, make(a, p, c), self.lib)
        with self.assertRaises(ValueError):
            v.verify_pair(self.i, self.r, self.lib)

    def test_self_consistent_changed_result(self):
        m, p, c = v.frame(self.r)
        bad = bytearray(p)
        bad[0] = 1
        # Native exact equality remains required even with valid wire checksum.
        rm = list(m)
        rm[8] = zlib.crc32(bad)
        im, iq, ic = v.frame(self.i)
        im = list(im)
        im[8] = rm[8]
        with self.assertRaisesRegex(ValueError, 'native'):
            v.verify_pair(make(rm, bytes(bad), c), make(im, iq, ic), self.lib)

    def test_output_cost(self):
        m, p, c = v.frame(self.r)
        for cost in ((0, 0), (c[1], c[0]), (c[0], c[0] + 17000001)):
            with self.assertRaises(ValueError):
                v.frame(make(m, p, cost))

    def test_header_identity(self):
        for bad in (
            self.r.replace(b'PEXFRAME 1', b'PEXFRAME 2', 1),
            self.r.replace(b' 512 ', b' 511 ', 1),
        ):
            with self.assertRaises(ValueError):
                v.frame(bad)

    def test_failed_attempt(self):
        wire = (P / 'mock-result.bin.error').read_bytes()
        result = v.failed_attempt(wire)
        self.assertTrue(result['triggered'])
        self.assertFalse(result['success'])
        self.assertIsNone(result['hardware_completed'])
        self.assertEqual(result['reason'], 'capture_or_calibration')
        for bad in (wire[:-1], wire + wire, wire.replace(b'PEXERR', b'PEXERX')):
            with self.assertRaises(ValueError):
                v.failed_attempt(bad)

    def test_cap_zero_is_accounted_not_recall(self):
        rm, _, rt = v.frame(self.r)
        im, iq, it = v.frame(self.i)
        result = v.replay(self.lib, iq, 0)
        self.assertEqual(result.count, 0)
        self.assertGreaterEqual(result.output_drops, 3)
        rm = list(rm)
        im = list(im)
        rm[6] = im[6] = 0
        rm[8] = im[8] = zlib.crc32(bytes(result))
        report = v.verify_pair(make(rm, bytes(result), rt), make(im, iq, it), self.lib)
        self.assertEqual(report['observed_records'], 0)


if __name__ == '__main__':
    unittest.main()
