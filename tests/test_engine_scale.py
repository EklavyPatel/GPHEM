"""Engine tests runnable without Flask, Excel, or solver dependencies."""
from copy import deepcopy
import pytest
from engine import Exam,Plan,Conflict,Preset


def config(count, rules=None):
    # Irregular room shapes and blocked/reserved positions represented as blocked rules.
    rooms=[]
    left=count+20
    i=1
    while left>0:
        rows=min(20,max(1,(left+9)//10))
        rooms.append({'id':f'R{i:03}','rows':rows,'columns':10,'seats_per_bench':1})
        left-=rows*10;i+=1
    return {'version':1,'seed':42,'rooms':rooms,
            'students':[{'sid':f'{i:06}','branch':'ICT' if i%5 else 'ECE','batch':str(i%3)} for i in range(count)],
            'rules':rules or [{'id':'shuffle','type':'order','mode':'random'}]}


@pytest.mark.parametrize('count',[10,100,1000,5000])
def test_complete_verified_deterministic_datasets(count):
    data=config(count)
    data['rules'].append({'id':'broken','type':'blocked','scope':{'room':'R001','row':1,'column':1,'position':1}})
    plan=Plan(Exam.model_validate(data));preview=plan.allocate()
    assignment={p['seat_id']:p['sid'] for p in preview['positions']}
    plan.verify(assignment)
    assert len([v for v in assignment.values() if v])==count
    assert assignment['R001/1/1/1'] is None
    data['students'].reverse()
    repeat=Plan(Exam.model_validate(data)).allocate()
    assert repeat['positions']==preview['positions']


def test_duplicate_and_insufficient_capacity():
    data=config(10);data['students'].append(deepcopy(data['students'][0]))
    with pytest.raises(Conflict,match='Duplicate'):Plan(Exam.model_validate(data))
    data=config(10);data['rooms']=[{'id':'R001','rows':1,'columns':1}]
    with pytest.raises(Conflict,match='Insufficient'):Plan(Exam.model_validate(data))


def test_overlapping_orders_fail():
    data=config(10,[{'id':'a','type':'order','mode':'ascending_sid'},
                    {'id':'b','type':'order','mode':'descending_sid'}])
    with pytest.raises(Conflict,match='Ambiguous'):Plan(Exam.model_validate(data))


def test_impossible_branch_restriction():
    data=config(10,[{'id':'restrict','type':'allow','values':['Unknown']}])
    with pytest.raises(Conflict,match='Insufficient'):Plan(Exam.model_validate(data))


def test_bijection_verifier_rejects_duplicate_assignment():
    plan=Plan(Exam.model_validate(config(10)))
    result=plan.allocate()
    assignment={p['seat_id']:p['sid'] for p in result['positions']}
    keys=[k for k,v in assignment.items() if v]
    assignment[keys[1]]=assignment[keys[0]]
    with pytest.raises(Conflict,match='Duplicate'):plan.verify(assignment)


def test_unknown_policy_never_accepted():
    with pytest.raises(ValueError):Preset.model_validate({'version':1,'rules':[{'id':'x','type':'magic'}]})
