import pytest

from sdr_research.lab_session import default_receiver_settings, validate_receiver
from sdr_research.stream_acquisition import StreamAcquisitionWorker


class FakeRadio:
    closed = False

    def __init__(self, *args, **kwargs):
        self.info = {'caps': ['DSTREAM', 'DSTREAMIQ']}

    def connect(self):
        return self.info

    def configure(self, **kwargs):
        self.configuration = kwargs

    def close(self):
        self.closed = True


@pytest.fixture
def setup(monkeypatch, tmp_path):
    import sdr_research.stream_acquisition as module

    radios = []

    def radio(*args, **kwargs):
        r = FakeRadio()
        radios.append(r)
        return r

    monkeypatch.setattr(module, 'Radio', radio)
    monkeypatch.setattr(module, 'clock_probe', lambda *args, **kwargs: {'offset_us': 1000})
    monkeypatch.setattr(module, 'select_background_policy', lambda *args: None)
    settings = default_receiver_settings() | {'mode': 'DSTREAMIQ', 'autosave': False}
    worker = StreamAcquisitionWorker('fake', settings, tmp_path / 'output')
    return module, worker, radios


def snapshot():
    return dict(
        payload=bytes(40950),
        samples=16380,
        bits=10,
        sample_rate=16000000,
        frequency_mhz=2440,
        transport_crc_valid=True,
        trigger_us=100,
        generation=1,
    )


def test_no_save_sparse_capture_and_stop(setup, monkeypatch):
    module, w, radios = setup

    def run(radio, **kw):
        assert kw['keep_records'] is False and kw['milliseconds'] == 600000
        assert kw['yield_phase'] == 32 and kw['snapshot_every'] == 2667
        kw['on_record']({'flags': 1})
        kw['on_snapshot'](snapshot())
        kw['stop'].set()
        return {'summary': {'captures': 1}, 'records': []}

    monkeypatch.setattr(module, 'run_stream', run)
    w.run()
    assert w.error is None and radios[0].closed
    assert not w.output_dir.exists()
    assert w.capture_count == 1 and w.retained_count == 1
    c, _, stats = w.frames[-1]
    assert len(c.iq) == 16380 and c.crc_ok and c.metadata['sparse_iq']
    assert stats['sparse_iq'] and stats['count'] == 1


def test_save_and_bounded_restart(setup, monkeypatch):
    module, w, radios = setup
    w.settings['autosave'] = True
    calls = []

    def run(radio, **kw):
        calls.append(1)
        kw['on_record']({'flags': 0})
        kw['on_snapshot'](snapshot())
        if len(calls) == 2:
            kw['stop'].set()
        return {'summary': {'captures': 1}, 'records': []}

    monkeypatch.setattr(module, 'run_stream', run)
    w.run()
    assert w.error is None and w.run_count == 2
    assert len(list(w.output_dir.glob('*.sigmf-meta'))) == 2
    assert len(list(w.output_dir.glob('*.dstreamiq.json'))) == 2
    assert radios[0].closed


def test_protocol_failure_closes(setup, monkeypatch):
    module, w, radios = setup

    def fail(*args, **kwargs):
        raise RuntimeError('CRC mismatch')

    monkeypatch.setattr(module, 'run_stream', fail)
    w.run()
    assert 'CRC' in str(w.error) and radios[0].closed
    assert not w.output_dir.exists()


def test_missing_capability(setup, monkeypatch):
    module, w, radios = setup
    monkeypatch.setattr(FakeRadio, 'connect', lambda self: self.info.update(caps=[]) or self.info)
    w.run()
    assert 'lacks' in str(w.error) and radios[0].closed


@pytest.mark.parametrize('change', [{'samples': 4096}, {'rate_hz': 40000000}, {'bits': 8}])
def test_reject_incompatible_stream_settings(change):
    with pytest.raises(ValueError):
        validate_receiver(default_receiver_settings() | {'mode': 'DSTREAMIQ'} | change, False)


def test_recording_failure_is_reported_and_radio_closed(setup, monkeypatch):
    module, w, radios = setup
    w.settings['autosave'] = True

    def fail_save(*args):
        raise OSError('disk full')

    monkeypatch.setattr(module, 'save_capture', fail_save)

    def run(radio, **kw):
        kw['on_record']({'flags': 0})
        kw['on_snapshot'](snapshot())
        kw['stop'].set()
        return {'summary': {'captures': 1}, 'records': []}

    monkeypatch.setattr(module, 'run_stream', run)
    w.run()
    assert 'disk full' in str(w.error)
    assert radios[0].closed
