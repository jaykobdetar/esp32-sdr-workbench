#!/usr/bin/env python3
"""Independent, bounded USB CDC controller for the local RF test transmitter."""
import argparse
import json
import os
import re
import time
from pathlib import Path
import serial
from serial.tools import list_ports

SERIAL = os.environ.get('RF_TX_SERIAL', '')

def target_serial(value=None):
    value = SERIAL if value is None else value
    if not re.fullmatch(r'[0-9A-F]{16}', value):
        raise ValueError('Set RF_TX_SERIAL or --serial to the exact 16-uppercase-hex USB serial')
    return value
VID, PID = 0x2886, 0xF010


def discover(serial_number=None):
    serial_number = target_serial(serial_number)
    found = [p.device for p in list_ports.comports()
             if p.vid == VID and p.pid == PID and p.serial_number == serial_number]
    if len(found) != 1:
        raise RuntimeError(f'Expected one RF transmitter {serial_number}; found {found}')
    return found[0]


class Transmitter:
    def __init__(self, port=None, timeout=3.0, serial_number=None):
        verified_port = discover(serial_number)
        if port is not None and Path(port).resolve() != Path(verified_port).resolve():
            raise RuntimeError('Explicit port does not match the designated USB serial and VID/PID')
        self.port = verified_port
        self.timeout = timeout
        self.failed = False
        self.serial = serial.Serial(self.port, 115200, timeout=0.1,
                                    write_timeout=timeout, exclusive=True)
        self.serial.dtr = True
        time.sleep(0.12)
        self.serial.reset_input_buffer()

    def command(self, command):
        if self.failed:
            raise RuntimeError('Serial framing is uncertain; close and reconnect before another command')
        if '\n' in command or '\r' in command or len(command) > 900:
            raise ValueError('One bounded command line required')
        self.serial.write((command + '\n').encode('ascii'))
        self.serial.flush()
        deadline = time.monotonic() + self.timeout
        line = bytearray()
        while time.monotonic() < deadline:
            chunk = self.serial.read(1)
            if not chunk:
                continue
            if chunk == b'\n':
                if not line.strip():
                    continue
                try:
                    response = json.loads(line)
                except (ValueError, UnicodeError) as e:
                    self.failed = True
                    raise RuntimeError(f'Malformed transmitter response: {line!r}') from e
                if not isinstance(response, dict):
                    self.failed = True
                    raise RuntimeError('Non-object transmitter response')
                if response.get('ok') is False or 'error' in response:
                    raise RuntimeError(f'Transmitter rejected {command!r}: {response}')
                return response
            line += chunk
            if len(line) > 16384:
                self.failed = True
                raise RuntimeError('Transmitter response exceeds size limit')
        self.failed = True
        raise TimeoutError(f'No complete acknowledgement for {command!r}; do not assume execution failed')

    def hello(self):
        r = self.command('HELLO')
        if r.get('app') != 'rf-test-tx' or r.get('protocol') != 1 or r.get('updater') is not True:
            raise RuntimeError(f'Wrong application or missing updater: {r}')
        return r

    def status(self):
        return self.command('STATUS')

    def stop(self):
        return self.command('STOP')

    def configure(self, **kwargs):
        return self.command('CONFIG ' + ' '.join(f'{k}={v}' for k,v in kwargs.items()))

    def start(self, count=0, duration_ms=5000):
        if not 1 <= duration_ms <= 60000 or count < 0:
            raise ValueError('Finite duration 1..60000 ms and nonnegative count required')
        return self.command(f'START count={count} duration_ms={duration_ms}')

    def close(self):
        if self.serial.is_open:
            try:
                self.stop()
            finally:
                self.serial.close()

    def __enter__(self):
        try:
            self.hello()
            return self
        except BaseException:
            self.serial.close()
            raise

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except Exception:
                pass  # Preserve the original error; serial.close lowers DTR and stops RF.


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port')
    p.add_argument('--serial', help='Exact device USB serial; defaults to RF_TX_SERIAL')
    p.add_argument('--frequency-mhz', type=int, default=2440)
    p.add_argument('--mode-mbps', type=int, choices=(1,2), default=2)
    p.add_argument('--power-dbm', type=int, default=-20)
    p.add_argument('--length', type=int, default=64)
    p.add_argument('--interval-us', type=int, default=2000)
    p.add_argument('--count', type=int, default=0)
    p.add_argument('--jitter-us', type=int, default=0)
    p.add_argument('--seed', type=int, default=52840)
    p.add_argument('--payload-hex', default='off')
    p.add_argument('--hop-list', default='off')
    p.add_argument('--hop-every', type=int, default=1)
    p.add_argument('--burst-count', type=int, default=0)
    p.add_argument('--burst-gap-us', type=int, default=0)
    p.add_argument('--duration-ms', type=int, default=2000)
    p.add_argument('--status-only', action='store_true')
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    result={'host_start_ns':time.time_ns()}
    try:
        with Transmitter(a.port, serial_number=a.serial) as tx:
            result['hello']=tx.hello()
            if not a.status_only:
                result['config']=tx.configure(frequency_mhz=a.frequency_mhz,mode_mbps=a.mode_mbps,power_dbm=a.power_dbm,length=a.length,interval_us=a.interval_us,jitter_us=a.jitter_us,seed=a.seed,payload_hex=a.payload_hex,hop_list=a.hop_list,hop_every=a.hop_every,burst_count=a.burst_count,burst_gap_us=a.burst_gap_us)
                result['start']=tx.start(a.count,a.duration_ms)
                deadline=time.monotonic()+a.duration_ms/1000+3
                while time.monotonic()<deadline:
                    time.sleep(.1)
                    result['final']=tx.status()
                    if not result['final'].get('running',True):break
                else:raise TimeoutError('Transmitter did not complete bounded run')
            else:result['final']=tx.status()
    finally:
        result['host_end_ns']=time.time_ns()
        if a.output:
            a.output.parent.mkdir(parents=True,exist_ok=True)
            with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
