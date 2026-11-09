from datetime import datetime,timedelta,timezone
from io import BytesIO
from pathlib import Path
import json
import pytest
from services.db import get_db
from services.pdf_service import tools_available
from services.publication_service import release_at
from .conftest import post,action,exam_state,release_window
from .pdf_fixtures import make_pdf,report_lines

pytestmark=pytest.mark.skipif(not tools_available(),reason='Local Poppler tools required for PDF workflow')


def upload_pdf(admin,mode='gtu',lines=None,**extra):
    response=post(admin,'/admin/pdf',pdf=(BytesIO(make_pdf(lines or report_lines())),'blocks.pdf'),mode=mode,
                  timezone='Asia/Kolkata',morning_time='10:00',afternoon_time='15:00',auto_publish='on',**extra)
    assert response.status_code==302,response.data
    return response.location


def first_exam(app):
    with app.app_context():return dict(get_db().execute('SELECT * FROM exams ORDER BY id LIMIT 1').fetchone())


def test_pdf_import_generates_visual_arrangement_and_auto_24h_release(app,admin):
    location=upload_pdf(admin)
    preview=admin.get(location)
    assert preview.status_code==200 and b'2 blocks' in preview.data and b'5 enrollments' in preview.data
    with app.app_context():assert get_db().execute('SELECT count(*) FROM exams').fetchone()[0]==0
    assert post(admin,location,sessions='0',time_0='11:15').status_code==302
    exam=first_exam(app);eid=exam['id']
    assert exam['source']=='pdf' and exam['draft_id'] and exam['historical']==0 and exam['auto_publish']==1
    assert exam['starts_at']=='2099-05-13T05:45:00+00:00'
    board=admin.get(f'/admin/exams/{eid}/arrangement')
    assert board.status_code==200 and b'Block 1' in board.data and b'draggable="true"' in board.data
    assert b'000001000001' in board.data and b'PDF bench 1' in board.data
    assert b'GOVERNMENT POLYTECHNIC HIMMATNAGAR EXAM MANAGEMENT' in board.data and b'made by Eklavy Patel' in board.data
    assert action(admin,app,eid,'approve').status_code==302
    state=exam_state(app,eid)
    assert state['publication']=='scheduled' and state['published_id']==state['approved_id']
    assert state['publish_at']==release_at(state['starts_at'])
    public=app.test_client()
    release_window(app,eid,-1)
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='000001000001').data
    # Even an explicit publish request cannot bypass the server-side 24h gate.
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='000001000001').data
    release_window(app,eid)
    ticket=post(public,'/',exam_id=eid,sid='000001000001')
    assert b'Seat confirmed' in ticket.data and b'GTU block' in ticket.data
    assert post(admin,location,sessions='0').status_code==404


def test_historical_pdf_is_arrangeable_but_permanently_private(app,admin):
    location=upload_pdf(admin,lines=report_lines(date='13-May-20'))
    assert b'Historical' in admin.get(location).data
    assert post(admin,location,sessions='0').status_code==302
    exam=first_exam(app);eid=exam['id']
    assert exam['historical']==1 and exam['auto_publish']==0 and exam['draft_id']
    assert action(admin,app,eid,'approve').status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==422
    assert b'Seat confirmed' not in post(app.test_client(),'/',exam_id=eid,sid='000001000001').data
    assert admin.get(f'/admin/exams/{eid}/export').status_code==200
    assert b'Create editable copy of approval' in admin.get(f'/admin/exams/{eid}').data
    assert action(admin,app,eid,'copy').status_code==302
    assert b'draggable="true"' in admin.get(f'/admin/exams/{eid}/arrangement').data


def test_gtu_board_reorders_whole_blocks_and_rejects_invalid_edits(app,admin):
    location=upload_pdf(admin);assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id']
    assert action(admin,app,eid,'edit',operation='move_block',source='1',target='G721',view='arrangement').status_code==302
    with app.app_context():
        rid=exam_state(app,eid)['draft_id']
        first=json.loads(get_db().execute('SELECT payload FROM assignments WHERE revision_id=? ORDER BY seat_id LIMIT 1',(rid,)).fetchone()[0])
        assert first['block_no']=='2'  # Source block 1 appended after the intact block 2.
    before=exam_state(app,eid)['draft_id']
    assert action(admin,app,eid,'edit',operation='swap',source='G721/1',target='G721/2').status_code==422
    assert exam_state(app,eid)['draft_id']==before
    # Manual room selection may skip earlier rooms; automatic generation still fills in order.
    assert action(admin,app,eid,'edit',operation='swap_rooms',source='G721',target='G722').status_code==302
    assert exam_state(app,eid)['draft_id']!=before


