import json
import sys
import zlib

import pytest

from scripts.dual_sparse_campaign import decode_saved, main, packet_union, save_snapshot


def decoded(run='one', receiver=0, sequence=7, crc=True, address=True, known=True):
    return dict(
        run_id=run,
        receiver=receiver,
        decoder=dict(
            full_payload_matches=[
                dict(
                    sequence=sequence,
                    crc_verified=crc,
                    address_verified=address,
                    full_known_payload_match=known,
                    observed_payload_hex='52465458',
                    expected_payload_hex='52465458',
                )
            ]
        ),
    )


def test_union_deduplicates_only_within_a_run_and_preserves_receiver_contributions():
    rows = [decoded(), decoded(), decoded(receiver=1), decoded(receiver=1, sequence=8)]
    result = packet_union('one', rows)
    assert result['unique_union'] == 2
    assert result['per_receiver_unique'] == [1, 2]
    assert result['shared'] == 1 and result['only_b'] == 1
    with pytest.raises(ValueError, match='identity'):
        packet_union('one', rows + [decoded(run='two')])
    assert packet_union('two', [decoded(run='two')])['unique_union'] == 1


@pytest.mark.parametrize('keyword', ['crc', 'address', 'known'])
def test_unverified_or_partial_hits_never_count(keyword):
    assert packet_union('one', [decoded(**{keyword: False})])['unique_union'] == 0


def test_payload_inconsistency_is_not_a_valid_union():
    row = decoded()
    row['decoder']['full_payload_matches'][0]['expected_payload_hex'] = '00'
    with pytest.raises(ValueError, match='payload'):
        packet_union('one', [row])


def test_private_snapshot_persistence_and_corruption_guard(tmp_path):
    raw = bytes(40950)
    snapshot = dict(payload=raw, generation=1024, crc32=zlib.crc32(raw), samples=16380)
    metadata = save_snapshot(tmp_path, 'one', 0, snapshot)
    assert (tmp_path / metadata['file']).read_bytes() == raw
    assert 'payload' not in json.loads(next(tmp_path.glob('*.json')).read_text())
    with pytest.raises(FileExistsError):
        save_snapshot(tmp_path, 'one', 0, snapshot)
    (tmp_path / metadata['file']).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='CRC/size'):
        decode_saved(tmp_path, dict(run_id='one', snapshots=[metadata]))
    with pytest.raises(ValueError, match='run mismatch'):
        decode_saved(tmp_path, dict(run_id='two', snapshots=[metadata]))


def test_dryrun_does_not_open_devices(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'campaign',
            '--port',
            '/nonexistent/a',
            '--port',
            '/nonexistent/b',
            '--tx-serial',
            'not-real',
            '--output',
            str(tmp_path / 'not-created'),
        ],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result['mode'] == 'dry-run'
    assert not (tmp_path / 'not-created').exists()


@pytest.mark.parametrize(
    'option,value',
    [('--seconds', '56'), ('--seconds', 'nan'), ('--trials', '0'), ('--snapshot-every', '1')],
)
def test_reject_unbounded_or_unsupported_runs(monkeypatch, tmp_path, option, value):
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'campaign',
            '--port',
            '/a',
            '--port',
            '/b',
            '--tx-serial',
            'x',
            '--output',
            str(tmp_path),
            option,
            value,
        ],
    )
    with pytest.raises(SystemExit):
        main()


@pytest.mark.parametrize('source_on', [False, True])
def test_bounded_source_run_and_joint_stop(monkeypatch, tmp_path, source_on):
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import Mock

    import scripts.dual_sparse_campaign as module

    calls = []

    def stream(radio, **kwargs):
        calls.append(kwargs)
        return {'summary': {'captures': 1}}

    monkeypatch.setattr(module, 'run_stream', stream)
    monkeypatch.setattr(module, 'clock_probe', lambda _: {'offset_us': 0})
    tx = Mock()
    tx.status.return_value = {'running': False}
    tx.start.return_value = {'ok': True}
    radios = [Mock(), Mock()]
    with ThreadPoolExecutor(2) as pool:
        campaign = module.SparseCampaign(radios, tx, pool, tmp_path)
        campaign.save = Mock()
        campaign.report['anchors'] = [
            dict(a_us=i * 1000, b_us=i * 1000 + 50, pair=i) for i in range(3)
        ]
        campaign.run_sparse(30000, 1875000, 1024, source_on, 0)
    assert len(calls) == 2
    assert calls[0]['stop'] is calls[1]['stop'] and calls[0]['stop'].is_set()
    assert tx.stop.call_count == 2
    if source_on:
        tx.start.assert_called_once_with(count=0, duration_ms=32000)
    else:
        tx.start.assert_not_called()


def test_worker_error_stops_source_and_both_receivers(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import Mock

    import scripts.dual_sparse_campaign as module

    stops = []

    def stream(radio, **kwargs):
        stops.append(kwargs['stop'])
        raise RuntimeError('simulated transport failure')

    monkeypatch.setattr(module, 'run_stream', stream)
    monkeypatch.setattr(module, 'clock_probe', lambda _: {'offset_us': 0})
    tx = Mock()
    with ThreadPoolExecutor(2) as pool:
        campaign = module.SparseCampaign([Mock(), Mock()], tx, pool, tmp_path)
        campaign.save = Mock()
        campaign.report['anchors'] = [
            dict(a_us=i * 1000, b_us=i * 1000 + 50, pair=i) for i in range(3)
        ]
        with pytest.raises(RuntimeError):
            campaign.run_sparse(1000, 1875000, 1024, True, 0)
    assert stops and all(stop.is_set() for stop in stops)
    assert tx.stop.call_count == 2
    assert campaign.report['runs'][0]['status'] == 'failed'
