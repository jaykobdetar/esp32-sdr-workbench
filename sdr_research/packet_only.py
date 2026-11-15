"""Strict bounded packet-only prototype reader. Not continuous RF acquisition.

Only accepts the reviewed PONLY v1 contract. No silent resynchronization.
"""

import re
import time
import zlib

from .protocol import ProtocolError

INFO = (
    'PKTONLYINFO 1 samples=16380 rate=16000000 mode=known_rftx16 '
    'crc=air16+wire32 period_us=10000..100000 captures=1..128 no_overlap'
)
FIELDS = {
    'BEGIN': 'count period_us cap hz core start_us'.split(),
    'WINDOW': 'slot trigger_us scheduled_us capture_us decode_us cycles packets output_drops busy incomplete'.split(),
    'PACKET': 'slot source_sequence address_sample phase polarity address air_crc payload'.split(),
    'END': (
        'status completed decoded decode_errors decoder_status faults skipped cancelled packets '
        'output_drops busy incomplete tx_failed decode_max_us cycles_max decode_total_us '
        'cycles_total gap_ns max_gap_ns session_us'
    ).split(),
}


def validate_plan(count, period_us, cap):
    if (
        type(count) is not int
        or not 1 <= count <= 128
        or type(period_us) is not int
        or not 10000 <= period_us <= 100000
        or type(cap) is not int
        or not 0 <= cap <= 16
    ):
        raise ValueError('Count 1..128, period 10000..100000 us, cap 0..16 required')


def known_payload(sequence):
    return (
        b'RFTX' + sequence.to_bytes(4, 'little') + bytes((sequence + k) & 255 for k in range(8, 16))
    )


def air_crc(payload):
    crc = 0xFFFF
    for byte in bytes.fromhex('efcdab89c3') + bytes([16]) + payload:
        for shift in range(8):
            feedback = (crc >> 15) ^ ((byte >> shift) & 1)
            crc = (crc << 1) & 0xFFFF
            if feedback & 1:
                crc ^= 0x1021
    return crc


def parse_line(line, expected_sequence):
    if not isinstance(line, str) or len(line) > 543 or '\n' in line or '\r' in line:
        raise ProtocolError('Invalid PONLY line bounds')
    match = re.fullmatch(r'(PONLY ([0-9]+) (.+)) \*([0-9a-f]{8})', line)
    if not match or int(match[2]) != expected_sequence:
        raise ProtocolError('PONLY framing or sequence failure')
    body = match[1]
    if zlib.crc32(body.encode('ascii')) != int(match[4], 16):
        raise ProtocolError('PONLY wire CRC failure')
    tokens = match[3].split(' ')
    kind = tokens.pop(0)
    if kind == 'BEGIN':
        if not tokens or tokens.pop(0) != '1':
            raise ProtocolError('Unsupported PONLY version')
    if kind not in FIELDS or len(tokens) != len(FIELDS[kind]):
        raise ProtocolError('Invalid PONLY field count')
    fields = {}
    for token, name in zip(tokens, FIELDS[kind], strict=True):
        key, sep, value = token.partition('=')
        if key != name or not sep:
            raise ProtocolError('Invalid PONLY field order/name')
        if key in ('address', 'air_crc', 'payload'):
            length = {'address': 10, 'air_crc': 4, 'payload': 32}[key]
            if re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is None:
                raise ProtocolError('Invalid packet hexadecimal field')
            fields[key] = value
        else:
            pattern = r'-?[0-9]+' if key == 'polarity' else r'[0-9]+'
            if re.fullmatch(pattern, value) is None:
                raise ProtocolError('Invalid PONLY numeric field')
            fields[key] = int(value)
            wide = key in (
                'start_us',
                'trigger_us',
                'scheduled_us',
                'decode_total_us',
                'cycles_total',
                'gap_ns',
                'max_gap_ns',
                'session_us',
            )
            if abs(fields[key]) > 2 ** (64 if wide else 32) - 1:
                raise ProtocolError('PONLY number out of range')
    return dict(kind=kind, wire_sequence=expected_sequence, wire_crc32=int(match[4], 16), **fields)


