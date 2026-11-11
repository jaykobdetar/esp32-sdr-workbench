#!/usr/bin/env python3
"""Fail-closed application-only updater for the verified Makerdiary dongle.
Never erases or writes raw block devices, bootloader, MBR, settings or UICR.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
from rf_tx import target_serial, Transmitter, discover

APP_START, APP_LIMIT = 0x23000, 0x40000
BOARD = 'nRF52840-MDK-USB-DONGLE'
RECOVERY = ('Unplug the Makerdiary dongle. Hold its button while plugging it back in, '
            'then release it. Confirm the green LED and UF2BOOT volume. '
            'Run this updater with --initial and a known-good application UF2. '
            'Do not use a bootloader-update UF2 or mass erase.')


def validate_image(path):
    data = Path(path).read_bytes()
    if not data or len(data)%512:
        raise ValueError('UF2 must contain complete 512-byte blocks')
    blocks = {}
    total=len(data)//512
    for o in range(0,len(data),512):
        a,b,flags,addr,size,num,count,family=struct.unpack_from('<8I',data,o)
        end=struct.unpack_from('<I',data,o+508)[0]
        if (a,b,end)!=(0x0a324655,0x9e5d5157,0x0ab16f30):
            raise ValueError('Invalid UF2 magic')
        if flags!=0x2000 or family!=0xada52840 or size!=256:
            raise ValueError('Only plain nRF52840 application family blocks are allowed')
        if count!=total or num>=total or num in blocks:
            raise ValueError('Missing/duplicate/inconsistent UF2 block numbering')
        if addr != APP_START+num*256 or addr+size>APP_LIMIT:
            raise ValueError('UF2 outside exact contiguous application-only range 0x23000..0x3ffff')
        blocks[num]=data[o+32:o+288]
    binary=b''.join(blocks[n] for n in range(total))
    sp,reset=struct.unpack_from('<II',binary)
    if not 0x20000000<sp<=0x20040000 or sp%8 or not reset&1 or not APP_START<=(reset&~1)<APP_START+len(binary):
        raise ValueError('Invalid Cortex-M application vectors')
    if b'UF2_ENTRY_0x57_v1' not in binary:
        raise ValueError('Required software update capability marker absent')
    return {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
            'flash_start':APP_START,'flash_end':APP_START+len(binary),'blocks':total}


def properties(device):
    raw=subprocess.check_output(['udevadm','info','--query=property','--name',device],text=True)
    return dict(s.split('=',1) for s in raw.splitlines() if '=' in s)


def verified_mount(serial_number=None):
    serial_number = target_serial(serial_number)
    entries=json.loads(subprocess.check_output(['findmnt','--json','--output','TARGET,SOURCE,FSTYPE'],text=True))
    def walk(items):
        for item in items:
            yield item
            yield from walk(item.get('children',[]))
    found=[]
    for item in walk(entries['filesystems']):
        target=Path(item['target'])
        if target.name != 'UF2BOOT' or item.get('fstype')!='vfat':continue
        info=target/'INFO_UF2.TXT'
        if not info.is_file():continue
        txt=info.read_text()
        if f'Board-ID: {BOARD}' not in txt or not txt.startswith('UF2 Bootloader 0.7.1 '):
            raise RuntimeError('Unexpected board or bootloader at UF2BOOT')
        prop=properties(item['source'])
        if prop.get('ID_SERIAL_SHORT')!=serial_number or prop.get('ID_VENDOR_ID')!='2886' or prop.get('ID_MODEL_ID')!='f00f':
            raise RuntimeError('UF2BOOT is not the designated physical dongle')
        found.append(target)
    if len(found)>1:raise RuntimeError('Ambiguous UF2 mounts')
    return found[0] if found else None


def wait_for(fn, timeout, description):
    end=time.monotonic()+timeout
    last=None
    while time.monotonic()<end:
        try:
            r=fn()
            if r:return r
        except (RuntimeError,FileNotFoundError,subprocess.CalledProcessError) as e:last=str(e)
        time.sleep(.2)
    raise TimeoutError(f'Timed out waiting for {description}; last error={last}. {RECOVERY}')


def update(image, expected_version, initial=False, timeout=35, output=None, serial_number=None):
    serial_number = target_serial(serial_number)
    image=Path(image).resolve()
    report={'started_ns':time.time_ns(),'expected_version':expected_version,
            'target_serial':serial_number,'image':str(image),'validation':validate_image(image),'events':[]}
    root=Path(__file__).resolve().parents[1]
    backup=root/'recovery'/str(report['started_ns'])
    backup.mkdir(parents=True)
    log=Path(output) if output else root/'logs'/f"update-{report['started_ns']}.json"
    log.parent.mkdir(exist_ok=True,parents=True)
    def event(name,**kw):
        report['events'].append({'event':name,'host_ns':time.time_ns(),**kw})
        log.write_text(json.dumps(report,indent=2))
    try:
        if not initial:
            tx=Transmitter(serial_number=serial_number)
            try:
                hello=tx.hello()
                event('application_identified',hello=hello)
                tx.stop()
                ack=tx.command('BOOTLOADER')
                event('bootloader_requested',ack=ack)
            finally:
                tx.serial.close() # no STOP after intentional reset
        mount=wait_for(lambda:verified_mount(serial_number),timeout,'verified UF2BOOT volume')
        event('bootloader_identified',mount=str(mount))
        for name in ('INFO_UF2.TXT','CURRENT.UF2','INDEX.HTM'):
            shutil.copyfile(mount/name,backup/name)
        event('pre_update_backup',directory=str(backup),current_sha256=hashlib.sha256((backup/'CURRENT.UF2').read_bytes()).hexdigest())
        # Validate preserved SoftDevice header and destination before every update.
        old=(backup/'CURRENT.UF2').read_bytes(); chunks={}
        for off in range(0,len(old),512):
            h=struct.unpack_from('<8I',old,off);chunks[h[3]]=old[off+32:off+32+h[4]]
        info=chunks.get(0x3000,b'')
        if len(info)<12 or struct.unpack_from('<II',info,4)!=(0x51b1e5db,APP_START):
            raise RuntimeError('Existing SoftDevice/application boundary changed; refusing flash')
        # Count write as uncertain until readback through the new application.
        event('write_begin')
        try:
            with (mount/'RFTEST.UF2').open('wb',buffering=0) as f:
                data=image.read_bytes()
                offset=0
                while offset<len(data):
                    n=f.write(data[offset:offset+512])
                    if not n:raise OSError('Short UF2 write')
                    offset+=n
                os.fsync(f.fileno())
            event('write_complete')
        except OSError as e:
            event('write_outcome_uncertain',error=str(e))
            # A bootloader can disconnect after the last block before fsync returns.
            # Never retry writes here. Await exact-version health to resolve outcome.
        port=wait_for(lambda:discover(serial_number),timeout,'application USB enumeration')
        with Transmitter(port, serial_number=serial_number) as tx:
            hello=tx.hello();status=tx.status()
            if hello.get('version')!=expected_version or hello.get('healthy') is not True or status.get('running') is not False:
                raise RuntimeError(f'Application health/version mismatch: {hello}, {status}')
            event('verified',hello=hello,status=status)
            report['result']='verified'
    except Exception as e:
        report['result']='blocked_or_unverified'
        event('failure',error=str(e),manual_recovery=RECOVERY)
        raise
    finally:
        report['ended_ns']=time.time_ns()
        log.write_text(json.dumps(report,indent=2))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path)
    p.add_argument('--expected-version')
    p.add_argument('--serial', help='Exact device USB serial; defaults to RF_TX_SERIAL')
    p.add_argument('--initial',action='store_true',help='Device is already in verified bootloader mode')
    p.add_argument('--validate-only',action='store_true')
    p.add_argument('--timeout',type=float,default=35)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.validate_only:print(json.dumps(validate_image(a.image),indent=2));return
    if not a.expected_version:p.error('--expected-version is required to flash')
    print(json.dumps(update(a.image,a.expected_version,a.initial,a.timeout,a.output,a.serial),indent=2))
if __name__=='__main__':main()
