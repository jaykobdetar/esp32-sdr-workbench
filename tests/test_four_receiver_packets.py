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