def validate_lines(lines, count, period_us, cap):
    validate_plan(count, period_us, cap)
    if len(lines) < 2 or len(lines) > 2 + count * (1 + cap):
        raise ProtocolError('Incomplete or oversized packet-only run')
    parsed = [parse_line(line, n) for n, line in enumerate(lines)]
    begin, end = parsed[0], parsed[-1]
    if begin['kind'] != 'BEGIN' or end['kind'] != 'END':
        raise ProtocolError('Missing BEGIN or END')
    if [begin[k] for k in ('count', 'period_us', 'cap')] != [count, period_us, cap]:
        raise ProtocolError('BEGIN does not echo requested bounds')
    if begin['hz'] != 240000000 or begin['core'] != 1 or not begin['start_us']:
        raise ProtocolError('Unqualified CPU/core or start clock')
    windows, packets, pending = [], [], 0
    for item in parsed[1:-1]:
        if item['kind'] == 'WINDOW':
            if pending:
                raise ProtocolError('Missing packets from preceding window')
            if (
                item['slot'] >= count
                or (windows and item['slot'] <= windows[-1]['slot'])
                or item['scheduled_us'] != begin['start_us'] + item['slot'] * period_us
                or item['trigger_us'] < item['scheduled_us']
                or (windows and item['trigger_us'] < windows[-1]['trigger_us'])
                or not 0 < item['capture_us'] <= 20000
                or item['decode_us'] >= 100000
                or item['cycles'] >= 2**32
                or item['packets'] > cap
            ):
                raise ProtocolError('Invalid WINDOW accounting/timing')
            pending = item['packets']
            windows.append(item)
        elif item['kind'] == 'PACKET':
            if not windows or not pending or item['slot'] != windows[-1]['slot']:
                raise ProtocolError('PACKET has no matching WINDOW')
            seq = item['source_sequence']
            if (
                seq >= 2**32
                or item['address_sample'] + 1536 >= 16380
                or item['phase'] not in range(8)
                or item['polarity'] not in (-1, 1)
                or item['address'] != 'efcdab89c3'
            ):
                raise ProtocolError('Invalid known packet fields')
            payload = bytes.fromhex(item['payload'])
            if payload != known_payload(seq) or int(item['air_crc'], 16) != air_crc(payload):
                raise ProtocolError('Known payload/over-air CRC mismatch')
            packets.append(item)
            pending -= 1
        else:
            raise ProtocolError('Unexpected packet-only message order')
    if pending:
        raise ProtocolError('END arrived before promised packets')
    if any(
        end[k]
        for k in ('status', 'decode_errors', 'decoder_status', 'faults', 'cancelled', 'tx_failed')
    ):
        raise ProtocolError('Packet-only terminal reports failure/cancellation')
    if not windows or end['completed'] != len(windows) or end['decoded'] != len(windows):
        raise ProtocolError('Incomplete decoded-window accounting')
    if count != end['completed'] + end['skipped'] or end['packets'] != len(packets):
        raise ProtocolError('Incomplete slot or packet accounting')
    for key in ('packets', 'output_drops', 'busy', 'incomplete'):
        if end[key] != sum(w[key] for w in windows):
            raise ProtocolError('Terminal cumulative counter mismatch')
    if end['output_drops']:
        raise ProtocolError('Decoder output-cap loss invalidates strict recall control')
    for field, target, op in [
        ('decode_us', 'decode_max_us', max),
        ('cycles', 'cycles_max', max),
        ('decode_us', 'decode_total_us', sum),
        ('cycles', 'cycles_total', sum),
    ]:
        if end[target] != op(w[field] for w in windows):
            raise ProtocolError('Terminal decoder work counter mismatch')
    gaps = [
        max(0, (b['trigger_us'] - a['trigger_us']) * 1000 - 1023750)
        for a, b in zip(windows, windows[1:], strict=False)
    ]
    if (
        end['gap_ns'] != sum(gaps)
        or end['max_gap_ns'] != max(gaps, default=0)
        or not 0 < end['session_us'] <= 15100000
    ):
        raise ProtocolError('Invalid nominal gap/session accounting')
    return dict(
        status='verified',
        begin=begin,
        windows=windows,
        packets=packets,
        end=end,
        accepted_observations=len(packets),
        unique_sequences=sorted({p['source_sequence'] for p in packets}),
        skipped_slots=end['skipped'],
        output_drops=end['output_drops'],
        busy_candidates=end['busy'],
        incomplete_candidates=end['incomplete'],
        queue='No queue: sequential acquisition, decoding and metadata output',
        note='Known RFTX16 packets only. No continuous acquisition or general protocol claim. '
        'Skipped slots, busy/incomplete candidates are not unique RF-packet loss counts.',
    )


def collect(radio, count=128, period_us=10000, cap=16, *, on_line=None, stop_after_windows=None):
    validate_plan(count, period_us, cap)
    if stop_after_windows is not None and (
        type(stop_after_windows) is not int or not 1 <= stop_after_windows <= count
    ):
        raise ValueError('STOP window bound must be within requested count')
    deadline = time.monotonic() + 18
    lines, windows, stopping = [], 0, False

    def retain(line):
        lines.append(line)
        if on_line:
            on_line(line)

    try:
        retain(radio.command(f'PKTONLY {count} {period_us} {cap}'))
        while True:
            item = parse_line(lines[-1], len(lines) - 1)
            if item['kind'] == 'END':
                break
            windows += item['kind'] == 'WINDOW'
            if stop_after_windows and windows >= stop_after_windows and not stopping:
                radio.serial.write(b'STOP\n')
                radio.serial.flush()
                stopping = True
            if len(lines) >= 2 + count * (1 + cap):
                raise ProtocolError('Packet-only output exceeds finite plan')
            retain(radio._line(deadline))
        return validate_lines(lines, count, period_us, cap)
    except BaseException:
        radio.failed = True
        # Never reinterpret or repair received data. Request cooperative stop,
        # then leave framing poisoned; caller closes rather than querying it.
        if not stopping:
            try:
                radio.serial.write(b'STOP\n')
                radio.serial.flush()
            except BaseException as cleanup_error:
                radio.packet_only_cleanup_error = repr(cleanup_error)
        raise
