"""Strict PPROF1 telemetry adapter; reuses DETPIPE1 validation and CRC handling.

Profile intervals describe histogram bounds, not point quantile estimates.
No serial ports are opened here. Caller configures and owns the radio.
"""
import json
import time
from .pipeline import run_pipeline
from .protocol import ProtocolError, Radio

class ProfileMemoryError(ProtocolError):
    """Complete pre-BEGIN allocation rejection; no capture transaction began."""


STAGES = ('prepare','calibration_check','tune_calibration','gain','rx_prepare','clear',
          'filter_apply','register_setup','trigger_to_done','poll_after_overlap',
          'hardware_finalize','register_restore','filter_restore','validate_or_fused_copy',
          'acquire_total','energy','decision_including_retention','retention',
          'separate_copy','yield','iteration','timer_pair','histogram_update')
INIT_FIELDS = {'version','stages','init_us','hist_bytes','timer_observations',
               'telemetry_gap_min_ms','yield_cap_us'}
STAGE_FIELDS = {'id','name','count','sum_us','min_us','max_us',
                'p50_lo','p50_hi','p95_lo','p95_hi','p99_lo','p99_hi'}
END_EXTRA = {'copy_option','fused_active','profile_enabled','yield_cadence',
             'yield_cap_us','yield_count','max_yield_gap_us','init_us','telemetry_us'}


def _object(line, prefix):
    if not isinstance(line,str) or not line.startswith(prefix) or len(line)>4096:
        raise ProtocolError('Invalid profile frame')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ProtocolError('Duplicate profile JSON field')
            result[key]=value
        return result
    try:
        obj=json.loads(line[len(prefix):],object_pairs_hook=pairs)
    except (ValueError,TypeError) as exc:
        raise ProtocolError('Invalid profile JSON') from exc
    if not isinstance(obj,dict):raise ProtocolError('Invalid profile object')
    return obj


def _uints(obj, fields):
    if any(type(obj.get(k)) is not int or not 0<=obj[k]<=2**64-1 for k in fields):
        raise ProtocolError('Invalid profile integer field')


def parse_init(line):
    obj=_object(line,'PPROF1 INIT ')
    version=obj.get('version')
    fields=INIT_FIELDS if version==1 else INIT_FIELDS|{'bins_count_bits','overflow'}
    if set(obj)!=fields:raise ProtocolError('Invalid profile INIT fields')
    _uints(obj,fields-{'overflow'})
    if (version not in (1,2) or obj['stages']!=23 or
        obj['hist_bytes']!={1:43424,2:22080}[version] or
        obj['timer_observations']!=255 or obj['telemetry_gap_min_ms']!=20 or
        obj['yield_cap_us']!=100000):
        raise ProtocolError('Unsupported profile INIT')
    if version==2 and (obj['bins_count_bits']!=16 or obj['overflow'] is not False):
        raise ProtocolError('Invalid compact histogram INIT')
    return obj


def parse_stage(line, expected_id):
    obj=_object(line,'PPROF1 STAGE ')
    if set(obj)!=STAGE_FIELDS:raise ProtocolError('Invalid profile STAGE fields')
    _uints(obj,STAGE_FIELDS-{'name'})
    if not 0<=expected_id<23 or obj['id']!=expected_id or obj['name']!=STAGES[expected_id]:
        raise ProtocolError('Profile stage order/name mismatch')
    if any(obj[k]>2**32-1 for k in STAGE_FIELDS-{'name','sum_us'}):
        raise ProtocolError('Profile uint32 overflow')
    count,lo,hi=obj['count'],obj['min_us'],obj['max_us']
    if lo>hi or not count*lo<=obj['sum_us']<=count*hi:
        raise ProtocolError('Inconsistent profile sum/extrema')
    if count==0 and any(obj[k] for k in STAGE_FIELDS-{'id','name'}):
        raise ProtocolError('Nonempty empty histogram')
    for q in (50,95,99):
        if not lo<=obj[f'p{q}_lo']<=obj[f'p{q}_hi']<=hi:
            raise ProtocolError('Invalid profile quantile interval')
    for side in ('lo','hi'):
        if not obj[f'p50_{side}']<=obj[f'p95_{side}']<=obj[f'p99_{side}']:
            raise ProtocolError('Nonmonotonic profile quantiles')
    return obj


