"""Independent finite receiver coordinator; host scheduling is not RF synchronization."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
import time

from .protocol import Radio, RATES
from .recording import save_capture

TIMING_NOTE = ('Offsets schedule host worker connection/configuration starts, not RF starts. '
    'Host capture-call bounds include commands, device work and USB transfer. Nominal N/fs '
    'is per-receiver aperture only; clocks and RF windows are not synchronized. Overlap, '
    'unique RF coverage and continuous reception cannot be inferred from summed duties.')

@dataclass(frozen=True)
class ReceiverConfig:
    receiver_id: str
    port: str
    frequency_mhz: int = 2440
    rate_hz: int = 16000000
    bandwidth_mhz: int = 12
    gain: int = 40
    samples: int = 16380
    start_offset_ms: int = 0
    captures: int = 1


def validate_plan(configs):
    configs = list(configs)
    if not 1 <= len(configs) <= 16:
        raise ValueError('Plan requires 1–16 receivers')
    ids, ports = set(), set()
    for c in configs:
        if not isinstance(c, ReceiverConfig):raise ValueError('Expected ReceiverConfig')
        if not isinstance(c.receiver_id,str) or not c.receiver_id or any(x not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for x in c.receiver_id):
            raise ValueError('Receiver IDs must use letters, digits, underscore or hyphen')
        if not isinstance(c.port,str) or not c.port.strip():raise ValueError('Port is required')
        port = str(Path(c.port).expanduser().resolve())
        if c.receiver_id in ids or port in ports:raise ValueError('Duplicate receiver ID or resolved port')
        ids.add(c.receiver_id);ports.add(port)
        for name in ('frequency_mhz','rate_hz','bandwidth_mhz','gain','samples','start_offset_ms','captures'):
            if type(getattr(c,name)) is not int:raise ValueError(f'{name} must be an integer')
        if not 2400 <= c.frequency_mhz <= 2500 or c.rate_hz not in RATES:
            raise ValueError('Unsupported frequency or rate')
        if not 0 <= c.bandwidth_mhz <= 100 or not 0 <= c.gain <= 127:
            raise ValueError('Invalid bandwidth/gain; actual device limits checked after connection')
        if not 256 <= c.samples <= 16380 or not 0 <= c.start_offset_ms <= 60000 or not 1 <= c.captures <= 100:
            raise ValueError('Samples, offset or finite capture count outside bounds')
    return configs


def describe_plan(configs):
    configs = validate_plan(configs)
    lines = [f'{len(configs)} independent receiver(s); no hardware opened.', TIMING_NOTE]
    for c in configs:
        lines.append(f'{c.receiver_id}: {c.port}, {c.frequency_mhz} MHz, {c.rate_hz} samples/s, '
            f'bandwidth {c.bandwidth_mhz} MHz, gain {c.gain}, {c.captures} × {c.samples} samples; '
            f'host worker offset {c.start_offset_ms} ms; nominal aperture/capture {c.samples/c.rate_hz*1000:.6f} ms')
    return '\n'.join(lines)


def run_plan(configs, *, radio_factory=Radio, clock=time.monotonic_ns, sleep=time.sleep,
             output_directory=None, saver=save_capture):
    """Each worker owns and closes one Radio, including on connection/capture failure.

    Finite iteration limits and Radio's existing serial deadlines bound operations;
    no unsafe thread cancellation or shared serial instance is used.
    """
    configs = validate_plan(configs)
    out = Path(output_directory) if output_directory is not None else None
    if out is not None:out.mkdir(parents=True,exist_ok=False)
    epoch = clock()
    def worker(c):
        row = {'receiver_id':c.receiver_id,'config':asdict(c),'status':'running','captures':[],
               'scheduled_worker_start_ns':epoch+c.start_offset_ms*1000000}
        radio = None
        try:
            delay = (row['scheduled_worker_start_ns']-clock())/1e9
            if delay > 0:sleep(delay)
            row['actual_worker_start_ns'] = clock()
            row['host_start_lateness_ns'] = max(0,row['actual_worker_start_ns']-row['scheduled_worker_start_ns'])
            radio = radio_factory(c.port)
            row['device'] = radio.connect()
            radio.configure(c.frequency_mhz,c.rate_hz,c.bandwidth_mhz,c.gain,10)
            for index in range(c.captures):
                before = clock()
                capture = radio.capture(c.samples)
                after = clock()
                if not capture.crc_ok:raise RuntimeError('Raw capture CRC failed')
                if len(capture.iq)!=c.samples or capture.sample_rate_hz!=c.rate_hz or capture.frequency_hz!=c.frequency_mhz*1000000:
                    raise RuntimeError('Raw capture settings/count mismatch')
                item = {'index':index,'host_capture_call_start_ns':before,'host_capture_call_end_ns':after,
                        'host_capture_call_elapsed_ns':after-before,'nominal_rf_seconds':c.samples/c.rate_hz,
                        'samples':c.samples,'crc_valid':True,'host_request_timestamp':capture.timestamp}
                if out is not None:
                    capture.metadata['multi_receiver'] = {'receiver_id':c.receiver_id,'config':asdict(c),
                        'coordinator_epoch_ns':epoch,'timing_note':TIMING_NOTE}
                    item['sigmf'] = str(saver(capture,out/f'{c.receiver_id}-{index:04d}'))
                row['captures'].append(item)
            row['status']='passed'
        except Exception as exc:
            row['status']='failed';row['error']=repr(exc)
        finally:
            if radio is not None:
                try:radio.close();row['connection_closed']=True
                except Exception as exc:row['close_error']=repr(exc);row['status']='failed';row['connection_closed']=False
            row['host_finished_ns']=clock()
        row['successful_nominal_rf_seconds']=sum(x['nominal_rf_seconds'] for x in row['captures'])
        return row
    results = {}
    with ThreadPoolExecutor(max_workers=len(configs),thread_name_prefix='receiver') as executor:
        futures = {executor.submit(worker,c):c.receiver_id for c in configs}
        for f in as_completed(futures):results[futures[f]]=f.result()
    return {'status':'passed' if all(r['status']=='passed' for r in results.values()) else 'failed',
            'timing_note':TIMING_NOTE,'coordinator_epoch_ns':epoch,'host_finished_ns':clock(),
            'receivers':[results[c.receiver_id] for c in configs]}
