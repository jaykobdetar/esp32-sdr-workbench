import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host.source_trace import read_trace


def chunk(rows, offset=0, count=None):
    count = len(rows) if count is None else count
    return dict(ok=True, trace_schema=1, run_id=1, enabled=True, capacity=4096,
                count=count, ended=count, aborted=0, overflow=False, complete=True,
                attempted=count, completed=count, offset=offset, next=offset+len(rows), records=rows)


def test_full_trace():
    rows = [[i, i*2, 2440, i*100, i*100+50, 1] for i in range(4096)]
    calls=[]
    def command(s):
        calls.append(s);offset=int(s.split('=')[1])
        return chunk(rows[offset:offset+16], offset, len(rows))
    result=read_trace(command)
    assert result['records']==rows and len(calls)==256


@pytest.mark.parametrize('mutation', [
    {'complete':False}, {'overflow':True}, {'count':4097}, {'next':7},
    {'records':[[0,0,2490,0,1,1]]}, {'records':[[1,2,2440,0,1,1]]},
    {'records':[[0,0,2440,0,0,0]]}, {'ended':0}, {'completed':0},
])
def test_reject(mutation):
    c=chunk([[0,3,2440,1,2,1]]);c.update(mutation)
    with pytest.raises(ValueError):read_trace(lambda _:copy.deepcopy(c))


def test_abort_and_empty():
    c=chunk([[0,8,2402,10,0,2]]);c.update(ended=0,aborted=1,completed=0)
    assert read_trace(lambda _:c)['aborted']==1
    assert read_trace(lambda _:chunk([]))['records']==[]


def test_changed_run():
    first=chunk([[i,i,2440,i*100,i*100+50,1] for i in range(16)],0,17)
    second=chunk([[16,16,2440,1600,1650,1]],16,17);second['run_id']=2
    replies=iter([first,second])
    with pytest.raises(ValueError):read_trace(lambda _:next(replies))


@pytest.mark.parametrize('field', [
    'trace_schema', 'run_id', 'capacity', 'count', 'attempted', 'completed',
    'ended', 'aborted', 'offset', 'next',
])
@pytest.mark.parametrize('bad', [None, True, '1', 1.0, -1, 0x100000000])
def test_required_integer_metadata(field, bad):
    c=chunk([[0,0,2440,10,20,1]])
    if bad is None:
        del c[field]
    else:
        c[field]=bad
    with pytest.raises(ValueError):read_trace(lambda _:c)


@pytest.mark.parametrize('rows', [
    [[0,0,2440,100,150,1], [1,1,2440,90,200,1]],  # backward TXEN
    [[0,0,2440,100,150,1], [1,1,2440,100,200,1]],  # duplicate TXEN
    [[0,0,2440,100,150,1], [1,1,2440,120,200,1]],  # overlap
    [[0,0,2440,100,0,2], [1,1,2440,200,250,1]],  # resumed after abort
    [[0,0,2440,100,0,2], [1,1,2440,200,0,2]],  # multiple aborts
])
def test_impossible_record_order(rows):
    c=chunk(rows)
    c['ended']=c['completed']=sum(row[5]==1 for row in rows)
    c['aborted']=len(rows)-c['ended']
    with pytest.raises(ValueError):read_trace(lambda _:c)


def test_order_checked_across_chunks():
    first=chunk([[i,i,2440,i*100,i*100+50,1] for i in range(16)],0,17)
    second=chunk([[16,16,2440,1549,1650,1]],16,17)
    replies=iter([first,second])
    with pytest.raises(ValueError):read_trace(lambda _:next(replies))


def test_touching_end_and_launch_and_final_abort():
    c=chunk([[0,0,2440,100,150,1], [1,3,2480,150,0,2]])
    c.update(ended=1,completed=1,aborted=1,run_id=0xffffffff)
    assert read_trace(lambda _:c)['records']==c['records']


def test_wrapped_run_id_zero_is_valid():
    c=chunk([]);c['run_id']=0
    assert read_trace(lambda _:c)['run_id']==0


@pytest.mark.parametrize('value', [None, [], True, 'bad'])
def test_nonobject_response(value):
    with pytest.raises(ValueError):read_trace(lambda _:value)
