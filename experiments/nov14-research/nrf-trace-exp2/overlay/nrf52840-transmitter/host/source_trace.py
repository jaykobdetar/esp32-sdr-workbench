"""Stopped-only bounded source evidence. Does not access hardware on import."""


def read_trace(command):
    records = []
    summary = None
    # Includes empty zero-record run; at most 256 chunks for a full trace.
    for _ in range(257):
        chunk = command(f'TRACE offset={len(records)}')
        if not isinstance(chunk, dict):
            raise ValueError('Trace response must be an object')
        # bool is an int subclass in Python, but not a protocol integer.
        integer_bounds = {
            'trace_schema': (1, 1), 'run_id': (0, 0xffffffff),
            'capacity': (4096, 4096), 'count': (0, 4096),
            'attempted': (0, 4096), 'completed': (0, 4096),
            'ended': (0, 4096), 'aborted': (0, 4096),
            'offset': (0, 4096), 'next': (0, 4096),
        }
        if any(type(chunk.get(key)) is not int or not low <= chunk[key] <= high
               for key, (low, high) in integer_bounds.items()):
            raise ValueError('Missing or invalid trace integer metadata')
        meta = {k: v for k, v in chunk.items() if k not in ('offset', 'next', 'records')}
        if summary is None:
            summary = meta
        if (meta != summary or chunk.get('ok') is not True
                or chunk.get('trace_schema') != 1 or chunk.get('enabled') is not True
                or chunk.get('overflow') is not False or chunk.get('complete') is not True
                or chunk.get('capacity') != 4096):
            raise ValueError('Incomplete or inconsistent source trace')
        rows = chunk.get('records')
        count = chunk.get('count')
        if (type(count) is not int or not 0 <= count <= 4096
                or not isinstance(rows, list) or len(rows) > 16
                or chunk.get('offset') != len(records)
                or chunk.get('next') != len(records) + len(rows)
                or len(records) + len(rows) > count):
            raise ValueError('Invalid trace chunk bounds')
        for row in rows:
            if (not isinstance(row, list) or len(row) != 6
                    or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in row)
                    or row[0] != len(records) or row[1] < row[0]
                    or (records and (row[1] <= records[-1][1]
                                     or row[3] <= records[-1][3]
                                     or row[3] < records[-1][4]
                                     or records[-1][5] == 2))
                    or not 2402 <= row[2] <= 2480 or row[5] not in (1, 2)
                    or (row[5] == 2 and row[4] != 0)
                    or (row[5] == 1 and row[4] < row[3])):
                raise ValueError('Invalid source trace record')
            records.append(row)
        if len(records) == count:
            ended = sum(r[5] == 1 for r in records)
            if (summary.get('attempted') != count or summary.get('completed') != ended
                    or summary.get('ended') != ended or summary.get('aborted') != count-ended):
                raise ValueError('Trace counters do not reconcile')
            return dict(summary, records=records)
        if not rows:
            raise ValueError('Trace retrieval made no progress')
    raise ValueError('Trace retrieval exceeded chunk bound')
