"""Exact, confirmed emergency placement into draft/approved/published arrangements."""
import json
import pytest
from services.db import get_db
from services.allocation_service import decoded,revision,verify_revision
from .conftest import seed,action,post,exam_state,release_window
from .test_pdf_workflow import upload_pdf,first_exam


def seats(app,rid):
    with app.app_context():return {r['sid']:r['seat_id'] for r in get_db().execute('SELECT sid,seat_id FROM assignments WHERE revision_id=?',(rid,))}


def place(admin,app,eid,**changes):
    state=exam_state(app,eid)
    data={'base_revision':state['draft_id'],'confirmed':'yes','sid':'LATE-001','name':'Late Student','branch':'ICT','batch':'2024','year':'2','target':'R1/5/3/1',**changes}
    return action(admin,app,eid,'emergency-seat',**data)


def test_confirmed_placement_updates_published_approval_atomically(app,admin):
    eid,room=seed(app);release_window(app,eid)
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    old=exam_state(app,eid);before=seats(app,old['published_id'])
    result=place(admin,app,eid,target=f'R{room}/5/3/1')
    assert result.status_code==302,result.data
    state=exam_state(app,eid);assert state['approved_id']==state['draft_id']==state['published_id']!=old['published_id']
    assert state['publication']==old['publication'] and state['publish_at']==old['publish_at']
    current=seats(app,state['published_id']);assert current=={**before,'LATE-001':f'R{room}/5/3/1'}
    assert seats(app,old['published_id'])==before
    assert b'Seat confirmed' in post(app.test_client(),'/',exam_id=eid,sid='LATE-001').data
    with app.app_context():
        row=revision(state['published_id'],eid);assert row['approved']==1
        data=decoded(row);verify_revision(data['config'],data['preview'])
        assert get_db().execute("SELECT 1 FROM audit WHERE action='emergency_placement_confirmed'").fetchone()
    board=admin.get(result.location);assert b'Prepare student to drag' in board.data and b'data-empty-seat=' in board.data


@pytest.mark.parametrize('stage',['draft','approved','scheduled','unpublished'])
def test_preserves_existing_stage_and_release_gate(app,admin,stage):
    eid,room=seed(app);release_window(app,eid,-1)
    with app.app_context():get_db().execute('UPDATE exams SET auto_publish=1 WHERE id=?',(eid,))
    assert action(admin,app,eid,'generate').status_code==302
    if stage!='draft':assert action(admin,app,eid,'approve').status_code==302
    if stage in ('approved','unpublished'):assert action(admin,app,eid,'publication',action='unpublish').status_code==302
    old=exam_state(app,eid)
    assert place(admin,app,eid,target=f'R{room}/5/3/1').status_code==302
    state=exam_state(app,eid)
    assert state['publication']==old['publication'] and state['publish_at']==old['publish_at']
    if stage=='draft':assert state['approved_id'] is None and state['published_id'] is None
    else:
        assert state['approved_id']==state['draft_id']
        assert state['published_id']==(state['draft_id'] if old['published_id']==old['draft_id'] else old['published_id'])
    assert b'Seat confirmed' not in post(app.test_client(),'/',exam_id=eid,sid='LATE-001').data
    release_window(app,eid)
    assert (b'Seat confirmed' in post(app.test_client(),'/',exam_id=eid,sid='LATE-001').data)==(stage=='scheduled')


def test_rejected_drop_occupied_blocked_locked_duplicate_cancel_and_stale(app,admin):
    eid,room=seed(app,states={'5/3/1':'blocked'})
    assert action(admin,app,eid,'generate').status_code==302
    with app.app_context():
        row=revision(exam_state(app,eid)['draft_id'],eid);positions=decoded(row)['preview']['positions']
        occupied=next(p['seat_id'] for p in positions if p['sid'])
        free=next(p['seat_id'] for p in positions if not p['sid'] and not p['blocked'])
    original=exam_state(app,eid)
    for data in ({'confirmed':''},{'target':occupied},{'target':f'R{room}/5/3/1'},{'target':'invented'},{'sid':'00000','target':free},{'base_revision':999}):
        result=place(admin,app,eid,**data);assert result.status_code==422,result.data
        assert exam_state(app,eid)==original
    assert action(admin,app,eid,'edit',operation='lock',source=free).status_code==302
    assert place(admin,app,eid,target=free).status_code==422
    assert post(app.test_client(),f'/admin/exams/{eid}/emergency-seat').status_code==302
    assert admin.post(f'/admin/exams/{eid}/emergency-seat',data={}).status_code==400
    state=exam_state(app,eid)
    assert post(admin,f'/admin/exams/{eid}/emergency-seat',version=original['version'],base_revision=original['draft_id'],confirmed='yes').status_code==422
    assert exam_state(app,eid)==state
    with app.app_context():assert get_db().execute('SELECT count(*) FROM students WHERE exam_id=?',(eid,)).fetchone()[0]==10


def test_gtu_emergency_needs_no_block_and_can_use_any_empty_seat(app,admin):
    import copy
    location=upload_pdf(admin);assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id'];release_window(app,eid)
    assert action(admin,app,eid,'approve').status_code==302
    old=exam_state(app,eid);before=seats(app,old['published_id'])
    for sid,target in [('000002000003','G721/9'),('000002000004','G725/17')]:
        result=place(admin,app,eid,target=target,sid=sid)
        assert result.status_code==302,result.data
        before[sid]=target
        state=exam_state(app,eid)
        assert seats(app,state['published_id'])==before
        assert state['approved_id']==state['published_id']
    board=admin.get(f'/admin/exams/{eid}/arrangement')
    assert b'name="block_no"' not in board.data and b'Emergency admission' in board.data
    with app.app_context():
        data=decoded(revision(state['published_id'],eid));verify_revision(data['config'],data['preview'])
        assert data['config']['emergency_seats']['000002000004']=='G725/17'
        assert data['metadata']['students']['000002000004']['name']=='Late Student'
        broken=copy.deepcopy(data['preview'])
        # Regular students still cannot acquire gaps or violate GTU ordering.
        regular=next(p for p in broken['positions'] if p.get('sid')=='000001000001')
        empty=next(p for p in broken['positions'] if p['seat_id']=='G721/8')
        for key in ('sid','block_no','subject_code','subject_name'):
            regular[key],empty[key]=empty[key],regular[key]
        with pytest.raises(ValueError):verify_revision(data['config'],broken)
        moved=copy.deepcopy(data['preview'])
        emergency=next(p for p in moved['positions'] if p.get('sid')=='000002000004')
        emergency['seat_id']='G725/18';emergency['seat_number']=18
        with pytest.raises(ValueError):verify_revision(data['config'],moved)
    # Regeneration either retains the explicit seat reservations or fails without replacing them.
    assert action(admin,app,eid,'generate').status_code==302
    assert seats(app,exam_state(app,eid)['draft_id'])==before
    assert action(admin,app,eid,'delete',confirm_title=state['title']).status_code==302


def test_custom_pdf_emergency_does_not_request_an_official_block(app,admin):
    layout={'rows':3,'columns':3,'seats_per_bench':1,'seats':{}}
    assert post(admin,'/admin/rooms/new',building='Test',number='C1',layout=json.dumps(layout)).status_code==302
    with app.app_context():room=get_db().execute('SELECT id FROM rooms').fetchone()[0]
    location=upload_pdf(admin,mode='seating',room_ids=str(room));assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id']
    assert place(admin,app,eid,sid='000002000003',target=f'R{room}/3/3/1').status_code==302
    assert seats(app,exam_state(app,eid)['draft_id'])['000002000003']==f'R{room}/3/3/1'
