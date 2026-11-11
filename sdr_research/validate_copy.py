"""Strict, finite VCTEST1 reader. No flashing; caller owns a configured Radio."""
from datetime import datetime, timezone
import json,re,time,zlib
import numpy as np
from .protocol import Capture,ProtocolError,RATES,decode_iq

NAMES=('validate4-memcpy','fused-scalar','fused-unroll4','fused-unroll8')
STAT_INTS=('variant','count','sum_cycles','min_cycles','median_cycles','p95_cycles','p99_cycles','max_cycles','mismatch_count')
END_INTS=('version','status','mismatch_mask','wall_elapsed_us','cpu_hz_before','cpu_hz_after','core_before','core_after','samples','rate_code','repeats_requested','warmup_calls','cycle_bits','capture_us')

def _json(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ProtocolError('Duplicate VCTEST JSON key')
            out[key]=value
        return out
    def constant(_):raise ProtocolError('Non-finite VCTEST JSON number')
    value=json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    if not isinstance(value,dict):raise ProtocolError('VCTEST record is not an object')
    return value

def _integers(obj,fields):
    if any(type(obj.get(k)) is not int or not 0<=obj[k]<=2**64-1 for k in fields):
        raise ProtocolError('Invalid VCTEST integer field')

def _stat(obj,variant,name,maximum_count):
    _integers(obj,STAT_INTS)
    if obj['variant']!=variant or obj.get('name')!=name or obj['count']>maximum_count:
        raise ProtocolError('VCTEST variant/count mismatch')
    c=obj['count'];v=[obj[k] for k in ('min_cycles','median_cycles','p95_cycles','p99_cycles','max_cycles')]
    if any(x>0xffffffff for x in v) or v!=sorted(v):raise ProtocolError('Invalid cycle quantiles')
    if not c:
        if any(v) or obj['sum_cycles']:raise ProtocolError('Nonzero empty timing distribution')
    elif not v[0]*c<=obj['sum_cycles']<=v[-1]*c:raise ProtocolError('Inconsistent cycle sum')

def _unpack20(payload,n):
    """Independent streaming bit unpacker, not the GUI's vector decoder."""
    words=[];acc=bits=0
    for byte in payload:
        acc|=byte<<bits;bits+=8
        while bits>=20 and len(words)<n:
            words.append(acc&0xfffff);acc>>=20;bits-=20
    if len(words)!=n or acc:raise ProtocolError('Invalid CAP20 word count/padding')
    return np.asarray(words,dtype=np.uint32)

def _pack20(words):
    out=bytearray();acc=bits=0
    for word in words:
        acc|=int(word)<<bits;bits+=20
        while bits>=8:out.append(acc&255);acc>>=8;bits-=8
    if bits:out.append(acc&255)
    return bytes(out)

def run_validate_copy(radio,samples=16380,rate_hz=16_000_000,repeats=63):
    if any(type(v) is not int for v in (samples,rate_hz,repeats)) or not 256<=samples<=16380 or not 3<=repeats<=255:
        raise ValueError('Invalid VCTEST integer bounds')
    if rate_hz not in (16_000_000,40_000_000,80_000_000):raise ValueError('Unsupported capture rate')
    frequency=radio.settings['frequency_mhz'];code=RATES[rate_hz]
    stamp=datetime.now(timezone.utc).isoformat();start=time.monotonic_ns()
    report={'request':{'samples':samples,'rate_hz':rate_hz,'repeats':repeats,'frequency_mhz':frequency},'timestamp':stamp,'results':[]}
    try:
        if radio.command('VCTESTINFO?')!='VCTESTINFO 1 4 255 5000':raise ProtocolError('Unsupported VCTEST firmware')
        begin=radio.command(f'VCTEST {samples} {code} {repeats}')
        if begin!=f'VCTEST BEGIN {samples} {code} {repeats} {frequency}':raise ProtocolError('Invalid VCTEST BEGIN')
        report['begin']=begin;deadline=time.monotonic()+12
        line=radio._line(deadline)
        if not line.startswith('VCTEST TIMER '):raise ProtocolError('Missing VCTEST TIMER')
        timer=_json(line[len('VCTEST TIMER '):]);report['timer']=timer
        _stat(timer,0,'cycle-read-pair',255)
        if timer['count']!=255 or timer['mismatch_count']:raise ProtocolError('Invalid timer calibration record')
        for variant,name in enumerate(NAMES):
            line=radio._line(deadline)
            if not line.startswith('VCTEST RESULT '):raise ProtocolError('Missing/duplicate VCTEST result')
            obj=_json(line[len('VCTEST RESULT '):]);report['results'].append(obj);_stat(obj,variant,name,repeats)
        line=radio._line(deadline)
        if not line.startswith('VCTEST END '):raise ProtocolError('Missing VCTEST END')
        end=_json(line[len('VCTEST END '):]);report['end']=end;_integers(end,END_INTS)
        if end['version']!=1 or end['status'] not in (0,1,2,3) or end['mismatch_mask']>15:
            raise ProtocolError('Unsupported VCTEST version/status/mask')
        if (end['samples'],end['rate_code'],end['repeats_requested'],end['warmup_calls'],end['cycle_bits'])!=(samples,code,repeats,3,32):
            raise ProtocolError('VCTEST request/summary mismatch')
        if not re.fullmatch(r'[0-9a-fA-F]{8}',str(end.get('raw_crc32',''))):raise ProtocolError('Invalid raw CRC identity')
        if not end['wall_elapsed_us'] or any(not 0<end[k]<=1_000_000_000 for k in ('cpu_hz_before','cpu_hz_after')):
            raise ProtocolError('Invalid VCTEST clock/time')
        if end['core_before'] not in (0,1) or end['core_after'] not in (0,1):raise ProtocolError('Invalid CPU core')
        mask=sum(1<<i for i,r in enumerate(report['results']) if r['mismatch_count'])
        if mask!=end['mismatch_mask']:raise ProtocolError('VCTEST mismatch counters disagree')
        if end['status']==0 and (mask or any(r['count']!=repeats for r in report['results'])):
            raise ProtocolError('Successful VCTEST has missing/failed repetitions')
        if end['status']==2 and not mask:raise ProtocolError('Mismatch status without mismatches')
        report['clock_endpoints_stable']=end['cpu_hz_before']==end['cpu_hz_after'] and end['core_before']==end['core_after']
        if not report['clock_endpoints_stable']:raise ProtocolError('CPU clock/core endpoints changed; cannot rank safely')
        payloads=[]
        for _ in range(2):
            header=radio.command('VCTESTGET');m=re.fullmatch(r'DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)',header)
            if not m or int(m[1])!=samples or int(m[3])!=end['capture_us']:raise ProtocolError('Invalid VCTESTGET DATA header')
            payload=radio._read((samples*20+7)//8)
            if len(payload)!=(samples*20+7)//8 or zlib.crc32(payload)!=int(m[2],16):raise ProtocolError('VCTESTGET CRC mismatch')
            payloads.append(payload)
        if payloads[0]!=payloads[1]:raise ProtocolError('Retained VCTEST snapshot changed between reads')
        words=_unpack20(payloads[0],samples)
        if _pack20(words)!=payloads[0]:raise ProtocolError('Independent CAP20 roundtrip mismatch')
        iq=decode_iq(payloads[0],samples,10)
        i=(words&1023).astype(np.int32);q=((words>>10)&1023).astype(np.int32)
        i=np.where(i>=512,i-1024,i);q=np.where(q>=512,q-1024,q)
        if not np.array_equal(iq.real*512,i) or not np.array_equal(iq.imag*512,-q):raise ProtocolError('Independent signed I/Q decoding mismatch')
        blocks=samples//64;a=i[:blocks*64].astype(np.int64).reshape(blocks,64);b=q[:blocks*64].astype(np.int64).reshape(blocks,64)
        energy=((a*a+b*b).sum(axis=1)*64-a.sum(axis=1)**2-b.sum(axis=1)**2)//4096
        report['host_reference']={'cap20_crc_valid':True,'repeated_retrieval_identical':True,'iq20_roundtrip_exact':True,
            'samples_including_tail':samples,'iq20_words_crc32':f'{zlib.crc32(words.astype("<u4").tobytes()):08x}',
            'mean_energy':int(energy.sum()//blocks),'peak_energy':int(energy.max()),
            'full_raw_metadata_verified':False,'limitation':'CAP20 omits the upper12 metadata bits and guard words. Firmware raw_crc32 cannot be independently matched from this export; target comparisons cover full32-bit copy and guards.'}
        report['host_elapsed_us']=(time.monotonic_ns()-start)/1000
        for obj in report['results']:
            obj['median_us_at_endpoint_clock']=obj['median_cycles']*1e6/end['cpu_hz_before']
        capture=Capture(iq,rate_hz,frequency*1_000_000,stamp,start,time.monotonic_ns(),end['capture_us'],10,True,
            {'device':radio.info,'validate_copy_test':report,'timestamp_reference':'host test request, not RF arrival'})
        return report,capture
    except Exception as exc:
        radio.failed=True
        try:exc.report=report
        except Exception:pass
        raise

def clear_validate_copy(radio):
    if radio.command('VCTESTCLEAR')!='OK':raise ProtocolError('VCTESTCLEAR failed')
