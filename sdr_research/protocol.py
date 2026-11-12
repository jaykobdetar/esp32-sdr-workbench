"""ESP-SDR protocol 6. One Radio instance belongs to one acquisition worker."""

import json
import re
import struct
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from numpy.typing import NDArray

RATES = {
    80_000_000: 0,
    40_000_000: 1,
    20_000_000: 2,
    10_000_000: 3,
    8_000_000: 4,
    4_000_000: 5,
    16_000_000: 6,
    32_000_000: 7,
    10_666_667: 8,
    6_400_000: 9,
}

# Field order of the SPS1 statistics frame body and of the SPECEND text line.
SPEC_STAT_FIELDS = (
    'core0_permille', 'core1_permille', 'coverage_permille', 'flags', 'heap_free', 'heap_largest',
    'abandoned', 'drops', 'late', 'queue_permille', 'ffts_per_second',
)  # fmt: skip
SPEC_END_FIELDS = (
    'status', 'detail', 'units', 'pairs', 'elapsed_us', 'late_max', 'work_max_cycles', 'frames',
    'drops', 'abandoned', 'ffts', 'stopped_by_host',
)  # fmt: skip


class ProtocolError(RuntimeError):
    pass


@dataclass
class Capture:
    iq: NDArray[np.complex64]
    sample_rate_hz: int
    frequency_hz: int
    timestamp: str
    monotonic_start_ns: int
    monotonic_end_ns: int
    firmware_capture_us: int
    bits: int = 8
    crc_ok: bool = True
    metadata: dict = field(default_factory=dict)

    @property
    def nominal_rf_seconds(self) -> float:
        return len(self.iq) / self.sample_rate_hz

    @property
    def host_seconds(self) -> float:
        return (self.monotonic_end_ns - self.monotonic_start_ns) / 1e9


def decode_iq(payload: bytes, n: int, bits: int) -> NDArray[np.complex64]:
    expected = (n * bits * 2 + 7) // 8
    if len(payload) != expected:
        raise ProtocolError('Wrong I/Q payload length')
    if bits == 8:
        a = np.frombuffer(payload, dtype=np.int8).reshape(n, 2).astype(np.float32)
    elif bits == 10:
        # A pair of 20-bit samples occupies five bytes. An odd final sample uses three.
        padded = np.frombuffer(payload + b'\0' * 5, dtype=np.uint8)
        starts = np.arange(n, dtype=np.int64) * 20
        byte = starts // 8
        shift = starts % 8
        word = (
            padded[byte].astype(np.uint32)
            | padded[byte + 1].astype(np.uint32) << 8
            | padded[byte + 2].astype(np.uint32) << 16
        ) >> shift
        i = (word & 1023).astype(np.int32)
        q = ((word >> 10) & 1023).astype(np.int32)
        i = np.where(i >= 512, i - 1024, i)
        q = np.where(q >= 512, q - 1024, q)
        a = np.column_stack((i, q)).astype(np.float32)
    else:
        raise ValueError('bits must be 8 or 10')
    return ((a[:, 0] - 1j * a[:, 1]) / (1 << (bits - 1))).astype(np.complex64)


