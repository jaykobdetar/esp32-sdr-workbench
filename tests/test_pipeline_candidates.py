"""Three-crop protocol coverage with a bounded fake transport, no hardware."""

import copy
import json
import zlib

import pytest

from sdr_research.pipeline import run_pipeline, run_pipeline_candidates
from sdr_research.protocol import ProtocolError


class CandidateRadio:
    def __init__(self):
        self.settings = {'frequency_mhz': 2440}
        self.info = {'caps': []}
        self.failed = False
        self.commands = []
        self.corrupt_slot = None
        self.reply_keep = 'PIPEKEEP 3'
        self.active_slot = 1
        self.summary = dict(
            version=1,
            kernel=0,
            status=0,
            captures=20,
            processed_captures=20,
            detections=3,
            background_adc2=1,
            best_ratio_milli=9000,
            wall_elapsed_us=2000,
            completion_observed_us=1700,
            acquire_call_us_includes_overlap=1900,
            energy_compute_us=1000,
            copy_us=50,
            decision_us=10,
            retention_copy_us=5,
            retained_samples=5120,
            frequency_mhz=2440,
            total_samples=20 * 16380,
            analyzed_samples=20 * 16320,
            sample_rate_hz=16000000,
            errors=0,
            warmup_captures=16,
            background_policy=2,
            background_q16=65536,
            gain_register_start=40,
            gain_register_end=40,
            hardware_agc=0,
            gain_index_requested=40,
            first_trigger_device_us=1000,
            last_trigger_device_us=2000,
            retained_trigger_device_us=1800,
            retained_generation=19,
            retention_capacity=3,
            retained_candidates=[
                dict(
                    slot=0,
                    samples=5120,
                    offset_samples=64,
                    generation=17,
                    trigger_device_us=1600,
                    score_milli=5000,
                    capture_us=100,
                ),
                dict(
                    slot=1,
                    samples=5120,
                    offset_samples=128,
                    generation=19,
                    trigger_device_us=1800,
                    score_milli=9000,
                    capture_us=110,
                ),
                dict(
                    slot=2,
                    samples=5120,
                    offset_samples=256,
                    generation=20,
                    trigger_device_us=2000,
                    score_milli=6000,
                    capture_us=120,
                ),
            ],
        )
        self.payload = bytes(5120 * 20 // 8)

    def command(self, command):
        self.commands.append(command)
        if command == 'PIPEKERNEL 0':
            return command
        if command == 'DETPIPEINFO?':
            return 'DETPIPEINFO 1 5000 16 64'
        if command in ('PIPEKEEP 3', 'PIPEKEEP?'):
            return self.reply_keep
        if command.startswith('DETPIPE1 '):
            return 'DETPIPE1 BEGIN 2000 16380 6 4000 1 2440'
        if command.startswith('DETPIPEGET'):
            self.active_slot = 1 if command == 'DETPIPEGET' else int(command.split()[1])
            item = self.summary['retained_candidates'][self.active_slot]
            crc = zlib.crc32(self.payload) ^ int(self.corrupt_slot == self.active_slot)
            return f'DATA 5120 {crc:08x} {item["capture_us"]}'
        raise AssertionError(command)

    def _line(self, deadline):
        return 'DETPIPE1 END ' + json.dumps(self.summary)

    def _read(self, size):
        assert size == len(self.payload)
        return self.payload


def test_three_crops_are_crc_checked_and_keep_independent_metadata():
    radio = CandidateRadio()
    summary, captures = run_pipeline_candidates(radio)
    assert [c.metadata['retained_generation'] for c in captures] == [19, 17, 20]
    assert [c.metadata['trigger_device_us'] for c in captures] == [1800, 1600, 2000]
    assert [c.metadata['crop_offset_samples'] for c in captures] == [128, 64, 256]
    assert all(len(c.iq) == 5120 and c.crc_ok for c in captures)
    assert summary['retained_event_count'] == 3
    assert radio.commands[-3:] == ['DETPIPEGET', 'DETPIPEGET 0', 'DETPIPEGET 2']
    assert 'not UTC' in captures[0].metadata['trigger_timestamp_reference']
    assert summary['host_total_elapsed_us'] >= summary['host_run_elapsed_us']
    json.dumps(captures[0].metadata)


def test_single_return_can_opt_in_but_only_reads_strongest():
    radio = CandidateRadio()
    _, capture = run_pipeline(radio, candidate_count=3)
    assert len(capture.iq) == 5120
    assert capture.metadata['retained_candidate']['slot'] == 1
    assert radio.commands[-1] == 'DETPIPEGET'


@pytest.mark.parametrize('slot', [0, 1, 2])
def test_crc_failure_poisoned(slot):
    radio = CandidateRadio()
    radio.corrupt_slot = slot
    with pytest.raises(ProtocolError, match='CRC'):
        run_pipeline_candidates(radio)
    assert radio.failed


@pytest.mark.parametrize('count', [True, 0, 2, 4, 3.0])
def test_invalid_candidate_count_has_no_io(count):
    radio = CandidateRadio()
    with pytest.raises(ValueError):
        run_pipeline(radio, candidate_count=count)
    assert not radio.commands


def test_policy_readback_failure_poisoned():
    radio = CandidateRadio()
    radio.reply_keep = 'ERR unsupported'
    with pytest.raises(ProtocolError, match='PIPEKEEP'):
        run_pipeline_candidates(radio)
    assert radio.failed
    assert not any(c.startswith('DETPIPE1 ') for c in radio.commands)


@pytest.mark.parametrize(
    'field,bad',
    [
        ('slot', 3),
        ('samples', 1024),
        ('offset_samples', 16380),
        ('offset_samples', 7),
        ('score_milli', 2**32),
        ('generation', 16),
        ('trigger_device_us', 999),
        ('score_milli', -1),
        ('capture_us', True),
    ],
)
def test_bad_descriptors_rejected_before_retrieval(field, bad):
    radio = CandidateRadio()
    radio.summary['retained_candidates'][0][field] = bad
    with pytest.raises(ProtocolError):
        run_pipeline_candidates(radio)
    assert radio.failed
    assert not any(c.startswith('DETPIPEGET') for c in radio.commands)


def test_duplicate_candidate_rejected():
    radio = CandidateRadio()
    radio.summary['retained_candidates'][2] = copy.deepcopy(radio.summary['retained_candidates'][0])
    with pytest.raises(ProtocolError):
        run_pipeline_candidates(radio)