class _ProfileRadio:
    """Consume profile telemetry while leaving original DETPIPE parser intact."""
    def __init__(self,radio,enabled,cadence,samples):
        self.radio=radio
        self.enabled=enabled
        self.cadence=cadence
        self.samples=samples
        self.init=None
        self.stages=[]
        self.memory_rejection_verified=False
        self.overflow=False
    def __getattr__(self,key):return getattr(self.radio,key)
    @property
    def failed(self):return self.radio.failed
    @failed.setter
    def failed(self,value):self.radio.failed=value
    def command(self,cmd):
        healthy=not self.radio.failed
        try:
            line=self.radio.command(cmd)
        except ProtocolError as exc:
            # Radio.command raises only after consuming a newline-delimited ERR.
            # Match its exact concrete implementation, full request and response,
            # and healthy before/after state. Never reinterpret transport failures.
            if (self.enabled and cmd.startswith('DETPIPE1 ') and healthy and
                not self.radio.failed and
                getattr(self.radio.command,'__func__',None) is Radio.command and
                type(exc) is ProtocolError and
                str(exc)==f'{cmd}: ERR pipeline_profile_memory'):
                self.memory_rejection_verified=True
                raise ProfileMemoryError('ERR pipeline_profile_memory') from exc
            raise
        if self.enabled and cmd.startswith('DETPIPE1 '):
            if line=='ERR pipeline_profile_memory' and healthy and not self.radio.failed:
                self.memory_rejection_verified=True
                raise ProfileMemoryError(line)
            if line.startswith('ERR '):raise ProtocolError(line)
            self.init=parse_init(line)
            return self.radio._line(time.monotonic()+5)
        return line
    def _line(self,deadline):
        while True:
            line=self.radio._line(deadline)
            if self.enabled and line=='ERR pipeline_profile_overflow':
                self.overflow=True
                continue
            if self.enabled and line.startswith('PPROF1 STAGE '):
                if self.overflow:raise ProtocolError('Stage distribution after histogram overflow')
                self.stages.append(parse_stage(line,len(self.stages)))
                continue
            if line.startswith('DETPIPE1 END '):
                if self.overflow:
                    obj=_object(line,'DETPIPE1 END ')
                    exc=ProtocolError('ERR pipeline_profile_overflow')
                    exc.profile_end=obj
                    if (type(obj.get('status')) is not int or obj['status']!=2 or
                        type(obj.get('profile_overflow')) is not int or obj['profile_overflow']!=1):
                        raise ProtocolError('Overflow without status2/profile_overflow1')
                    raise exc
                if self.enabled and len(self.stages)!=23:raise ProtocolError('Incomplete profile stages')
                obj=_object(line,'DETPIPE1 END ')
                _uints(obj,END_EXTRA)
                if self.enabled and self.init['version']==2 and (
                    type(obj.get('profile_overflow')) is not int or obj['profile_overflow']!=0):
                    raise ProtocolError('Compact END requires profile_overflow0')
                if (obj['copy_option']!=1 or obj['fused_active']!=int(self.samples==16380) or
                    obj['profile_enabled']!=int(self.enabled) or obj['yield_cadence']!=self.cadence or
                    obj['yield_cap_us']!=100000):
                    raise ProtocolError('Profile END selector mismatch')
            elif self.stages:
                raise ProtocolError('Unexpected line after profile telemetry began')
            return line


