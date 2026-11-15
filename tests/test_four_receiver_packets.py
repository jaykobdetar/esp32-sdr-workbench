import json

import pytest

from scripts.four_receiver_packets import CONFIG, accepted, run, summarize


def state(**extra):
    value = dict(
        CONFIG,
        hop_list=[],
        payload_hex='',
        version='0.2.2',
        healthy=True,
        errors=0,
        timing_saturated=False,
        running=False,
        uptime_ms=1000,
        attempted=10,
        completed=10,
        scheduled=12,
        missed_slots=2,
        elapsed_us=10000,
    )
    value.update(extra)
    return value


def row(receiver=0, seq=2, condition='ON', **extra):
    hit = dict(
        sequence=seq,
        crc_verified=True,
        address_verified=True,
        full_known_payload_match=True,
        observed_payload_hex='aa',
        expected_payload_hex='aa',
    )
    hit.update(extra)
    return dict(
        receiver=receiver,
        condition=condition,
        transport_crc_valid=True,
        decoder={'full_payload_matches': [hit]},
    )


def test_union_denominator_duplicates():
    result = summarize([row(), row(1), row(3, 3)], state(), state(), 4)
    assert result['unique_packets'] == 2
    assert result['recovery_percent'] == 20
    assert result['duplicate_observations'] == 1
    assert result['per_receiver_unique'] == [1, 1, 0, 1]


@pytest.mark.parametrize(
    'change',
    [
        dict(completed=9),
        dict(attempted=11),
        dict(scheduled=11),
        dict(completed=0, attempted=0),
        dict(running=True),
        dict(version='other'),
        dict(uptime_ms=999),
        dict(timing_saturated=True),
        dict(errors=1),
        dict(payload_hex='aa'),
        dict(completed=True),
    ],
)
def test_reject_denominator(change):
    with pytest.raises(ValueError):
        summarize([row()], state(), state(**change), 4)


@pytest.mark.parametrize('flag', ['crc_verified', 'address_verified', 'full_known_payload_match'])
def test_reject_unverified_hits(flag):
    assert accepted(row(**{flag: False})['decoder']) == []


def test_off_negative_and_out_of_range():
    with pytest.raises(ValueError, match='OFF'):
        summarize([row(condition='OFF')], state(), state(), 4)
    with pytest.raises(ValueError, match='outside'):
        summarize([row(seq=10)], state(), state(), 4)
    result = summarize([row(condition='OFF', crc_verified=False)], state(), state(), 4)
    assert result['unique_packets'] == 0


def test_failure_stops_and_closes(tmp_path):
    class TX:
        stops = 0

        def stop(self):
            self.stops += 1
            return state()

        def status(self):
            return state()

        def configure(self, **_):
            return state()

    class Radio:
        closed = False

        def connect(self):
            raise RuntimeError('bad receiver')

        def close(self):
            self.closed = True

    tx, radio = TX(), Radio()
    with pytest.raises(RuntimeError, match='bad receiver'):
        run([radio], tx, tmp_path)
    assert tx.stops == 2
    assert radio.closed
    assert 'failed' in (tmp_path / 'results.json').read_text()


@pytest.mark.parametrize('fail_cleanup', [False, True])
def test_complete_lifecycle_with_fake_hardware(tmp_path, monkeypatch, fail_cleanup):
    import scripts.four_receiver_packets as campaign

    class TX:
        stops = 0
        started = False
        starts = []

        def stop(self):
            self.stops += 1
            if fail_cleanup and self.stops == 2:
                raise RuntimeError('STOP failed')
            return state()

        def status(self):
            return state(uptime_ms=1002 if self.started else 1000)

        def configure(self, **_):
            return state()

        def start(self, **kwargs):
            self.starts.append(kwargs)
            self.started = True
            return state(
                running=True, attempted=0, completed=0, scheduled=0, missed_slots=0, elapsed_us=0
            )

    class Radio:
        closed = False
        info = {'caps': ['CALHASH']}
        clock = 0

        def connect(self):
            return {'protocol': 6}

        def command(self, _):
            self.clock += 1
            return 'CALHASH ' + json.dumps(
                dict(
                    version=1, algorithm='sha256', bytes=1904, sha256='a' * 64, device_us=self.clock
                )
            )

        def configure(self, *_):
            pass

        def close(self):
            self.closed = True

    def fake_capture(r, receiver, index, condition, output):
        value = row(receiver, seq=receiver)
        value.update(index=index, condition=condition, file=condition)
        return value

    monkeypatch.setattr(campaign, 'capture', fake_capture)
    monkeypatch.setattr(campaign.np, 'load', lambda path: path.name)
    monkeypatch.setattr(
        campaign, 'decode', lambda condition, *_: row(crc_verified=condition == 'ON')['decoder']
    )
    tx, radios = TX(), [Radio() for _ in range(4)]
    result = run(radios, tx, tmp_path, captures=2, duration_ms=8000)
    assert result['status'] == ('failed' if fail_cleanup else 'passed')
    if fail_cleanup:
        assert result['cleanup_errors'] == ["RuntimeError('STOP failed')"]
    assert len(result['captures']) == 16
    assert result['analysis']['unique_packets'] == 1
    assert tx.starts == [{'count': 20000, 'duration_ms': 8000}]
    assert tx.stops == 2
    assert all(r.closed for r in radios)


def test_calibration_ignores_timestamp_but_rejects_changes():
    from scripts.four_receiver_packets import check_calibration

    before = [{'sha256': 'a' * 64, 'bytes': 1904, 'device_us': 100}]
    after = [{'sha256': 'a' * 64, 'bytes': 1904, 'device_us': 200}]
    check_calibration(before, after)
    after[0]['sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='fingerprint'):
        check_calibration(before, after)
    after[0].update(sha256='a' * 64, device_us=99)
    with pytest.raises(ValueError, match='reset'):
        check_calibration(before, after)
