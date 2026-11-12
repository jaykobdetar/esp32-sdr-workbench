"""Failure and publication races must not turn failed saves into recordings."""

from pathlib import Path

import numpy as np
import pytest

from sdr_research import recording
from sdr_research.protocol import Capture


@pytest.fixture
def capture():
    return Capture(
        np.array([0.25 + 0.5j, -0.75j], dtype=np.complex64),
        16000000,
        2440000000,
        '2026-11-12T00:00:00Z',
        1,
        2,
        1,
    )


def assert_retry(capture, base):
    restored = recording.load_capture(recording.save_capture(capture, base))
    np.testing.assert_array_equal(restored.iq, capture.iq)
    assert sorted(p.name for p in base.parent.iterdir()) == [
        base.name + '.sigmf-data',
        base.name + '.sigmf-meta',
    ]


@pytest.mark.parametrize('failure', ['conversion', 'payload', 'metadata', 'data_sync', 'meta_sync'])
def test_failed_staging_cleans_all_files_and_allows_retry(tmp_path, capture, monkeypatch, failure):
    base = tmp_path / 'capture'
    with monkeypatch.context() as patch:
        if failure in ('conversion', 'payload'):

            class BrokenArray:
                def tofile(self, output):
                    output.write(b'partial payload')
                    output.flush()
                    raise OSError('injected payload failure')

            def broken_array(*args, **kwargs):
                if failure == 'conversion':
                    raise ValueError('injected conversion failure')
                return BrokenArray()

            patch.setattr(recording.np, 'asarray', broken_array)
        elif failure == 'metadata':

            def broken_dump(doc, output, **kwargs):
                output.write('{"global": ')
                output.flush()
                raise OSError('injected metadata failure')

            patch.setattr(recording.json, 'dump', broken_dump)
        else:
            calls = 0
            original_sync = recording.os.fsync

            def broken_sync(fd):
                nonlocal calls
                calls += 1
                if calls == (1 if failure == 'data_sync' else 2):
                    raise OSError('injected sync failure')
                original_sync(fd)

            patch.setattr(recording.os, 'fsync', broken_sync)
        with pytest.raises((OSError, ValueError), match='injected'):
            recording.save_capture(capture, base)
    assert list(tmp_path.iterdir()) == []
    assert_retry(capture, base)


@pytest.mark.parametrize('suffix', ['.sigmf-data', '.sigmf-meta'])
@pytest.mark.parametrize('kind', ['file', 'dangling_symlink'])
def test_existing_destination_is_never_replaced(tmp_path, capture, suffix, kind):
    existing = tmp_path / ('capture' + suffix)
    if kind == 'file':
        existing.write_bytes(b'original')
    else:
        existing.symlink_to('missing-target')
    with pytest.raises(FileExistsError):
        recording.save_capture(capture, tmp_path / 'capture')
    assert list(tmp_path.iterdir()) == [existing]
    if kind == 'file':
        assert existing.read_bytes() == b'original'
    else:
        assert existing.is_symlink()
        assert existing.readlink() == Path('missing-target')


@pytest.mark.parametrize('suffix', ['.sigmf-data', '.sigmf-meta'])
def test_racing_destination_is_preserved(tmp_path, capture, monkeypatch, suffix):
    original_link = recording.os.link
    conflict = tmp_path / ('capture' + suffix)

    def racing_link(source, destination):
        if destination == conflict:
            conflict.write_bytes(b'concurrent writer')
        original_link(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(recording.os, 'link', racing_link)
        with pytest.raises(FileExistsError):
            recording.save_capture(capture, tmp_path / 'capture')
    assert list(tmp_path.iterdir()) == [conflict]
    assert conflict.read_bytes() == b'concurrent writer'
    conflict.unlink()
    assert_retry(capture, tmp_path / 'capture')


@pytest.mark.parametrize('failed_link', [1, 2])
def test_publication_failure_cleans_owned_files(tmp_path, capture, monkeypatch, failed_link):
    original_link = recording.os.link
    calls = 0

    def failing_link(source, destination):
        nonlocal calls
        calls += 1
        if calls == failed_link:
            raise OSError('injected publication failure')
        original_link(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(recording.os, 'link', failing_link)
        with pytest.raises(OSError, match='injected'):
            recording.save_capture(capture, tmp_path / 'capture')
    assert list(tmp_path.iterdir()) == []
    assert_retry(capture, tmp_path / 'capture')


def test_rollback_preserves_replaced_data(tmp_path, capture, monkeypatch):
    original_link = recording.os.link
    data = tmp_path / 'capture.sigmf-data'

    def replacing_link(source, destination):
        if destination.suffix == '.sigmf-meta':
            data.unlink()
            data.write_bytes(b'replacement by another writer')
            raise OSError('injected metadata publication failure')
        original_link(source, destination)

    monkeypatch.setattr(recording.os, 'link', replacing_link)
    with pytest.raises(OSError, match='injected'):
        recording.save_capture(capture, tmp_path / 'capture')
    assert list(tmp_path.iterdir()) == [data]
    assert data.read_bytes() == b'replacement by another writer'


def test_publication_only_exposes_complete_files(tmp_path, capture, monkeypatch):
    original_link = recording.os.link
    base = tmp_path / 'capture'
    data = tmp_path / 'capture.sigmf-data'
    meta = tmp_path / 'capture.sigmf-meta'

    def checking_link(source, destination):
        if destination == data:
            assert not meta.exists()
            np.testing.assert_array_equal(np.fromfile(source, dtype='<c8'), capture.iq)
        else:
            assert data.exists()
            assert not meta.exists()
            assert recording.json.loads(Path(source).read_text())['captures']
        original_link(source, destination)

    monkeypatch.setattr(recording.os, 'link', checking_link)
    assert_retry(capture, base)


def test_concurrent_saves_publish_exactly_one_complete_pair(tmp_path, capture, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Barrier

    original_link = recording.os.link
    ready = Barrier(2)
    data = tmp_path / 'capture.sigmf-data'
    base = tmp_path / 'capture'

    def synchronized_link(source, destination):
        if destination == data:
            ready.wait(timeout=5)
        original_link(source, destination)

    def save(value):
        candidate = replace(capture, iq=capture.iq * value, metadata={'writer': value})
        try:
            recording.save_capture(candidate, base)
        except FileExistsError:
            return None
        return value

    monkeypatch.setattr(recording.os, 'link', synchronized_link)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, [1, 2]))
    winners = [value for value in results if value is not None]
    assert len(winners) == 1
    restored = recording.load_capture(tmp_path / 'capture.sigmf-meta')
    assert restored.metadata == {'writer': winners[0]}
    np.testing.assert_array_equal(restored.iq, capture.iq * winners[0])
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        'capture.sigmf-data',
        'capture.sigmf-meta',
    ]
