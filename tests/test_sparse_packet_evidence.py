from copy import deepcopy

import pytest

from scripts.verify_nrf_evidence import known_payload, radio_crc
from scripts.verify_sparse_packet_evidence import verify


def evidence():
    data = known_payload(7, 16).hex()
    crc = radio_crc(bytes.fromhex('efcdab89c3') + bytes([16]) + bytes.fromhex(data))
    packet = dict(
        sequence=7,
        length=16,
        observed_payload_hex=data,
        expected_payload_hex=data,
        address_hex='efcdab89c3',
        crc_computed=crc,
        crc_received_msb_first=crc,
        full_known_payload_match=True,
        address_verified=True,
        crc_verified=True,
    )
    run = dict(
        run_id='one',
        source_on=True,
        recording_counts=[1, 1],
        recordings=[
            dict(receiver=0, generation=1, packets=[packet]),
            dict(receiver=1, generation=2, packets=[packet]),
        ],
        counts=dict(per_receiver_unique=[1, 1], unique_union=1, shared=1),
    )
    return dict(schema='sparse-known-packet-evidence-v1', runs=[run])


def test_independent_crc_and_per_start_union():
    document = evidence()
    assert verify(document)['runs'][0]['unique_union'] == 1
    second = deepcopy(document['runs'][0])
    second['run_id'] = 'two'
    document['runs'].append(second)
    assert len(verify(document)['runs']) == 2


@pytest.mark.parametrize(
    'fault',
    ['crc', 'payload', 'count', 'duplicate_run', 'duplicate_record', 'receiver', 'generation'],
)
def test_tampered_packet_proof_fails(fault):
    document = evidence()
    run = document['runs'][0]
    packet = run['recordings'][0]['packets'][0]
    if fault == 'crc':
        packet['crc_received_msb_first'] = '0000'
    elif fault == 'payload':
        packet['observed_payload_hex'] = '00' * 16
    elif fault == 'count':
        run['counts']['unique_union'] = 2
    elif fault == 'duplicate_run':
        document['runs'].append(deepcopy(run))
    elif fault == 'duplicate_record':
        run['recordings'].append(deepcopy(run['recordings'][0]))
    elif fault == 'receiver':
        run['recordings'][0]['receiver'] = 2
    else:
        run['recordings'][0]['generation'] = 0
    with pytest.raises(ValueError):
        verify(document)
