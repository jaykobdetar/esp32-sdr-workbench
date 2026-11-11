"""Experimental DET1 client; requires separately built experimental firmware.
Never silently upgrades or flashes a connected device.
"""
from datetime import datetime,timezone
import json,time,re,zlib
from .protocol import Capture,ProtocolError,decode_iq,RATES

def run_detection(radio,milliseconds=2000,samples=16380,rate_hz=16_000_000,ratio_milli=4000,retain=True):
    if not 1<=milliseconds<=5000 or not 256<=samples<=16380 or not 1000<=ratio_milli<=1000000:raise ValueError('Invalid bounded detector request')
    if rate_hz not in (16_000_000,40_000_000,80_000_000):raise ValueError('Unsupported rate')
    transaction_start=time.monotonic_ns()
    info=radio.command('DETINFO?')
    if info!='DETINFO 1 5000 16 64':raise ProtocolError(f'Unsupported experimental detector version: {info}')
    frequency=radio.settings['frequency_mhz'];cmd=f'DET1 {milliseconds} {samples} {RATES[rate_hz]} {ratio_milli} {int(retain)}'
    start=time.monotonic_ns();stamp=datetime.now(timezone.utc).isoformat();errors=[]
    try:
        begin=radio.command(cmd)
        expected=f'DET1 BEGIN {milliseconds} {samples} {RATES[rate_hz]} {ratio_milli} {int(retain)} {frequency}'
        if begin!=expected:raise ProtocolError('Malformed detector begin')
        deadline=time.monotonic()+milliseconds/1000+5
        while True:
            line=radio._line(deadline)
            if line.startswith('ERR '):errors.append(line);continue
            if not line.startswith('DET1 END '):raise ProtocolError('Malformed detector end')
            summary=json.loads(line[len('DET1 END '):]);break
        if summary.get('version')!=1:raise ProtocolError('Unknown detector summary version')
        integer_fields=('status','captures','detections','warmup_captures','errors','wall_elapsed_us','total_samples','analyzed_samples','retained_samples','sample_rate_hz','frequency_mhz')
        if any(type(summary.get(key)) is not int or summary[key]<0 for key in integer_fields):raise ProtocolError('Invalid detector numeric fields')
        if summary['status'] not in (0,1) or summary['errors'] not in (0,1) or bool(summary['status'])!=bool(summary['errors']):raise ProtocolError('Inconsistent detector status')
        if summary['warmup_captures']!=min(summary['captures'],16):raise ProtocolError('Invalid detector warmup count')
        if summary['detections']>summary['captures']-summary['warmup_captures']:raise ProtocolError('Invalid detector event count')
        if summary['retained_samples'] and (not retain or not summary['detections']):raise ProtocolError('Unexpected retained detector event')
        if summary.get('sample_rate_hz')!=rate_hz or summary.get('frequency_mhz')!=frequency:raise ProtocolError('Detector settings mismatch')
        if summary.get('retained_samples') not in (0,samples) or summary.get('wall_elapsed_us',0)<=0:raise ProtocolError('Invalid detector sample count or timing')
        count=summary.get('captures',-1)
        if not isinstance(count,int) or count<0 or summary.get('total_samples')!=count*samples or summary.get('analyzed_samples')!=count*(samples//64)*64:raise ProtocolError('Inconsistent detector counters')
        summary['host_elapsed_us']=(time.monotonic_ns()-start)/1000
        summary['host_request_timestamp']=stamp;summary['errors_received']=errors
        summary['nominal_rf_duty_percent']=100*summary['total_samples']/summary['sample_rate_hz']/(summary['wall_elapsed_us']/1e6)
        summary['nominal_analyzed_duty_percent']=100*summary['analyzed_samples']/rate_hz/(summary['wall_elapsed_us']/1e6)
        summary['nominal_decision_duty_percent']=100*max(0,count-summary.get('warmup_captures',min(count,16)))*(samples//64)*64/rate_hz/(summary['wall_elapsed_us']/1e6)
        capture=None
        if summary['status']==0 and summary['retained_samples'] and retain:
            n=summary['retained_samples'];line=radio.command('DETGET');m=re.fullmatch(r'DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)',line)
            if not m or int(m[1])!=n:raise ProtocolError('Invalid retained capture header')
            data=radio._read((n*20+7)//8)
            if zlib.crc32(data)!=int(m[2],16):raise ProtocolError('Retained capture CRC mismatch')
            capture=Capture(decode_iq(data,n,10),summary['sample_rate_hz'],frequency*1_000_000,stamp,start,time.monotonic_ns(),int(m[3]),10,True,{'detector_summary':summary,'timestamp_reference':'detector run host start; exact event time unavailable','device':radio.info})
        summary['host_total_elapsed_us']=(time.monotonic_ns()-transaction_start)/1000
        summary['nominal_host_duty_percent']=100*summary['total_samples']/rate_hz/(summary['host_total_elapsed_us']/1e6)
        summary['nominal_host_decision_duty_percent']=100*max(0,count-summary.get('warmup_captures',min(count,16)))*(samples//64)*64/rate_hz/(summary['host_total_elapsed_us']/1e6)
        summary['retained_crc_valid']=bool(capture is not None and capture.crc_ok)
        summary['retained_event_count']=int(capture is not None)
        summary['timing_note']='Local duty excludes allocation, receiver preparation, protocol and retained IQ transfer. Host total includes DETINFO, run and retrieval. Event timestamp is run start, not packet arrival.'
        return summary,capture
    except Exception:
        radio.failed=True;raise
