"""Manual room choice may cross floors; generation priorities stay automatic."""
from copy import deepcopy
from io import BytesIO
import json
import pytest
from openpyxl import load_workbook
from services.db import get_db
from services.gtu_engine import allocate,edit_blocks,verify
from services.allocation_service import revision,decoded,verify_revision
from .test_gtu_engine import config
from .test_pdf_workflow import upload_pdf,first_exam
from .pdf_fixtures import report_lines
from .conftest import post,action,exam_state,release_window


def room_for(preview,block):return {p['room'] for p in preview['positions'] if p['sid'] and p['block_no']==block}


@pytest.mark.parametrize('operation,source',[('move_block','000'),('swap_rooms','G721')])
def test_move_ground_floor_to_empty_second_floor_and_back(operation,source):
    data=config([3]);original=allocate(data)
    result=edit_blocks(data,original,operation,source,'G761')
    assert verify(data,result) and room_for(result,'000')=={'G761'}
    assert result['manual_room_selection'] is True
    assert room_for(original,'000')=={'G721'}
    restored=edit_blocks(data,result,operation,'000' if operation=='move_block' else 'G761','G721')
    assert room_for(restored,'000')=={'G721'} and verify(data,restored)
    # Generating afresh follows the automatic floor order again.
    assert room_for(allocate(data),'000')=={'G721'}


def test_manual_full_block_may_be_above_partial_block_but_is_still_exclusive():
    data=config([30,3]);original=allocate(data)
    assert room_for(original,'000')=={'G721'} and room_for(original,'001')=={'G722'}
    moved=edit_blocks(data,original,'move_block','000','G761')
    assert room_for(moved,'000')=={'G761'} and room_for(moved,'001')=={'G722'}
    assert verify(data,moved)
    with pytest.raises(ValueError,match='exceed'):
        edit_blocks(data,moved,'move_block','001','G761')


def test_cross_floor_block_and_room_swaps_with_occupied_second_floor():
    data=config([17,16]);original=allocate(data)
    second=edit_blocks(data,original,'move_block','001','G761')
    swapped=edit_blocks(data,second,'swap_blocks','000','001')
    assert room_for(swapped,'000')=={'G761'} and room_for(swapped,'001')=={'G721'}
    rooms=edit_blocks(data,swapped,'swap_rooms','G721','G761')
    assert room_for(rooms,'000')=={'G721'} and room_for(rooms,'001')=={'G761'}
    assert verify(data,rooms)


def test_manual_floor_choice_does_not_disable_capacity_subject_or_unavailable_room_checks():
    data=config([20,20]);original=allocate(data)
    moved=edit_blocks(data,original,'move_block','000','G761')
    with pytest.raises(ValueError,match='exceed'):
        edit_blocks(data,moved,'move_block','001','G761')
    data=config([13,10],['MATH','MATH']);original=allocate(data)
    moved=edit_blocks(data,original,'move_block','000','G761')
    with pytest.raises(ValueError,match='same subject'):
        edit_blocks(data,moved,'move_block','001','G761')
    data=config([3]);data['disabled_rooms']=['761'];original=allocate(data)
    with pytest.raises(ValueError,match='available'):
        edit_blocks(data,original,'move_block','000','G761')
    with pytest.raises(ValueError,match='available'):
        edit_blocks(data,original,'swap_rooms','G721','G761')
    with pytest.raises(ValueError,match='available'):
        edit_blocks(data,original,'move_block','000','G999')


def test_second_floor_approved_draft_publish_and_reports_with_fixed_emergency(app,admin):
    location=upload_pdf(admin,lines=report_lines(sizes=(30,3)))
    assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id'];release_window(app,eid)
    assert action(admin,app,eid,'approve').status_code==302
    original=exam_state(app,eid)
    response=action(admin,app,eid,'emergency-seat',base_revision=original['draft_id'],confirmed='yes',sid='000009000001',target='G762/17')
    assert response.status_code==302
    before=exam_state(app,eid)
    moved=action(admin,app,eid,'edit',view='arrangement',base_revision=before['draft_id'],operation='move_block',source='1',target='G761')
    assert moved.status_code==302,moved.data
    state=exam_state(app,eid)
    assert state['published_id']==before['published_id'] and state['approved_id']==before['approved_id']
    with app.app_context():
        data=decoded(revision(state['draft_id'],eid));verify_revision(data['config'],data['preview'])
        assert room_for(data['preview'],'1')=={'G761'}
        assert next(p for p in data['preview']['positions'] if p['sid']=='000009000001')['seat_id']=='G762/17'
    assert action(admin,app,eid,'approve').status_code==302
    assert exam_state(app,eid)['published_id']==state['draft_id']
    ticket=post(app.test_client(),'/',exam_id=eid,sid='000001000001')
    assert b'Seat confirmed' in ticket.data and b'761' in ticket.data and b'Second Floor' in ticket.data
    report=admin.get(f'/admin/exams/{eid}/export')
    book=load_workbook(BytesIO(report.data))
    validation=list(book['Allocation validation'].values)
    assert any('Administrator-selected rooms' in str(v) for row in validation for v in row)
    assert b'761' in admin.get(f'/admin/block-classrooms?exam_id={eid}').data
    # A subsequent official roster amendment retains the manual room policy.
    assert action(admin,app,eid,'roster',sid='000002000004',block_no='2',subject_code='SUB2',reason='Authorized corrected list').status_code==302
    with app.app_context():
        data=decoded(revision(exam_state(app,eid)['draft_id'],eid));verify_revision(data['config'],data['preview'])
        assert data['preview']['manual_room_selection'] is True and room_for(data['preview'],'1')=={'G761'}