def run_pipeline_profile(radio, *, enabled=True, cadence=32, milliseconds=2000,
                         samples=16380, rate_hz=16000000, ratio_milli=4000, retain=False):
    if type(enabled) is not bool or type(cadence) is not int or cadence not in (32,64,128):
        raise ValueError('Invalid profile mode or yield cadence')
    # Validate request before making persistent selector changes.
    if (any(type(v) is not int for v in (milliseconds,samples,rate_hz,ratio_milli)) or
        not 1<=milliseconds<=5000 or not 256<=samples<=16380 or
        rate_hz not in (16000000,40000000,80000000) or
        not 1000<=ratio_milli<=1000000 or type(retain) is not bool):
        raise ValueError('Invalid pipeline profile request')
    # Conservative common safe envelope: compact firmware has no pre-run version query.
    if enabled and (milliseconds>2000 or samples!=16380 or rate_hz!=16000000):
        raise ValueError('Profile ON requires <=2000ms, 16380 samples and 16MS/s')
    if radio.failed:
        raise ProtocolError('Radio already failed; reconnect before profile run')
    try:
        for command,expected in ((f'PIPEPROFILE {int(enabled)}',f'PIPEPROFILE {int(enabled)}'),
                                 ('PIPEPROFILE?',f'PIPEPROFILE {int(enabled)}'),
                                 (f'PIPEYIELD {cadence}',f'PIPEYIELD {cadence} 100000'),
                                 ('PIPEYIELD?',f'PIPEYIELD {cadence} 100000')):
            if radio.command(command)!=expected:raise ProtocolError('Profile selector/readback mismatch')
        adapter=_ProfileRadio(radio,enabled,cadence,samples)
        summary,capture=run_pipeline(adapter,milliseconds,samples,rate_hz,ratio_milli,retain,kernel=3,optimized=True,copy_option=1)
        _uints(summary,END_EXTRA)
        if (summary['copy_option']!=1 or summary['fused_active']!=int(samples==16380) or
            summary['profile_enabled']!=int(enabled) or summary['yield_cadence']!=cadence or
            summary['yield_cap_us']!=100000):
            raise ProtocolError('Profile END selector mismatch')
        if summary['status']==0 and summary['max_yield_gap_us']>100000:
            raise ProtocolError('Successful profile exceeded yield cap')
        if enabled:
            stages=adapter.stages
            counts={s['name']:s['count'] for s in stages}
            count=summary['captures']
            if summary['init_us']!=adapter.init['init_us']:raise ProtocolError('Profile INIT/END timing mismatch')
            if counts['timer_pair']!=255:raise ProtocolError('Profile timer observation mismatch')
            if (counts['energy']!=count or counts['decision_including_retention']!=count or
                counts['yield']!=summary['yield_count']):
                raise ProtocolError('Profile processing count mismatch')
            if summary['status']==0 and (counts['acquire_total']!=count or counts['iteration']!=count):
                raise ProtocolError('Profile acquisition count mismatch')
            if counts['histogram_update']!=sum(s['count'] for s in stages[:-1]):
                raise ProtocolError('Profile histogram overhead count mismatch')
            summary['profile_init']=adapter.init
            summary['profile_stages']=stages
        else:
            summary['profile_init']=None
            summary['profile_stages']=[]
        summary['profile_quantile_semantics']='All-observation histogram interval bounds; not point estimates. Nested/overlapped stages must not be summed.'
        return summary,capture
    except ProfileMemoryError:
        if not adapter.memory_rejection_verified:
            radio.failed=True
            raise
        # The firmware has freed partial allocations and emitted one complete line.
        # Base run_pipeline flags all exceptions; this exact pre-BEGIN rejection
        # is the sole deliberate recovery exception. No unread frame remains.
        radio.failed=False
        raise
    except Exception as exc:
        radio.failed=True
        if 'adapter' in locals():
            exc.profile_partial={'init':adapter.init,'stages':list(adapter.stages)}
        raise
