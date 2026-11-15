import json

import pytest

from scripts.four_receiver_packets import CONFIG, accepted, payload, run, summarize


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
        first_end_us=500,
        last_end_us=9000,
    )
    value.update(extra)
    return value


def fresh_state(**extra):
    value = state(running=True, attempted=0, completed=0, scheduled=0, missed_slots=0, elapsed_us=0)
    value.update(extra)
    return value


def row(receiver=0, seq=2, condition='ON', **extra):
    hit = dict(
        sequence=seq,
        crc_verified=True,
        address_verified=True,
        full_known_payload_match=True,
        observed_payload_hex=payload(seq, 16).hex(),
        expected_payload_hex=payload(seq, 16).hex(),
    )
    hit.update(extra)
    return dict(
        receiver=receiver,
        condition=condition,
        transport_crc_valid=True,
        decoder={'full_payload_matches': [hit]},
    )


def empty_controls(receiver_count=4):
    return [
        row(receiver=k, condition=condition, crc_verified=False)
        for condition in ('OFF', 'ON')
        for k in range(receiver_count)
    ]


def test_union_denominator_duplicates():
    result = summarize(empty_controls() + [row(), row(1), row(3, 3)], fresh_state(), state(), 4)
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
        summarize([row()], fresh_state(), state(**change), 4)


@pytest.mark.parametrize('flag', ['crc_verified', 'address_verified', 'full_known_payload_match'])
def test_reject_unverified_hits(flag):
    assert accepted(row(**{flag: False})['decoder']) == []


def test_off_negative_and_out_of_range():
    with pytest.raises(ValueError, match='OFF'):
        summarize([row(condition='OFF')], fresh_state(), state(), 4)
    with pytest.raises(ValueError, match='outside'):
        summarize([row(seq=10)], fresh_state(), state(), 4)
    result = summarize(empty_controls(), fresh_state(), state(), 4)
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
        run([radio, Radio()], tx, tmp_path)
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


@pytest.mark.parametrize('condition', ['OFF', 'ON'])
@pytest.mark.parametrize('receiver', range(4))
def test_missing_control_or_receiver_rejected(condition, receiver):
    rows = [
        r
        for r in empty_controls()
        if not (r['condition'] == condition and r['receiver'] == receiver)
    ]
    with pytest.raises(ValueError, match='every receiver'):
        summarize(rows, fresh_state(), state(), 4)


@pytest.mark.parametrize('receiver', [True, False, -1, 4, 1.5, '0', None])
def test_invalid_receiver_rejected(receiver):
    rows = empty_controls()
    rows[0]['receiver'] = receiver
    with pytest.raises(ValueError, match='receiver index'):
        summarize(rows, fresh_state(), state(), 4)


@pytest.mark.parametrize(
    'value', [None, '', 'aa', '00' * 16, 'g' * 32, ' ' + payload(2, 16).hex(), payload(3, 16).hex()]
)
@pytest.mark.parametrize('field', ['observed_payload_hex', 'expected_payload_hex'])
def test_incomplete_or_wrong_payload_rejected(value, field):
    with pytest.raises(ValueError, match='known-payload'):
        accepted(row(**{field: value})['decoder'])


def test_missing_payload_fields_rejected():
    decoder = row()['decoder']
    del decoder['full_payload_matches'][0]['observed_payload_hex']
    del decoder['full_payload_matches'][0]['expected_payload_hex']
    with pytest.raises(ValueError, match='known-payload'):
        accepted(decoder)


def test_empty_campaign_rejected():
    with pytest.raises(ValueError, match='every receiver'):
        summarize([], fresh_state(), state(), 4)


@pytest.mark.parametrize(
    'change',
    [
        dict(running=False),
        dict(attempted=1),
        dict(completed=1),
        dict(scheduled=1),
        dict(missed_slots=1),
        dict(attempted=False),
    ],
)
def test_start_must_prove_fresh_run(change):
    with pytest.raises(ValueError, match='Fresh running'):
        summarize(empty_controls(), fresh_state(**change), state(), 4)


@pytest.mark.parametrize('elapsed', [0, 1, 7, 499])
def test_start_elapsed_is_live_clock_not_reset_variable(elapsed):
    result = summarize(empty_controls(), fresh_state(elapsed_us=elapsed), state(), 4)
    assert result['completed_transmissions'] == 10


