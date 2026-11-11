"""Command line entrypoint; recording does not import Qt or require a display server."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return result


def gain_index(value: str) -> int | None:
    if value.lower() == 'agc':
        return None
    result = int(value)
    if not 0 <= result <= 81:
        raise argparse.ArgumentTypeError('gain must be agc or an index from 0 to 81')
    return result


def record(argv: list[str] | None = None) -> int:
    """Record finite detector summaries, or every raw burst, until stopped or limited."""
    from .acquisition import DETECTOR_MODES, AcquisitionWorker

    parser = argparse.ArgumentParser(
        prog='esp32-sdr record',
        description='Headless burst recording. No flashing, no continuous RF coverage claim. '
        'SIGINT/SIGTERM stops after the current bounded acquisition and recording.',
    )
    parser.add_argument('--port', help='Explicit serial device (required unless --demo)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('raw', *DETECTOR_MODES), default='DETPIPE1')
    parser.add_argument(
        '--frequency-mhz', type=int, choices=range(2400, 2501), default=2440, metavar='2400..2500'
    )
    parser.add_argument(
        '--rate-hz', type=int, choices=(16_000_000, 40_000_000, 80_000_000), default=16_000_000
    )
    parser.add_argument('--bandwidth-mhz', type=int, choices=range(68), default=0, metavar='0..67')
    parser.add_argument('--gain', type=gain_index, default=None, metavar='agc|0..81')
    parser.add_argument(
        '--samples', type=int, choices=range(256, 16381), default=16380, metavar='256..16380'
    )
    parser.add_argument('--bits', type=int, choices=(8, 10), default=10)
    parser.add_argument(
        '--run-ms', type=int, choices=range(1, 5001), default=1000, metavar='1..5000'
    )
    parser.add_argument(
        '--ratio-milli',
        type=int,
        choices=range(1000, 1000001),
        default=4000,
        metavar='1000..1000000',
    )
    parser.add_argument(
        '--candidate-count',
        type=int,
        choices=(1, 3),
        default=1,
        help='Opt in to three candidate crops (DETPIPE1 with PIPEKEEP only)',
    )
    parser.add_argument('--runs', type=positive_int, help='Maximum finite runs or raw bursts')
    parser.add_argument(
        '--duration-s',
        type=positive_int,
        help='Stop starting new runs after this elapsed time; in-flight run finishes',
    )
    parser.add_argument(
        '--demo', action='store_true', help='Synthetic raw IQ only; never opens serial'
    )
    args = parser.parse_args(argv)
    if not args.demo and not args.port:
        parser.error('--port is required unless --demo is selected')
    if args.demo and args.mode != 'raw':
        parser.error('--demo requires --mode raw; detector performance is not simulated')
    if args.candidate_count != 1 and args.mode != 'DETPIPE1':
        parser.error('--candidate-count 3 requires --mode DETPIPE1')
    if args.mode in DETECTOR_MODES and args.bits != 10:
        parser.error('detector modes require --bits 10')
    if args.mode in DETECTOR_MODES and args.gain is None:
        print(
            'WARNING: hardware AGC changes gain; detector energies and candidate rates are not '
            'comparable across gain steps. Use fixed manual gain for comparisons.',
            file=sys.stderr,
        )
    settings = dict(
        candidate_count=args.candidate_count,
        mode=args.mode,
        det_ms=args.run_ms,
        ratio_milli=args.ratio_milli,
        frequency_mhz=args.frequency_mhz,
        rate_hz=args.rate_hz,
        bandwidth_mhz=args.bandwidth_mhz,
        gain=args.gain,
        bits=args.bits,
        samples=args.samples,
        threshold_db=10,
        autosave=True,
        record_all=True,
        scan=False,
        max_runs=args.runs,
        duration_s=args.duration_s,
    )
    worker = AcquisitionWorker(
        'SIMULATED' if args.demo else args.port, settings, args.output, demo=args.demo
    )
    previous = {}

    def stop(signum: int, frame: object) -> None:
        worker.stop()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
        worker.start()
        while worker.isRunning():
            worker.wait(100)
            _print_notices(worker)
        _print_notices(worker)
    finally:
        if worker.isRunning():
            worker.stop()
        if worker.ident is not None:
            worker.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(
        json.dumps(
            {
                'runs': worker.run_count,
                'captures': worker.capture_count,
                'output': str(args.output),
                'synthetic': args.demo,
                'stopped': worker.stop_requested.is_set(),
                'ok': worker.error is None,
            }
        )
    )
    return 1 if worker.error is not None else 0


def _print_notices(worker: object) -> None:
    import queue

    while True:
        try:
            kind, value = worker.notices.get_nowait()
        except queue.Empty:
            return
        if kind in ('error', 'state', 'record'):
            print(json.dumps({'kind': kind, 'message': value}), flush=True)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == 'record':
        return record(args[1:])
    from .gui import main as gui_main

    return gui_main(args)


if __name__ == '__main__':
    raise SystemExit(main())