def test_custom_pdf_individual_drag_swap_preserves_source_block_labels(app,admin):
    layout={'rows':2,'columns':3,'seats_per_bench':1,'seats':{}}
    assert post(admin,'/admin/rooms/new',building='Custom building',number='C1',layout=json.dumps(layout)).status_code==302
    with app.app_context():room_id=get_db().execute('SELECT id FROM rooms').fetchone()[0]
    location=upload_pdf(admin,mode='seating',room_ids=str(room_id))
    assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id']
    assert admin.get(f'/admin/exams/{eid}/arrangement').status_code==200
    a=f'R{room_id}/1/1/1';b=f'R{room_id}/1/2/1'
    assert action(admin,app,eid,'edit',operation='swap',source=a,target=b,view='arrangement').status_code==302
    with app.app_context():
        rid=exam_state(app,eid)['draft_id']
        payload=json.loads(get_db().execute('SELECT payload FROM assignments WHERE revision_id=? AND seat_id=?',(rid,a)).fetchone()[0])
        assert payload['sid']=='000001000002' and payload['block_no']=='1' and payload['pdf_bench']==2
    assert admin.get(f'/admin/exams/{eid}/export').status_code==200


def test_multi_session_pdf_import_and_ownership(app,admin,client):
    lines=report_lines()+report_lines(date='15-May-99')
    location=upload_pdf(admin,lines=lines)
    assert post(admin,location,sessions=['0','1'],time_0='10:00',time_1='12:00').status_code==302
    with app.app_context():
        exams=get_db().execute('SELECT * FROM exams ORDER BY gtu_date').fetchall()
        assert len(exams)==2 and all(e['draft_id'] for e in exams)
        assert exams[0]['starts_at'].endswith('04:30:00+00:00') and exams[1]['starts_at'].endswith('06:30:00+00:00')
    assert app.test_client().get('/admin/pdf').status_code==302


def test_same_day_gtu_pdf_does_not_get_historical_deadline_bypass(app,admin):
    from zoneinfo import ZoneInfo
    today=datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).date()
    location=upload_pdf(admin,lines=report_lines(date=today.strftime('%d-%b-%y')))
    body=admin.get(location).data
    assert b'uploads are blocked' in body
    assert post(admin,location,sessions='0').status_code==422


def test_bad_pdf_and_capacity_errors_keep_existing_data(app,admin):
    response=post(admin,'/admin/pdf',pdf=(BytesIO(b'bad'),'a.pdf'),mode='gtu',timezone='Asia/Kolkata')
    assert response.status_code==422
    location=upload_pdf(admin)
    assert post(admin,location,sessions='99').status_code==422
    with app.app_context():assert get_db().execute('SELECT count(*) FROM exams').fetchone()[0]==0


def test_provided_pdf_full_import_generates_all_seven_private_arrangements(app,admin):
    path=Path(__file__).resolve().parent.parent/'624_DI-SEM4SUMMEREXAMINATION-2026 (1).pdf'
    if not path.exists():pytest.skip('Private sample PDF is not distributed')
    response=post(admin,'/admin/pdf',pdf=(BytesIO(path.read_bytes()),path.name),mode='gtu',timezone='Asia/Kolkata',morning_time='10:00',auto_publish='on')
    assert response.status_code==302
    assert post(admin,response.location,sessions=[str(i) for i in range(7)]).status_code==302
    with app.app_context():
        db=get_db()
        assert db.execute('SELECT count(*) FROM exams WHERE historical=1 AND draft_id IS NOT NULL').fetchone()[0]==7
        assert db.execute('SELECT count(*) FROM assignments').fetchone()[0]==1663
        assert db.execute('SELECT count(*) FROM gtu_students WHERE pdf_bench IS NOT NULL AND pdf_page IS NOT NULL').fetchone()[0]==1663
