"""Strict finite PROF1 lab client. Histogram quantiles are bounded intervals, not exact percentiles."""
import json,time
from .protocol import ProtocolError,RATES

def run_profile(radio,milliseconds=2000,samples=16380,rate_hz=16000000,ratio_milli=4000,retain=False):
    if not 1<=milliseconds<=5000 or not 256<=samples<=16380 or rate_hz not in (16000000,40000000,80000000):raise ValueError('Invalid profile settings')
    if not 1000<=ratio_milli<=1000000:raise ValueError('Invalid threshold')
    info=radio.command('PROFINFO?').split()
    if len(info)!=5 or info[:2]!=['PROFINFO','1']:raise ProtocolError('Unsupported profile protocol')
    stage_count=int(info[4]);frequency=radio.settings['frequency_mhz'];code=RATES[rate_hz]
    expected=f'PROF1 BEGIN {milliseconds} {samples} {code} {ratio_milli} {int(retain)} {frequency}'
    started=time.monotonic_ns();result={'stages':{},'errors_received':[],'profile_info':' '.join(info)}
    try:
        if radio.command(f'PROF1 {milliseconds} {samples} {code} {ratio_milli} {int(retain)}')!=expected:raise ProtocolError('Invalid profile BEGIN')
        deadline=time.monotonic()+milliseconds/1000+10
        while True:
            line=radio._line(deadline)
            if line.startswith('ERR '):result['errors_received'].append(line);continue
            if line.startswith('PROF1 INIT '):
                if 'initialization' in result:raise ProtocolError('Duplicate profile INIT')
                result['initialization']=json.loads(line[len('PROF1 INIT '):]);continue
            if line.startswith('PROF1 STAGE '):
                stage=json.loads(line[len('PROF1 STAGE '):]);name=stage['name']
                if name in result['stages']:raise ProtocolError('Duplicate profile stage')
                for key in ('count','nonzero_count','sum_us','min_us','max_us'):
                    if type(stage.get(key)) is not int or stage[key]<0:raise ProtocolError('Invalid profile integer')
                for key in ('median_us','p95_us','p99_us'):
                    value=stage.get(key)
                    if not isinstance(value,list) or len(value)!=2 or any(type(x)is not int or x<0 for x in value) or value[0]>value[1]:raise ProtocolError('Invalid profile quantile interval')
                stage['mean_us']=stage['sum_us']/stage['count'] if stage['count'] else None
                result['stages'][name]=stage;continue
            if line.startswith('PROF1 END '):
                summary=json.loads(line[len('PROF1 END '):])
                if summary.get('version')!=1 or len(result['stages'])!=stage_count or 'initialization' not in result:raise ProtocolError('Incomplete profile')
                if summary.get('frequency_mhz')!=frequency or summary.get('sample_rate_hz')!=rate_hz:raise ProtocolError('Profile settings mismatch')
                count=summary.get('captures',-1)
                if type(count)is not int or count<0 or summary.get('total_samples')!=count*samples or summary.get('analyzed_samples')!=count*(samples//64)*64:raise ProtocolError('Profile count mismatch')
                if type(summary.get('wall_elapsed_us'))is not int or summary['wall_elapsed_us']<=0:raise ProtocolError('Invalid profile duration')
                summary['nominal_rf_duty_percent']=100*summary['total_samples']/rate_hz/(summary['wall_elapsed_us']/1e6)
                summary['nominal_decision_duty_percent']=100*max(0,count-summary['warmup_captures'])*(samples//64)*64/rate_hz/(summary['wall_elapsed_us']/1e6)
                result['summary']=summary;break
            raise ProtocolError('Unknown profiling record')
        result['host_total_elapsed_us']=(time.monotonic_ns()-started)/1000
        return result
    except Exception:
        radio.failed=True;raise
