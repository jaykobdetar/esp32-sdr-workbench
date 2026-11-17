import gc

import pytest

from sdr_research.gc_policy import deferred_cyclic_gc


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('failure', [True, False])
def test_restores_exact_state_after_scope(monkeypatch, enabled, failure):
    original = gc.isenabled()
    collected = []
    monkeypatch.setattr(gc, 'collect', lambda: collected.append(gc.isenabled()) or 0)
    observation = {}
    error = RuntimeError('primary')
    try:
        gc.enable() if enabled else gc.disable()

        def work():
            with deferred_cyclic_gc(observation):
                assert collected == [enabled]
                assert not gc.isenabled()
                if failure:
                    raise error

        if failure:
            with pytest.raises(RuntimeError) as caught:
                work()
            assert caught.value is error
        else:
            work()
        assert gc.isenabled() == enabled
        assert observation['restored_enabled'] == enabled
        assert (
            observation['collect_finished_ns']
            <= observation['run_started_ns']
            <= observation['run_finished_ns']
            <= observation['restored_ns']
        )
    finally:
        gc.enable() if original else gc.disable()


def test_nested_context_refused_without_early_restore(monkeypatch):
    monkeypatch.setattr(gc, 'collect', lambda: 0)
    with deferred_cyclic_gc({}):
        with pytest.raises(RuntimeError, match='already active'):
            with deferred_cyclic_gc({}):
                pass
        assert not gc.isenabled()


def test_bookkeeping_failure_never_masks_primary_or_leaks_lock(monkeypatch):
    class BrokenObservation(dict):
        def update(self, *args, **kwargs):
            raise MemoryError('telemetry unavailable')

    monkeypatch.setattr(gc, 'collect', lambda: 0)
    original = gc.isenabled()
    error = RuntimeError('primary')
    with pytest.raises(RuntimeError) as caught:
        with deferred_cyclic_gc(BrokenObservation()):
            raise error
    assert caught.value is error and gc.isenabled() == original
    with deferred_cyclic_gc({}):
        assert not gc.isenabled()