class Radio:
    def __init__(self, port: str, baud: int = 1_000_000, transport=None) -> None:
        self.port = port
        self.baud = baud
        self.serial = transport
        self.info = {}
        self.settings = {}
        self.failed = False

    def _line(self, deadline: float | None = None) -> str:
        deadline = deadline or time.monotonic() + 4
        out = bytearray()
        while time.monotonic() < deadline:
            b = self.serial.read(1)
            if not b:
                continue
            if b == b'\n':
                try:
                    return out.rstrip(b'\r').decode('ascii')
                except UnicodeDecodeError:
                    raise ProtocolError('Non-ASCII command reply') from None
            out += b
            if len(out) > 8192:
                raise ProtocolError('Oversized reply')
        raise TimeoutError('Serial reply timed out')

    def _read(self, n: int, deadline: float | None = None) -> bytes:
        deadline = deadline or time.monotonic() + max(5, n * 10 / self.baud * 3)
        out = bytearray()
        while len(out) < n and time.monotonic() < deadline:
            out += self.serial.read(n - len(out))
        if len(out) != n:
            raise TimeoutError(f'Truncated binary payload: {len(out)}/{n}')
        return bytes(out)

    def command(self, cmd: str) -> str:
        if self.failed:
            raise ProtocolError('Connection framing uncertain; reconnect required')
        try:
            self.serial.write((cmd + '\n').encode('ascii'))
            self.serial.flush()
            line = self._line()
        except Exception:
            self.failed = True
            raise
        if line.startswith('ERR'):
            raise ProtocolError(f'{cmd}: {line}')
        return line

    def synchronize(self) -> None:
        deadline = time.monotonic() + 12
        # Do not reinterpret arbitrary capture bytes as commands; drain until exact nonce echo.
        while time.monotonic() < deadline:
            marker = f'SYNC {time.monotonic_ns()}'
            self.serial.write(('\nRELEASE\n' + marker + '\n').encode())
            self.serial.flush()
            until = min(deadline, time.monotonic() + 1.5)
            while time.monotonic() < until:
                try:
                    if self._line(until) == marker:
                        self.failed = False
                        return
                except (ProtocolError, TimeoutError):
                    break
        self.failed = True
        raise TimeoutError('Could not synchronize ESP-SDR')

    def connect(self) -> dict[str, object]:
        if self.serial is None:
            import serial

            self.serial = serial.Serial(
                port=None, baudrate=self.baud, timeout=0.1, write_timeout=3, exclusive=True
            )
            self.serial.dtr = False
            self.serial.rts = False
            self.serial.port = self.port
            self.serial.open()
        self.synchronize()
        info = self.command('INFO').split()
        if len(info) != 4 or info[1] != '6' or info[2] != 'burst':
            raise ProtocolError('Requires protocol 6 burst firmware')
        self.info = {
            'family': info[0],
            'protocol': 6,
            'max_samples': int(info[3]),
            'caps': self.command('CAPS').split()[1:],
        }
        line = self.command('LIMITS?')
        if not line.startswith('LIMITS '):
            raise ProtocolError('Missing receiver limits')
        self.info['limits'] = json.loads(line[7:])
        self.info['version'] = self.command('VERSION?')
        self.info['transport'] = self.command('TRANSPORT?')
        if 'SPEC' in self.info['caps']:
            line = self.command('SPECINFO?')
            self.info['spectrum'] = json.loads(line.removeprefix('SPECINFO '))
        self.settings = {}
        return self.info

    def configure(
        self,
        frequency_mhz: int = 2440,
        rate_hz: int = 16_000_000,
        bandwidth_mhz: int = 0,
        gain: int | None = None,
        bits: int = 8,
    ) -> None:
        limits = self.info['limits']
        if rate_hz not in limits['rates'] or bits not in limits['bits']:
            raise ValueError('Unsupported rate or precision')
        if not 2400 <= frequency_mhz <= 2500:
            raise ValueError('Research viewer tuning limited to 2400–2500 MHz')
        bw = limits.get('bandwidth')
        if bandwidth_mhz and (not bw or not bw[0] <= bandwidth_mhz <= bw[1]):
            raise ValueError('Unsupported analog bandwidth')
        if gain is not None and not limits['gain'][0] <= gain <= limits['gain'][1]:
            raise ValueError('Unsupported gain index')
        new = dict(
            frequency_mhz=int(frequency_mhz),
            rate_hz=int(rate_hz),
            bandwidth_mhz=int(bandwidth_mhz),
            gain=gain,
            bits=bits,
        )
        started = time.monotonic_ns()
        for key, cmd in [
            ('frequency_mhz', f'FREQ {frequency_mhz}'),
            ('bandwidth_mhz', f'BANDWIDTH {bandwidth_mhz}'),
            ('gain', 'GAIN HARDWARE' if gain is None else f'GAIN MANUAL {gain}'),
        ]:
            if key not in self.settings or self.settings[key] != new[key]:
                reply = self.command(cmd)
                if not (reply == 'OK' or reply.startswith(('GAIN ', 'FREQ ', 'BANDWIDTH '))):
                    raise ProtocolError(f'Unexpected configuration reply {reply!r}')
        new['configure_ns'] = time.monotonic_ns() - started
        self.settings = new

    def capture(self, samples: int = 16380) -> Capture:
        if not self.settings:
            self.configure()
        if not 256 <= samples <= self.info['max_samples']:
            raise ValueError('Capture length outside device limits')
        s = self.settings
        start = time.monotonic_ns()
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            line = self.command(f'CAP{s["bits"] * 2} {samples} {RATES[s["rate_hz"]]}')
            m = re.fullmatch(r'DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)', line)
            if not m or int(m[1]) != samples:
                raise ProtocolError('Invalid capture header')
            header_ns = time.monotonic_ns()
            payload = self._read((samples * s['bits'] * 2 + 7) // 8)
            end = time.monotonic_ns()
            if zlib.crc32(payload) != int(m[2], 16):
                raise ProtocolError('I/Q CRC mismatch')
            iq = decode_iq(payload, samples, s['bits'])
            return Capture(
                iq,
                s['rate_hz'],
                s['frequency_mhz'] * 1_000_000,
                stamp,
                start,
                end,
                int(m[3]),
                s['bits'],
                True,
                {
                    'settings': dict(s),
                    'device': self.info,
                    'header_latency_us': (header_ns - start) / 1000,
                    'payload_transfer_us': (end - header_ns) / 1000,
                    'crc32': m[2],
                    'timing_note': 'UTC timestamp is host request time, not hardware RF arrival time; n/fs is nominal sample duration, firmware time is trigger-to-done polling, excludes setup/teardown.',
                },
            )
        except Exception:
            self.failed = True
            raise

    def spectrum_run(
        self,
        milliseconds: int = 1000,
        fft_bins: int = 256,
        rate_hz: int = 16_000_000,
        detector: int = 1,
    ) -> dict[str, object]:
        profiles = self.info.get('spectrum', {}).get('profiles', [])
        profile = next((p for p in profiles if p[0] == rate_hz and p[2] == fft_bins), None)
        if profile is None:
            raise ValueError('Unsupported spectrum profile')
        if not 1 <= milliseconds <= 60000:
            raise ValueError('Finite runs require 1–60000 ms')
        cmd = f'SPEC {milliseconds} {profile[3]} {profile[4]} {detector} {profile[1]} {fft_bins}'
        stats = 'SPECSTAT' in self.info['caps']
        if stats:
            cmd += ' 1'
        start = time.monotonic_ns()
        result = {'frames': [], 'stats': []}
        deadline = time.monotonic() + milliseconds / 1000 + 10
        try:
            line = self.command(cmd)
            expected = f'SPEC {fft_bins} {rate_hz} {fft_bins} {self.settings["frequency_mhz"]}'
            if line != expected:
                raise ProtocolError('Invalid spectrum start')
            result['start'] = line
            while time.monotonic() < deadline:
                magic = self._read(4, deadline)
                if magic == b'SPC1':
                    body = magic + self._read(24 + fft_bins, deadline)
                    crc = self._read(4, deadline)
                    if zlib.crc32(body) != struct.unpack('<I', crc)[0]:
                        raise ProtocolError('Spectrum CRC mismatch')
                    seq, index, span, ffts, flags, gain, drops, log2, mult = struct.unpack(
                        '<IQIHBBHBB', body[4:28]
                    )
                    if 1 << log2 != fft_bins:
                        raise ProtocolError('Spectrum FFT size mismatch')
                    if mult != 2:
                        raise ProtocolError('Unsupported spectrum power multiplier')
                    result['frames'].append(
                        dict(
                            sequence=seq,
                            sample_index=index,
                            span=span,
                            ffts=ffts,
                            flags=flags,
                            gain=gain,
                            drops=drops,
                            multiplier=mult,
                            power_codes=list(body[28:]),
                        )
                    )
                elif magic == b'SPS1':
                    body = magic + self._read(32, deadline)
                    crc = self._read(4, deadline)
                    if zlib.crc32(body) != struct.unpack('<I', crc)[0]:
                        raise ProtocolError('Statistics CRC mismatch')
                    vals = struct.unpack('<HHHHIIIIHHI', body[4:])
                    result['stats'].append(dict(zip(SPEC_STAT_FIELDS, vals, strict=True)))
                elif magic == b'SPEC':
                    end = 'SPEC' + self._line(deadline)
                    if not end.startswith('SPECEND '):
                        raise ProtocolError('Invalid spectrum end')
                    vals = list(map(int, end.split()[1:]))
                    if len(vals) != 12 or vals[0] != 0:
                        raise ProtocolError(f'Failed spectrum run: {end}')
                    result['end'] = dict(zip(SPEC_END_FIELDS, vals, strict=True))
                    break
                else:
                    raise ProtocolError(f'Unknown spectrum frame {magic!r}')
            else:
                raise TimeoutError('Spectrum end missing')
        except Exception:
            self.failed = True
            raise
        result['host_elapsed_s'] = (time.monotonic_ns() - start) / 1e9
        return result

    def close(self) -> None:
        if self.serial:
            try:
                if not self.failed:
                    self.command('RELEASE')
            except Exception:
                pass
            self.serial.close()
            self.serial = None