@pytest.mark.parametrize('elapsed', [-1, True, 0.0, None, 500, 501])
def test_start_elapsed_must_precede_first_completed_packet(elapsed):
    with pytest.raises(ValueError, match='completion times'):
        summarize(empty_controls(), fresh_state(elapsed_us=elapsed), state(), 4)


@pytest.mark.parametrize(
    'change',
    [
        dict(first_end_us=0),
        dict(first_end_us=9001),
        dict(last_end_us=10001),
        dict(elapsed_us=False),
    ],
)
def test_completion_time_ordering_rejected(change):
    with pytest.raises(ValueError, match='completion times'):
        summarize(empty_controls(), fresh_state(elapsed_us=7), state(**change), 4)


@pytest.mark.parametrize('power', [-20, -16, -12, -8, -4, 0])
def test_explicit_controlled_power(power):
    from scripts.four_receiver_packets import configuration

    expected = configuration(power)
    result = summarize(
        empty_controls(),
        fresh_state(power_dbm=power),
        state(power_dbm=power),
        4,
        expected_config=expected,
    )
    assert result['completed_transmissions'] == 10


@pytest.mark.parametrize('power', [-40, 1, -10, True, '-20', None])
def test_unsupported_power_rejected(power):
    from scripts.four_receiver_packets import configuration

    with pytest.raises(ValueError, match='power'):
        configuration(power)


@pytest.mark.parametrize('changed', ['start', 'final'])
def test_power_drift_rejected(changed):
    from scripts.four_receiver_packets import configuration

    start, final = fresh_state(power_dbm=0), state(power_dbm=0)
    (start if changed == 'start' else final)['power_dbm'] = -20
    with pytest.raises(ValueError, match='configuration changed'):
        summarize(empty_controls(), start, final, 4, expected_config=configuration(0))


def test_expected_config_must_not_change_other_experiment_parameters():
    from scripts.four_receiver_packets import configuration

    expected = configuration(0)
    expected['interval_us'] = 2000
    with pytest.raises(ValueError, match='expected source'):
        summarize(empty_controls(), fresh_state(), state(), 4, expected_config=expected)


def test_nondefault_power_needs_explicit_expected_config():
    with pytest.raises(ValueError, match='configuration changed'):
        summarize(empty_controls(), fresh_state(power_dbm=0), state(power_dbm=0), 4)


@pytest.mark.parametrize(
    'count,stagger,delays', [(4, 0, [0, 0, 0, 0]), (4, 100, [0, 100, 200, 300]), (2, 250, [0, 250])]
)
def test_stagger_plan(count, stagger, delays):
    from scripts.four_receiver_packets import stagger_plan

    plan = stagger_plan(count, 16, 16000, stagger)
    assert plan['per_receiver_delay_ms'] == delays
    assert plan['last_capture_start_lower_bound_ms'] == 16 * max(delays) + 15 * 409.5
    assert 'NOT RF synchronization' in plan['note']


@pytest.mark.parametrize('stagger', [-1, 251, True, 100.0, '100'])
def test_invalid_stagger_rejected(stagger):
    from scripts.four_receiver_packets import stagger_plan

    with pytest.raises(ValueError, match='stagger'):
        stagger_plan(4, 16, 16000, stagger)


def test_impossible_stagger_budget_rejected():
    from scripts.four_receiver_packets import stagger_plan

    with pytest.raises(ValueError, match='lower-bound'):
        stagger_plan(4, 32, 30000, 250)
    # A feasible lower bound is not a promise the host will complete in time.
    assert stagger_plan(4, 16, 16000, 100)['last_capture_start_lower_bound_ms'] < 16000


@pytest.mark.parametrize('condition', ['ON', 'OFF'])
def test_host_delay_and_deadline_observation(monkeypatch, tmp_path, condition):
    import scripts.four_receiver_packets as campaign

    clock = iter([100, 400, 600])
    sleeps = []
    monkeypatch.setattr(campaign.time, 'monotonic_ns', lambda: next(clock))
    monkeypatch.setattr(campaign.time, 'sleep', sleeps.append)
    monkeypatch.setattr(campaign, 'capture', lambda *args: {'condition': condition})
    bounds = [200, 300] if condition == 'ON' else None
    result = campaign.delayed_capture(None, 3, 0, condition, tmp_path, 300, bounds)
    assert sleeps == [0.3]
    assert result['planned_host_delay_ms'] == 300
    assert result['host_capture_call_start_ns'] == 400
    if bounds:
        assert result['host_duration_deadline_observation'][
            'capture_call_started_after_latest_deadline'
        ]
    else:
        assert 'host_duration_deadline_observation' not in result
