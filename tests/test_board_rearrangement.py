"""Restored block/room drag operations, including arrangements with emergency seats."""
import copy
import json
import pytest
from services.db import get_db
from services.allocation_service import decoded,revision,verify_revision
from services.gtu_engine import edit_blocks
from .conftest import post,action,exam_state,release_window
from .test_pdf_workflow import upload_pdf,first_exam
from .pdf_fixtures import report_lines


def prepared(app,admin,emergency_seat='G721/30'):
    location=upload_pdf(admin,lines=report_lines(sizes=(16,12,8)))
    assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id'];release_window(app,eid)
    assert action(admin,app,eid,'approve').status_code==302
    state=exam_state(app,eid)
    assert action(admin,app,eid,'emergency-seat',base_revision=state['draft_id'],confirmed='yes',sid='000009000001',target=emergency_seat).status_code==302
    return eid


def snapshot(app,eid,rid=None):
    with app.app_context():return decoded(revision(rid or exam_state(app,eid)['draft_id'],eid))


def occupied(data):return {p['sid']:p['seat_id'] for p in data['preview']['positions'] if p['sid']}


@pytest.mark.parametrize('operation,source,target',[('swap_blocks','1','3'),('swap_rooms','G721','G722'),('move_block','1','G721')])
def test_engine_rearranges_regular_blocks_while_emergency_stays_fixed(app,admin,operation,source,target):
    eid=prepared(app,admin);data=snapshot(app,eid);original=copy.deepcopy(data)
    edited=edit_blocks(data['config'],data['preview'],operation,source,target)
    verify_revision(data['config'],edited)
    assert data==original
    assert next(p for p in edited['positions'] if p['sid']=='000009000001')['seat_id']=='G721/30'
    assert {p['sid'] for p in edited['positions']}=={p['sid'] for p in data['preview']['positions']}
    if operation=='swap_blocks':
        assert {p['room'] for p in edited['positions'] if p.get('block_no')=='1'}=={'G722'}
        assert {p['room'] for p in edited['positions'] if p.get('block_no')=='3'}=={'G721'}


def test_dragging_approved_published_board_creates_draft_without_publishing(app,admin):
    eid=prepared(app,admin);old=exam_state(app,eid);previous=snapshot(app,eid)
    page=admin.get(f'/admin/exams/{eid}/arrangement')
    assert b'data-drag-kind="block"' in page.data and b'data-drag-kind="room"' in page.data
    assert b'id="board-edit-form"' in page.data and b'Interchange two blocks' in page.data
    assert b'whole-block rearrangement is disabled' not in page.data
    response=action(admin,app,eid,'edit',operation='swap_blocks',source='1',target='3',view='arrangement',base_revision=old['draft_id'])
    assert response.status_code==302,response.data
    state=exam_state(app,eid)
    assert state['draft_id']!=old['draft_id'] and state['approved_id']==old['approved_id'] and state['published_id']==old['published_id']
    assert state['publication']==old['publication'] and state['publish_at']==old['publish_at']
    assert snapshot(app,eid,old['published_id'])==previous
    draft=snapshot(app,eid);verify_revision(draft['config'],draft['preview'])
    assert occupied(draft)['000009000001']=='G721/30'
    assert occupied(draft)['000001000001'].startswith('G722/')
    assert action(admin,app,eid,'approve').status_code==302
    assert exam_state(app,eid)['published_id']==state['draft_id']


def test_rejected_approved_drag_rolls_back_copy_and_keeps_publication(app,admin):
    eid=prepared(app,admin,'G722/9');before=exam_state(app,eid)
    with app.app_context():count=get_db().execute('SELECT count(*) FROM revisions WHERE exam_id=?',(eid,)).fetchone()[0]
    # Incoming 28 regular students would overlap the fixed emergency seat 9.
    response=action(admin,app,eid,'edit',operation='swap_rooms',source='G721',target='G722',view='arrangement',base_revision=before['draft_id'])
    assert response.status_code==422 and b'emergency student' in response.data
    assert exam_state(app,eid)==before
    with app.app_context():assert get_db().execute('SELECT count(*) FROM revisions WHERE exam_id=?',(eid,)).fetchone()[0]==count
    assert action(admin,app,eid,'edit',operation='swap_blocks',source='1',target='EMERGENCY:000009000001',view='arrangement',base_revision=before['draft_id']).status_code==422
    assert exam_state(app,eid)==before


def test_board_rejects_old_revision_stale_inputs_and_missing_csrf(app,admin):
    eid=prepared(app,admin);before=exam_state(app,eid)
    assert action(admin,app,eid,'edit',operation='swap_rooms',source='G721',target='G722',view='arrangement',base_revision=999).status_code==422
    assert admin.post(f'/admin/exams/{eid}/edit',data={}).status_code==400
    with app.app_context():get_db().execute("UPDATE exams SET gtu_disabled='[\"721\"]' WHERE id=?",(eid,))
    page=admin.get(f'/admin/exams/{eid}/arrangement')
    assert b'data-drag-kind="room"' not in page.data
    assert action(admin,app,eid,'edit',operation='swap_rooms',source='G721',target='G722',view='arrangement',base_revision=before['draft_id']).status_code==422
    state=exam_state(app,eid);assert state['published_id']==before['published_id'] and state['draft_id']==before['draft_id']
