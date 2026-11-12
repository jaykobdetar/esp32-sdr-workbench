"""Qt-free presentation rules for RF Studio. No hardware I/O."""

from __future__ import annotations

import json
from pathlib import Path

TASKS = {
    'listen': ('Listen', 'See the radio activity around you. No transmission is requested.'),
    'test': ('Test a signal', 'Send a short, known test signal and watch the receivers respond.'),
    'compare': (
        'Compare receivers',
        'Watch two or more receivers on the same frequency. No transmission.',
    ),
}


def readiness(task: str, receivers: int, transmitters: int, demo: bool) -> str | None:
    if receivers < 1:
        return 'Choose at least one receiver to continue.'
    if task == 'compare' and receivers < 2:
        return 'Compare needs at least two receivers. Choose Listen for one receiver.'
    if task == 'test' and (demo or transmitters < 1):
        return 'Choose a physical transmitter, or switch to Listen.'
    return None


def describe_result(manifest: dict) -> tuple[str, str]:
    """Summarize even damaged/incomplete history without implying radio safety.

    A STOP is confirmed only by the literal JSON boolean false for every
    requested transmitter. Counts never include unrelated result entries.
    """
    if not isinstance(manifest, dict):
        return 'Session needs attention', 'Invalid session summary.'
    malformed = False

    def mapping(value):
        nonlocal malformed
        if not isinstance(value, dict):
            malformed = True
            return {}
        return value

    def sequence(value):
        nonlocal malformed
        if not isinstance(value, list):
            malformed = True
            return []
        return value

    state = manifest.get('status', 'unknown')
    errors = sequence(manifest.get('cleanup_errors', []))
    rx_errors = [
        r.get('error')
        for item in mapping(manifest.get('receiver_results', {})).values()
        if (r := mapping(item)).get('error')
    ]
    tx_value = manifest.get('transmitters', [])
    tx = sequence(tx_value)
    results = mapping(manifest.get('transmitter_results', {}))
    stopped = bool(tx)
    completed = 0
    counts_known = True
    labels = set()
    for item in tx:
        name = mapping(item).get('label')
        if not isinstance(name, str) or not name or name in labels:
            malformed = True
            stopped = False
            continue
        labels.add(name)
        stop = mapping(mapping(results.get(name, {})).get('stop', {}))
        stopped = stopped and stop.get('running') is False
        count = stop.get('completed')
        if type(count) is int and count >= 0:
            completed += count
        else:
            counts_known = False
    unconfirmed = bool(tx) and not stopped
    if manifest.get('error') or errors or rx_errors or state == 'error' or malformed or unconfirmed:
        title = 'Session needs attention'
    elif state == 'stopped':
        title = 'Session stopped'
    elif state == 'complete':
        title = 'Session complete'
    else:
        title = 'Session unfinished'
    if not isinstance(tx_value, list):
        message = 'Transmitter state is unknown: invalid session summary.'
    elif not tx:
        message = 'Receive-only session. No transmitter was requested.'
    elif stopped:
        message = 'Transmitter stop confirmed.'
        message += (
            f' {completed:,} transmissions completed.'
            if counts_known
            else ' Completed-transmission count unavailable.'
        )
    else:
        message = 'Transmitter stop is NOT confirmed. Check the device before continuing.'
    details = [manifest.get('error'), *errors, *rx_errors]
    if malformed:
        details.append('Some session fields are invalid or incomplete.')
    if any(details):
        message += '\n' + '\n'.join(str(x) for x in details if x)
    return title, message


def session_history(root: Path) -> list[tuple[Path, dict]]:
    """Read immediate session manifests, including incomplete/error sessions."""
    entries = []
    for path in sorted(root.glob('*/session.json'), reverse=True)[:200]:
        try:
            if path.stat().st_size > 2_000_000:
                continue
            doc = json.loads(path.read_text())
            if isinstance(doc, dict):
                entries.append((path.parent, doc))
        except (OSError, ValueError):
            continue
    return entries
