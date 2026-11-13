"""Verify published known-test packet bytes and per-run diversity counts offline.

This rechecks payload structure and the published over-air CRC. Raw I/Q is
private, so this does not independently repeat demodulation or measure recall.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__:
    from .verify_nrf_evidence import verify_packet
else:
    from verify_nrf_evidence import verify_packet


def verify(document: dict) -> dict:
    if document.get('schema') != 'sparse-known-packet-evidence-v1':
        raise ValueError('Unsupported packet evidence schema')
    ids = set()
    counts = []
    for run in document['runs']:
        run_id = run['run_id']
        if not isinstance(run_id, str) or not run_id or run_id in ids:
            raise ValueError('Each transmitter run needs a unique identity')
        ids.add(run_id)
        if type(run['source_on']) is not bool:
            raise ValueError('Invalid source state')
        recordings = run['recording_counts']
        if len(recordings) != 2 or any(type(n) is not int or n < 0 for n in recordings):
            raise ValueError('Invalid recording counts')
        sets = [set(), set()]
        seen_recordings = set()
        for record in run['recordings']:
            receiver, generation = record['receiver'], record['generation']
            if type(receiver) is not int or receiver not in (0, 1):
                raise ValueError('Invalid receiver')
            if type(generation) is not int or generation < 1:
                raise ValueError('Invalid capture generation')
            identity = (receiver, generation)
            if identity in seen_recordings:
                raise ValueError('Duplicate recording identity')
            seen_recordings.add(identity)
            for packet in record['packets']:
                verify_packet(packet)
                sets[receiver].add((packet['sequence'], packet['observed_payload_hex']))
        if [sum(k == side for k, _ in seen_recordings) for side in (0, 1)] != recordings:
            raise ValueError('Recording accounting mismatch')
        computed = dict(
            per_receiver_unique=[len(s) for s in sets],
            unique_union=len(sets[0] | sets[1]),
            shared=len(sets[0] & sets[1]),
        )
        if computed != run['counts']:
            raise ValueError('Published packet counts disagree with bytes')
        counts.append(dict(run_id=run_id, source_on=run['source_on'], **computed))
    if not counts:
        raise ValueError('No packet runs')
    return dict(runs=counts, note=__doc__.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.evidence.read_text())), indent=2))


if __name__ == '__main__':
    main()
