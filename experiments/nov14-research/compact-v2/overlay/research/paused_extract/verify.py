"""Offline PEX1 parser/native replay. Never imports serial or opens devices."""

import ctypes as C
import hashlib
import json
import re
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np
from observed_bits import independent_packet

HERE = Path(__file__).resolve().parent
TARGET = HERE.parents[1] / 'firmware/main/targets/esp32'
SOURCES = ('packet_decimated_dfa.c', 'packet_decimated_dfa.h', 'prefix_dfa.h')


class Record(C.Structure):
    _fields_ = [
        ('sequence', C.c_uint32),
        ('address_start_sample', C.c_uint32),
        ('payload', C.c_uint8 * 16),
        ('air_crc', C.c_uint16),
        ('phase', C.c_uint8),
        ('polarity', C.c_int8),
    ]


class Result(C.Structure):
    _fields_ = [
        (n, C.c_uint32)
        for n in 'status count sync_hits valid_hypotheses duplicates output_drops payload_rejects crc_rejects incomplete busy_syncs samples_processed differential_products symbol_decisions'.split()
    ] + [('records', Record * 64)]


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build(path):
    path = Path(path)
    path.mkdir(exist_ok=False)
    subprocess.run(
        [
            'cc',
            '-O2',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-shared',
            '-fPIC',
            str(TARGET / SOURCES[0]),
            '-o',
            str(path / 'decoder.so'),
        ],
        check=True,
    )
    receipt = {
        'sources': {s: sha(TARGET / s) for s in SOURCES},
        'library': sha(path / 'decoder.so'),
        'verifier': sha(__file__),
        'oracle': sha(HERE / 'observed_bits.py'),
    }
    (path / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


def library(path):
    path = Path(path)
    r = json.loads((path / 'receipt.json').read_text())
    require(r['sources'] == {s: sha(TARGET / s) for s in SOURCES}, 'source pins')
    require(
        r['library'] == sha(path / 'decoder.so')
        and r['verifier'] == sha(__file__)
        and r['oracle'] == sha(HERE / 'observed_bits.py'),
        'binary/verifier pins',
    )
    lib = C.CDLL(str(path / 'decoder.so'))
    lib.pkt_workspace_size.restype = C.c_size_t
    lib.pkt_result_size.restype = C.c_size_t
    require(
        lib.pkt_workspace_size() == 612 and lib.pkt_result_size() == C.sizeof(Result) == 1844, 'ABI'
    )
    lib.pkt_decode.argtypes = [
        C.POINTER(C.c_uint32),
        C.c_size_t,
        C.c_void_p,
        C.POINTER(Result),
        C.c_uint,
    ]
    return lib


def replay(lib, raw, cap):
    require(len(raw) == 65520 and type(cap) is int and 0 <= cap <= 64, 'input/cap')
    words = (C.c_uint32 * 16380).from_buffer_copy(raw)
    w = C.create_string_buffer(612)
    r = Result()
    rc = lib.pkt_decode(words, 16380, w, C.byref(r), cap)
    require(rc == r.status == 0 and bytes(words) == raw, 'decode/input integrity')
    return r


HEADER = re.compile(rb'PEXFRAME 1 ([12]) ([0-9]+) ([0-9]+) 512 (1844|65520) ([0-9a-f]{8})\n')


def frame(data):
    require(type(data) is bytes, 'bytes only')
    h = HEADER.match(data)
    require(h is not None, 'header')
    kind, boot, gen, n = map(int, h.groups()[:4])
    crc = int(h[5], 16)
    require(
        0 < boot < 2**64 and 0 < gen < 2**64 and n == {1: 1844, 2: 65520}[kind], 'identity/size'
    )
    start = h.end()
    end = start + 512 + n
    require(len(data) >= end, 'truncated body')
    body = data[start:end]
    require(zlib.crc32(body) == crc, 'transport CRC')
    m = struct.unpack('<64Q', body[:512])
    payload = body[512:]
    require(m[:4] == (1, kind, boot, gen), 'metadata identity')
    require(m[4:6] == (16380, 16380) and m[6] <= 64, 'capture sizes/cap')
    require(m[9] in range(2400, 2501) and m[11] in (0, 1) and m[43] == 1, 'settings/calibration')
    require(m[13] == m[14] and all(x == 0 for x in m[46:]), 'DC/reserved')
    require(
        all(m[j] < 2**32 for j in (7, 8, 12, 13, 14, *range(31, 43), 44, 45)),
        'uint32 metadata range',
    )
    require(m[10] == 2**64 - 1 or m[10] <= 127, 'filter range')
    require(m[42] & (1 << 18) and (m[41] & 0x7FFF) == 16380, 'hardware completion metadata')
    times = m[15:31]
    require(all(times), 'missing successful stage timestamp')
    require(all(a <= b for a, b in zip(times, times[1:], strict=False)), 'stage order')
    require(
        m[22] - m[21] < 20000 and m[29] - m[28] < 100000 and m[30] - m[15] < 5000000, 'time bounds'
    )
    require(m[7 if kind == 2 else 8] == zlib.crc32(payload), 'payload CRC')
    tail = f'\nPEXEND 1 {kind} {boot} {gen}\n'.encode()
    require(data[end:].startswith(tail), 'terminal')
    rest = data[end + len(tail) :]
    cost = re.fullmatch(rb'PEXCOST 1 ([12]) ([0-9]+) ([0-9]+) ([0-9]+)\n', rest)
    require(cost is not None, 'cost/incomplete or extra bytes')
    k, g, a, b = map(int, cost.groups())
    require((k, g) == (kind, gen) and m[30] <= a <= b < 2**64 and b - a <= 17000000, 'output cost')
    return m, payload, (a, b)


def verify_pair(result_wire, iq_wire, lib):
    require(__debug__, 'observed oracle requires assertions')
    rm, rb, rt = frame(result_wire)
    im, iq, it = frame(iq_wire)
    require(
        rm[1] == 1 and im[1] == 2 and rm[:1] + rm[2:] == im[:1] + im[2:], 'paired identity/metadata'
    )
    require(it[0] >= rt[1], 'GET before result')
    r = replay(lib, iq, rm[6])
    require(bytes(r) == rb, 'full native result mismatch')
    require(r.count <= rm[6], 'cap')
    words = np.frombuffer(iq, dtype='<u4')
    for p in r.records[: r.count]:
        independent_packet(words, p, 4)
    return {
        'generation': rm[3],
        'input_sha256': hashlib.sha256(iq).hexdigest(),
        'observed_records': r.count,
        'source_recall': None,
        'coverage': None,
        'evidence': 'exported IQ + exact native equality + observed-bit CRC, not transmitter attestation',
    }


def failed_attempt(data):
    require(type(data) is bytes and data.endswith(b'\n') and data.count(b'\n') == 2, 'error frame')
    error_line, mem_line = data.splitlines()
    data = error_line + b'\n'
    mp, mc = mem_line.rsplit(b' ', 1)
    require(
        re.fullmatch(rb'[0-9a-f]{8}', mc) is not None and zlib.crc32(mp) == int(mc, 16),
        'memory CRC',
    )
    mf = mp.split(b' ')
    require(len(mf) == 10 and mf[:2] == [b'PEXMEM', b'1'], 'memory layout')
    require(all(re.fullmatch(rb'[0-9]+', x) for x in mf[2:]), 'memory integer')
    mv = list(map(int, mf[2:]))
    require(all(x < 2**32 for x in mv[2:]), 'memory range')
    prefix, crc = data[:-1].rsplit(b' ', 1)
    require(
        re.fullmatch(rb'[0-9a-f]{8}', crc) is not None and zlib.crc32(prefix) == int(crc, 16),
        'error CRC',
    )
    parts = prefix.split(b' ')
    require(len(parts) == 12 and parts[:2] == [b'PEXERR', b'1'], 'error layout')
    require(re.fullmatch(rb'[a-z_]+', parts[4]) is not None, 'error reason')
    nums = []
    for x in parts[2:4] + parts[5:]:
        require(re.fullmatch(rb'[0-9]+', x) is not None, 'error integer')
        n = int(x)
        require(n < 2**64, 'error range')
        nums.append(n)
    boot, gen, trigger, done, restored, copied, decoded, actual, end = nums
    require(gen > 0 and actual <= 32767, 'error generation/count')
    require(mv[:2] == [boot, gen], 'memory identity')
    ordered = [x for x in (trigger, done, restored, copied, decoded, end) if x]
    require(
        end > 0 and all(a <= b for a, b in zip(ordered, ordered[1:], strict=False)),
        'error stage order',
    )
    require(not trigger or (done and restored), 'unrestored attempt')
    return dict(
        boot=boot,
        generation=gen,
        reason=parts[4].decode(),
        triggered=bool(trigger),
        hardware_completed=None,
        copy_finished=bool(copied),
        decoder_returned=bool(decoded),
        actual_status_samples=actual,
        cleanup_end_us=end,
        success=False,
        allocation_heap_snapshots_bytes=mv[2:],
    )
