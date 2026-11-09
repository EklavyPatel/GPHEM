from copy import deepcopy
from collections import defaultdict
import pytest
from services.gtu_engine import DEFAULT_CONFIG,allocate,verify,validate_config,room_sequence


def config(sizes,subjects=None):
    students=[]
    for index,size in enumerate(sizes):
        for sid in range(size):
            students.append({'sid':f'{index:03}{sid:03}','block_no':f'{index:03}',
                             'subject_code':subjects[index] if subjects else f'S{index}',
                             'subject_name':f'Subject {subjects[index] if subjects else index}'})
    return {'mode':'gtu','settings':deepcopy(DEFAULT_CONFIG),'disabled_rooms':[],'students':students}


def counts(preview):
    by_room=defaultdict(list)
    for p in preview['positions']:
        if p['sid']:by_room[p['room']].append(p)
    return [len(people) for people in by_room.values()]


@pytest.mark.parametrize('sizes,expected',[
 ([30,30,20,10],[30,30,30]),([9,10,3],[22]),([3,3,3,3],[12]),
 ([3,3,3,3,3],[12,3]),([13,17],[30]),([13,18],[18,13]),([25,10,5],[30,10])])
def test_spec_examples(sizes,expected):
    data=config(sizes);result=allocate(data)
    assert counts(result)==expected
    assert verify(data,result)
    used=[]
    for p in result['positions']:
        if p['sid'] and p['room'] not in used:used.append(p['room'])
    assert used==['G'+r['number'] for r in room_sequence(DEFAULT_CONFIG)[:len(expected)]]


def test_same_subject_blocks_separate():
    data=config([13,10],['MATH','MATH'])
    assert counts(allocate(data))==[13,10]


def test_full_blocks_first_and_enrollment_sort():
    data=config([5,30,9]);data['students'].reverse()
    result=allocate(data)
    first=[p for p in result['positions'] if p['room']=='G721' and p['sid']]
    assert {p['block_no'] for p in first}=={'001'}
    assert [p['sid'] for p in first]==sorted(p['sid'] for p in first)
    assert result==allocate({**data,'students':list(reversed(data['students']))})


def test_maximum_capacity_and_shortfall():
    assert counts(allocate(config([30]*13)))==[30]*13
    with pytest.raises(ValueError,match='shortfall 1 seats'):allocate(config([30]*13+[1]))
    with pytest.raises(ValueError,match='maximum 30'):allocate(config([31]))


def test_room_count_shortfall_despite_spare_seats():
    with pytest.raises(ValueError,match='requires 14 rooms'):
        allocate(config([1]*14,['MATH']*14))


def test_unavailable_rooms_are_skipped_and_sessions_reuse_full_pool():
    data=config([30,1]);data['disabled_rooms']=['721','722','731']
    result=allocate(data)
    assert {p['room'] for p in result['positions'] if p['sid']}=={'G723','G724'}
    next_session=config([30])
    assert {p['room'] for p in allocate(next_session)['positions'] if p['sid']}=={'G721'}


def test_configurable_floor_order():
    data=config([1]);data['settings']['floors'][2]['order']=1;data['settings']['floors'][0]['order']=3
    assert next(p for p in allocate(data)['positions'] if p['sid'])['room']=='G761'


@pytest.mark.parametrize('change',[{'room_capacity':31},{'max_blocks_per_room':5},{'room_capacity':True},
 {'floors':[{'order':1,'name':'X','rooms':['721','721']}]},
 {'floors':[{'order':1,'name':'X','rooms':['../721']}]}])
def test_invalid_configuration(change):
    with pytest.raises(ValueError):validate_config({**DEFAULT_CONFIG,**change})


def test_ambiguous_block_and_duplicate_enrollment():
    data=config([2]);data['students'][1]['subject_code']='OTHER'
    with pytest.raises(ValueError,match='more than one subject'):allocate(data)
    data=config([2]);data['students'][1]['sid']=data['students'][0]['sid']
    with pytest.raises(ValueError,match='Duplicate enrollment'):allocate(data)


def test_independent_verifier_rejects_split_block_and_duplicate():
    data=config([20,20]);result=allocate(data)
    people=[p for p in result['positions'] if p['sid']]
    a,b=people[0],people[-1]
    for field in ('sid','block_no','subject_code','subject_name'):a[field],b[field]=b[field],a[field]
    with pytest.raises(ValueError,match='split'):verify(data,result)
    result=allocate(data);occupied=[p for p in result['positions'] if p['sid']]
    occupied[1]['sid']=occupied[0]['sid']
    with pytest.raises(ValueError,match='duplicate'):verify(data,result)


def test_verifier_rejects_nonconsecutive_block_order():
    data=config([3,2]);result=allocate(data)
    people=[p for p in result['positions'] if p['sid']]
    a,b=people[1],people[-1]
    for field in ('sid','block_no','subject_code','subject_name'):a[field],b[field]=b[field],a[field]
    with pytest.raises(ValueError,match='together'):verify(data,result)


def test_verifier_rejects_same_subject_merge():
    data=config([13,10],['MATH','MATH']);result=allocate(data)
    first_empty=[p for p in result['positions'] if p['room']=='G721' and not p['sid']]
    second=[p for p in result['positions'] if p['room']=='G722' and p['sid']]
    for empty,person in zip(first_empty,second):
        for field in ('sid','block_no','subject_code','subject_name'):
            empty[field],person[field]=person[field],empty[field]
    with pytest.raises(ValueError,match='same subject'):verify(data,result)


def test_verifier_rejects_skipping_available_room():
    data=config([3]);result=allocate(data)
    first=[p for p in result['positions'] if p['room']=='G721']
    second=[p for p in result['positions'] if p['room']=='G722']
    for left,right in zip(first,second):
        for field in ('sid','block_no','subject_code','subject_name'):left[field],right[field]=right[field],left[field]
    with pytest.raises(ValueError,match='continuously'):verify(data,result)


def test_whole_block_manual_reorder_and_room_swap():
    from services.gtu_engine import edit_blocks
    data=config([3,2]);original=allocate(data)
    result=edit_blocks(data,original,'move_block','000','G721')
    assert [p['block_no'] for p in result['positions'] if p['sid']][:2]==['001','001']
    assert verify(data,result)
    assert original!=result
    data=config([30,30]);original=allocate(data)
    swapped=edit_blocks(data,original,'swap_rooms','G721','G722')
    assert next(p for p in swapped['positions'] if p['sid'])['block_no']=='001'
    assert verify(data,swapped)


def test_manual_move_cannot_overfill_or_merge_same_subject_blocks():
    from services.gtu_engine import edit_blocks
    data=config([20,20]);original=allocate(data)
    with pytest.raises(ValueError,match='exceed'):
        edit_blocks(data,original,'move_block','001','G721')
    data=config([13,10],['MATH','MATH']);original=allocate(data)
    with pytest.raises(ValueError,match='same subject'):
        edit_blocks(data,original,'move_block','001','G721')
