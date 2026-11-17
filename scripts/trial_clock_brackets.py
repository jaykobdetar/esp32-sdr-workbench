"""Prospective trial-local clock policy. No residual-selected anchor exclusions."""

from __future__ import annotations

import hashlib
import json
import math

POLICY = 'trial-batches-v1'
MIN_GROUPS = 8
MAX_BOUNDARY_AGE_US = 60_000_000


def batch_spec(trial_index, role):
    if type(trial_index) is not int or trial_index < 0 or role not in ('before', 'after'):
        raise ValueError('Invalid trial calibration batch')
    return dict(batch_id=f'trial-{trial_index:04d}-{role}', trial_index=trial_index, role=role)


def trial_spec(trial_index):
    return dict(
        policy=POLICY,
        trial_index=trial_index,
        before_batch_id=batch_spec(trial_index, 'before')['batch_id'],
        after_batch_id=batch_spec(trial_index, 'after')['batch_id'],
        minimum_groups_per_side=MIN_GROUPS,
        maximum_boundary_age_us=MAX_BOUNDARY_AGE_US,
    )


def anchor_seal(anchors):
    """Canonical exact inventory seal, including group identities and both clocks."""
    fields = (
        'batch_id',
        'trial_index',
        'role',
        'receiver_index',
        'pair',
        'sequence',
        'a_us',
        'b_us',
    )
    inventory = [{key: a[key] for key in fields} for a in anchors]
    inventory.sort(key=lambda a: (a['receiver_index'], a['pair'], a['sequence']))
    encoded = json.dumps(inventory, sort_keys=True, separators=(',', ':'), allow_nan=False).encode(
        'utf-8'
    )
    return dict(anchor_count=len(inventory), anchor_sha256=hashlib.sha256(encoded).hexdigest())


def select_trial_anchors(row, anchors):
    """Select by assigned batches only; reject malformed or stale assigned evidence.

    Future/unrelated batches never participate. All anchors in either assigned
    batch must be well-formed and retained; bad fits cannot prune a group.
    """
    spec = row['clock_brackets']
    if spec != trial_spec(row['index']):
        raise ValueError('Malformed or changed trial bracket policy')
    receipts = row['clock_bracket_batches']
    if not isinstance(receipts, list) or len(receipts) != 2:
        raise ValueError('Both complete calibration batch receipts required')
    receipt_pairs = {}
    for role, receipt in zip(('before', 'after'), receipts, strict=True):
        if not isinstance(receipt, dict):
            raise ValueError('Malformed batch receipt')
        expected = batch_spec(row['index'], role)
        if (
            any(receipt.get(k) != v for k, v in expected.items())
            or receipt.get('status') != 'complete'
        ):
            raise ValueError('Incomplete or mismatched calibration batch receipt')
        pairs = receipt.get('pair_ids')
        if (
            not isinstance(pairs, list)
            or any(type(p) is not int or p < 0 for p in pairs)
            or len(set(pairs)) != len(pairs)
        ):
            raise ValueError('Invalid batch capture group inventory')
        receipt_pairs[role] = set(pairs)
    if receipt_pairs['before'] & receipt_pairs['after']:
        raise ValueError('Capture group reused across calibration batches')
    count = len(row['receivers'])
    start = row['scheduled_a_us']
    end = start + row['duration_ms'] * 1000
    if not all(math.isfinite(t) for t in (start, end)) or end <= start:
        raise ValueError('Invalid requested observation window')
    ids = {spec[f'{role}_batch_id']: role for role in ('before', 'after')}
    selected, pair_roles, keys = [], {}, set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            raise ValueError('Malformed anchor record')
        batch_id = anchor.get('batch_id')
        if batch_id not in ids:
            if anchor.get('pair') in receipt_pairs['before'] | receipt_pairs['after']:
                raise ValueError('Assigned capture group has missing or incorrect batch tag')
            continue
        role = ids[batch_id]
        if anchor.get('trial_index') != row['index'] or anchor.get('role') != role:
            raise ValueError('Assigned anchor batch metadata mismatch')
        k, pair, seq = (anchor.get(key) for key in ('receiver_index', 'pair', 'sequence'))
        if (
            any(type(v) is not int for v in (k, pair, seq))
            or not 1 <= k < count
            or pair < 0
            or seq < 0
        ):
            raise ValueError('Invalid assigned anchor identity')
        if pair not in receipt_pairs[role]:
            raise ValueError('Assigned anchor absent from batch group inventory')
        if pair in pair_roles and pair_roles[pair] != role:
            raise ValueError('Capture group reused across before/after batches')
        pair_roles[pair] = role
        key = (k, pair, seq)
        if key in keys:
            raise ValueError('Duplicate assigned anchor')
        keys.add(key)
        a, b = anchor['a_us'], anchor['b_us']
        if any(
            isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t)
            for t in (a, b)
        ):
            raise ValueError('Invalid assigned anchor clock')
        age = start - a if role == 'before' else a - end
        if not 0 < age <= MAX_BOUNDARY_AGE_US:
            raise ValueError('Assigned anchor is not within its 60-second boundary bracket')
        selected.append(anchor)
    for role, receipt in zip(('before', 'after'), receipts, strict=True):
        seal = anchor_seal([a for a in selected if a['role'] == role])
        if any(receipt.get(key) != value for key, value in seal.items()):
            raise ValueError('Completed calibration batch anchor inventory seal mismatch')
    diagnostics = []
    for k in range(1, count):
        own = [a for a in selected if a['receiver_index'] == k]
        record = dict(receiver_index=k)
        for role in ('before', 'after'):
            side = [a for a in own if a['role'] == role]
            groups = sorted({a['pair'] for a in side})
            if len(groups) < MIN_GROUPS:
                raise ValueError('Eight independent shared capture groups required on each side')
            record[f'{role}_pair_ids'] = groups
            record[f'{role}_anchor_count'] = len(side)
            ages = [start - a['a_us'] if role == 'before' else a['a_us'] - end for a in side]
            record[f'{role}_boundary_age_range_us'] = [min(ages), max(ages)]
        diagnostics.append(record)
    return selected, dict(spec, receiver_brackets=diagnostics, assigned_anchor_count=len(selected))
