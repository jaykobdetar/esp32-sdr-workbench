"""Pinned observed-bit oracle copied unchanged from reviewed v6; not source truth."""
import numpy as np

def independent_packet(words, p, algorithm=0):
    i = (words & 1023).astype(np.int64)
    q = ((words >> 10) & 1023).astype(np.int64)
    i = np.where(i >= 512, i - 1024, i)
    q = -np.where(q >= 512, q - 1024, q)
    if algorithm >= 2:
        n = len(i) // 2
        i = i[: 2 * n : 2] + i[1 : 2 * n : 2]
        q = q[: 2 * n : 2] + q[1 : 2 * n : 2]
    cross = q[1:] * i[:-1] - i[1:] * q[:-1]
    dot = i[1:] * i[:-1] + q[1:] * q[:-1]
    if algorithm >= 2:
        rc, rd = cross.copy(), dot.copy()
        for first in range(0, len(cross), 32):
            sl = slice(first, first + 32)
            sc, sd = int(cross[sl].sum()), int(dot[sl].sum())
            if abs(sc) > abs(sd):
                rc[sl], rd[sl] = (-dot[sl], cross[sl]) if sc > 0 else (dot[sl], -cross[sl])
        cross, dot, coefficients = rc, rd, 101
    elif algorithm == 1:
        coefficients = np.empty(len(cross), dtype=np.int64)
        for first in range(0, len(cross), 64):
            sc = int(cross[first : first + 64].sum())
            sd = int(dot[first : first + 64].sum())
            coefficient = 1130 if 2 * sc > sd else -928 if 2 * sc < -sd else 50
            coefficients[first : first + 64] = coefficient
    else:
        coefficients = 50
    d = cross - dot * coefficients // 1024
    start = p.address_start_sample
    assert start % 8 == p.phase
    width = 4 if algorithm >= 2 else 8
    if algorithm >= 2:
        assert start % 2 == 0
        start //= 2
    b = (d[start : start + 192 * width].reshape(192, width).sum(1) * p.polarity > 0).astype(
        np.uint8
    )
    observed = np.packbits(b[:176], bitorder='little').tobytes()
    payload = (
        b'RFTX'
        + int(p.sequence).to_bytes(4, 'little')
        + bytes((k + p.sequence) & 255 for k in range(8, 16))
    )
    assert (
        observed == bytes.fromhex('efcdab89c3') + bytes([16]) + payload
        and bytes(p.payload) == payload
    )
    crc = 65535
    for bit in b[:176]:
        fb = (crc >> 15) ^ int(bit)
        crc = (crc << 1) & 65535
        if fb & 1:
            crc ^= 0x1021
    received = 0
    for bit in b[176:]:
        received = (received << 1) | int(bit)
    assert received == crc == p.air_crc

