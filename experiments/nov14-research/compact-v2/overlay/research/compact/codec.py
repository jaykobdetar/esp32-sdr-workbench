"""Offline compact transport codec. Inject the unchanged pinned PEX v1 verifier.
Normalization is internal validation only; callers preserve the original transcript.
No device imports. Transport checks are firmware claims, not IQ replay.
"""

import re
import struct
import zlib

HEADER = re.compile(rb'PEXFRAME 2 3 ([0-9]{1,20}) ([0-9]{1,20}) 512 ([0-9]{1,4}) ([0-9a-f]{8})\n')
CAPABILITY = re.compile(rb'PEXCOMPACT2 2 3 512 52 28 64 LEGACY1 ([0-9]{1,20}) ([0-9]{1,20})\n')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def capability(line):
    require(type(line) is bytes and len(line) <= 128, 'capability bound')
    m = CAPABILITY.fullmatch(line)
    require(m is not None, 'capability grammar')
    boot, gen = map(int, m.groups())
    require(boot < 2**64 and gen < 2**64 and (boot or not gen), 'capability identity')
    return boot, gen


def compact_prefix(native, cap):
    require(type(native) is bytes and len(native) == 1844, 'native size')
    require(type(cap) is int and 0 <= cap <= 64, 'cap')
    status, count = struct.unpack_from('<II', native)
    require(status == 0 and count <= cap, 'status/count')
    n = 52 + 28 * count
    require(not any(native[n:]), 'nonzero omitted tail')
    return native[:n]


def legacy_wire(m, native, cost):
    """Private canonical v1 representation, never presented as device output."""
    m = (1, 1) + tuple(m[2:])
    body = struct.pack('<64Q', *m) + native
    boot, gen = m[2:4]
    return (
        f'PEXFRAME 1 1 {boot} {gen} 512 1844 {zlib.crc32(body):08x}\n'.encode()
        + body
        + f'\nPEXEND 1 1 {boot} {gen}\nPEXCOST 1 1 {gen} {cost[0]} {cost[1]}\n'.encode()
    )


def frame(data, legacy):
    require(type(data) is bytes and len(data) <= 3000, 'frame bound')
    h = HEADER.match(data)
    require(h is not None and h.end() <= 128, 'compact header')
    boot, gen, n = map(int, h.groups()[:3])
    require(0 < boot < 2**64 and 0 < gen < 2**64 and 52 <= n <= 1844, 'identity/length')
    end = h.end() + 512 + n
    require(len(data) >= end, 'truncated compact body')
    body = data[h.end() : end]
    require(zlib.crc32(body) == int(h[4], 16), 'compact wire CRC')
    m = struct.unpack('<64Q', body[:512])
    require(m[:4] == (2, 3, boot, gen), 'compact metadata identity')
    prefix = body[512:]
    counters = struct.unpack_from('<13I', prefix)
    status, count, _sync, valid, duplicates, drops = counters[:6]
    require(
        status == 0 and count <= m[6] <= 64 and n == 52 + 28 * count, 'compact count/length/cap'
    )
    require(
        valid == count + duplicates + drops and (not drops or count == m[6]), 'counter accounting'
    )
    native = prefix + bytes(1844 - n)
    require(zlib.crc32(native) == m[8], 'full native CRC')
    tail = f'\nPEXEND 2 3 {boot} {gen}\n'.encode()
    require(data[end:].startswith(tail), 'compact terminal')
    c = re.fullmatch(
        rb'PEXCOST 2 3 ([0-9]{1,20}) ([0-9]{1,20}) ([0-9]{1,20})\n', data[end + len(tail) :]
    )
    require(c is not None, 'compact cost')
    cg, a, b = map(int, c.groups())
    require(cg == gen and a <= b < 2**64, 'cost identity/range')
    # Reuse unchanged metadata/timing checks without loosening legacy parser.
    legacy.frame(legacy_wire(m, native, (a, b)))
    return m, native, (a, b)


def verify_pair(result_wire, iq_wire, lib, legacy):
    rm, native, cost = frame(result_wire, legacy)
    im, _iq, _it = legacy.frame(iq_wire)
    require(im[:2] == (1, 2) and rm[2:] == im[2:], 'mixed paired identity/metadata')
    report = legacy.verify_pair(legacy_wire(rm, native, cost), iq_wire, lib)
    report['representation'] = 'compact v2/kind3 reconstructed losslessly; original IQ GET v1/kind2'
    return report


def failed_attempt(data, legacy):
    require(type(data) is bytes and len(data) <= 1024 and data.count(b'\n') == 2, 'error bounds')
    normalized = []
    for line, label in zip(data.splitlines(), (b'PEXERR', b'PEXMEM'), strict=True):
        prefix, crc = line.rsplit(b' ', 1)
        require(
            re.fullmatch(rb'[0-9a-f]{8}', crc) is not None and zlib.crc32(prefix) == int(crc, 16),
            'error CRC',
        )
        fields = prefix.split(b' ')
        require(fields[:2] == [label, b'2'], 'error version')
        require(all(len(x) <= 32 for x in fields), 'error field bound')
        fields[1] = b'1'
        p = b' '.join(fields)
        normalized.append(p + f' {zlib.crc32(p):08x}\n'.encode())
    result = legacy.failed_attempt(b''.join(normalized))
    result['operation_version'] = 2
    return result
