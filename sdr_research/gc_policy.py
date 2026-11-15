"""Opt-in bounded coordinator GC experiment, not a transport/firmware fix."""

import gc
import time
from contextlib import contextmanager
from threading import Lock

_ACTIVE = Lock()


def peak_rss():
    try:
        import resource

        return dict(
            value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            units='KiB on Linux; bytes on macOS',
        )
    except (ImportError, OSError):
        return dict(status='unavailable')


@contextmanager
def deferred_cyclic_gc(observation):
    """Call only around coordinator that joins ALL submitted workers on exit.

    GC is process-global; concurrent/nested policy contexts are refused. Other
    application code must not independently change GC policy during this scope.
    """
    if not _ACTIVE.acquire(blocking=False):
        raise RuntimeError('Cyclic GC deferral already active')
    enabled = gc.isenabled()

    def record(values):
        # Instrumentation must never bypass restoration or mask a primary
        # exception, including allocation failure while building telemetry.
        try:
            observation.update(values())
        except BaseException:
            pass

    try:
        record(
            lambda: dict(
                original_enabled=enabled,
                collect_started_ns=time.monotonic_ns(),
                peak_rss_before=peak_rss(),
            )
        )
        collected = gc.collect()
        record(lambda: dict(collected_objects=collected, collect_finished_ns=time.monotonic_ns()))
        gc.disable()
        record(lambda: dict(run_started_ns=time.monotonic_ns(), entry_enabled=gc.isenabled()))
        yield
    finally:
        # No report operation precedes restoration. Lock release is guaranteed
        # even if a GC policy API unexpectedly raises; bookkeeping comes last.
        try:
            try:
                if enabled:
                    gc.enable()
                else:
                    gc.disable()
            finally:
                _ACTIVE.release()
        finally:
            record(
                lambda: dict(
                    run_finished_ns=time.monotonic_ns(),
                    restored_enabled=gc.isenabled(),
                    restored_ns=time.monotonic_ns(),
                    peak_rss_after=peak_rss(),
                )
            )
