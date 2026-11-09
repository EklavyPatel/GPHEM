"""Regression checks for the audit findings and reviewed college amendments."""
from io import BytesIO
from datetime import datetime,timedelta
import json
import re
import shutil
import subprocess
from pathlib import Path
import pytest
from services.db import get_db
from services.allocation_service import decoded,revision,verify_revision
from .conftest import seed,post,action,exam_state,release_window
from .test_pdf_workflow import upload_pdf,first_exam
from .pdf_fixtures import make_pdf,report_lines


def settings(admin,app,eid,**changes):
    e=exam_state(app,eid)
    data={'title':e['title'],'starts_at':datetime.fromisoformat(e['starts_at']).replace(tzinfo=None).isoformat(timespec='minutes'),
          'timezone':'UTC','room_ids':[],'version':e['version'],**changes}
    # The helper's UTC is valid for seeded Custom Mode sessions only.
    return post(admin,f'/admin/exams/{eid}',**data)


def assert_valid(app,eid):
    with app.app_context():
        data=decoded(revision(exam_state(app,eid)['draft_id'],eid))
        verify_revision(data['config'],data['preview'])
        return data


def test_copy_and_approval_reject_current_room_changes(app,admin):
    eid,rid=seed(app)
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    with app.app_context():
        db=get_db();layout=json.loads(db.execute('SELECT layout FROM rooms WHERE id=?',(rid,)).fetchone()[0]);layout['seats']['1/1/1']='blocked'
        db.execute('UPDATE rooms SET layout=?,version=version+1 WHERE id=?',(json.dumps(layout),rid))
    assert action(admin,app,eid,'copy').status_code==422
    # Approval also checks real inputs if the room changed without an exam counter update.
    assert action(admin,app,eid,'generate').status_code==302
    with app.app_context():get_db().execute('UPDATE rooms SET version=version+1 WHERE id=?',(rid,))
    assert action(admin,app,eid,'approve').status_code==422


def test_time_change_within_release_window_hides_old_ticket_and_toggle_cancels(app,admin):
    eid,rid=seed(app);release_window(app,eid)
    with app.app_context():get_db().execute('UPDATE exams SET auto_publish=1 WHERE id=?',(eid,))
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    assert b'Seat confirmed' in post(app.test_client(),'/',exam_id=eid,sid='00000').data
    e=exam_state(app,eid)
    response=post(admin,f'/admin/exams/{eid}',version=e['version'],title=e['title'],starts_at='2026-12-15T10:30',timezone='Asia/Kolkata',room_ids=str(rid),auto_publish='on')
    assert response.status_code==302
    assert exam_state(app,eid)['publication']=='off'
    assert b'Seat confirmed' not in post(app.test_client(),'/',exam_id=eid,sid='00000').data
    assert action(admin,app,eid,'publication',action='publish').status_code==422
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    e=exam_state(app,eid)
    assert post(admin,f'/admin/exams/{eid}',version=e['version'],title=e['title'],starts_at='2026-12-15T10:30',timezone='Asia/Kolkata',room_ids=str(rid)).status_code==302
    assert exam_state(app,eid)['publication']=='off'


def test_custom_release_edit_is_server_enforced(app,admin):
    eid,rid=seed(app);boundary=release_window(app,eid)
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    e=exam_state(app,eid)
    assert post(admin,f'/admin/exams/{eid}',version=e['version'],title=e['title'],starts_at='2026-12-15T09:30',timezone='Asia/Kolkata',room_ids=str(rid),publish_at='2026-12-14T10:30').status_code==302
    assert b'Seat confirmed' not in post(app.test_client(),'/',exam_id=eid,sid='00000').data
    app.config['NOW_UTC']=lambda:boundary+timedelta(hours=1)
    assert b'Seat confirmed' in post(app.test_client(),'/',exam_id=eid,sid='00000').data
    e=exam_state(app,eid)
    assert post(admin,f'/admin/exams/{eid}',version=e['version'],title=e['title'],starts_at='2026-12-15T09:30',timezone='Asia/Kolkata',publish_at='2026-12-16T10:30').status_code==422


def test_emergency_after_publication_preserves_old_seats_and_atomic_rollbacks(app,admin):
    eid,_=seed(app,count=10,rows=4,columns=3);release_window(app,eid)
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    before=exam_state(app,eid);old=assert_valid(app,eid)
    response=action(admin,app,eid,'roster',sid='00010',name='Late Student',branch='ICT',batch='2024',year='2',reason='Office approved late form 123')
    assert response.status_code==302,response.data
    after=exam_state(app,eid);assert after['published_id']==before['published_id'] and after['approved_id']==before['approved_id']
    new=assert_valid(app,eid)
    old_map={p['sid']:p['seat_id'] for p in old['preview']['positions'] if p['sid']}
    assert all(old_map.get(p['sid'],p['seat_id'])==p['seat_id'] for p in new['preview']['positions'] if p['sid'])
    assert b'Seat confirmed' not in post(app.test_client(),'/',exam_id=eid,sid='00010').data
    assert action(admin,app,eid,'approve').status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    assert b'Late Student' not in post(app.test_client(),'/',exam_id=eid,sid='00010').data  # names remain private
    assert b'Seat confirmed' in post(app.test_client(),'/',exam_id=eid,sid='00010').data
    assert action(admin,app,eid,'roster',sid='00010',name='Duplicate',branch='ICT',batch='2024',year='2',reason='Duplicate attempt').status_code==422
    assert action(admin,app,eid,'roster',sid='00011',name='Last Seat',branch='ICT',batch='2024',year='2',reason='Last seat').status_code==302
    state=exam_state(app,eid)
    assert action(admin,app,eid,'roster',sid='00012',name='Overflow',branch='ICT',batch='2024',year='2',reason='No capacity').status_code==422
    assert exam_state(app,eid)==state
    with app.app_context():assert get_db().execute('SELECT count(*) FROM students WHERE exam_id=?',(eid,)).fetchone()[0]==12


def test_revised_pdf_preview_confirmation_original_fill_and_late_block(app,admin,tmp_path):
    location=upload_pdf(admin);assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id'];release_window(app,eid)
    assert action(admin,app,eid,'approve').status_code==302
    prior=exam_state(app,eid)
    preview=action(admin,app,eid,'revised-pdf',pdf=(BytesIO(make_pdf(report_lines(sizes=(4,2)))),'revision.pdf'),reason='Official corrected block list')
    assert preview.status_code==200,preview.data
    token=re.search(rb'/revised-pdf/([^"\s]+)',preview.data)[1].decode()
    confirm=action(admin,app,eid,'revised-pdf/'+token)
    assert confirm.status_code==302,confirm.data
    assert exam_state(app,eid)['published_id']==prior['published_id']
    assert len(assert_valid(app,eid)['config']['students'])==6
    assert admin.get(f'/admin/exams/{eid}/roster?sid=000001000001').status_code==200
    assert action(admin,app,eid,'roster',sid='000001000005',block_no='1',subject_code='SUB1',subject_name='SUB1',reason='Authorized late GTU form').status_code==302
    assert len(assert_valid(app,eid)['config']['students'])==7
    if shutil.which('gs'):
        result=admin.get(f'/admin/exams/{eid}/filled-pdf?revision={exam_state(app,eid)["draft_id"]}')
        assert result.status_code==200,result.data
        file=tmp_path/'filled.pdf';file.write_bytes(result.data)
        extracted=subprocess.run(['pdftotext','-layout',str(file),'-'],capture_output=True,check=True).stdout
        assert b'Room No : 721' in re.sub(rb' +',b' ',extracted)
        assert b'000001000001' in extracted and b'DRAFT revision' in extracted
    assert action(admin,app,eid,'approve').status_code==302


def test_delete_requires_exact_confirmation_and_does_not_touch_other_exams(app,admin):
    eid,_=seed(app);other=post(admin,'/admin/exams/new',title='Keep me',starts_at='2099-01-01T09:00',timezone='Asia/Kolkata',mode='seating')
    assert other.status_code==302
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    assert action(admin,app,eid,'delete',confirm_title='wrong').status_code==422
    assert action(admin,app,eid,'delete',confirm_title=exam_state(app,eid)['title']).status_code==302
    assert admin.get(f'/admin/exams/{eid}').status_code==404
    with app.app_context():
        db=get_db();assert db.execute('SELECT count(*) FROM exams').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM assignments').fetchone()[0]==0
        assert db.execute("SELECT 1 FROM audit WHERE action='delete_exam'").fetchone()


def test_shared_network_has_separate_client_quotas_and_favicon(app):
    a=app.test_client();b=app.test_client()
    for _ in range(60):assert post(a,'/',sid='missing').status_code==200
    assert post(a,'/',sid='missing').status_code==429
    assert post(b,'/',sid='missing').status_code==200
    assert b.get('/favicon.ico',follow_redirects=True).status_code==200
    assert b.get('/admin/exams/1/roster').status_code==302
    assert b.get('/admin/exams/1/filled-pdf').status_code==302


def test_gtu_late_receipt_exception_is_explicit_and_failed_block_edit_rolls_back(app,admin,monkeypatch):
    from types import SimpleNamespace
    from services import amendment_service
    location=upload_pdf(admin);assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id'];assert action(admin,app,eid,'approve').status_code==302
    # Actual receipt is on exam day, rather than inventing an earlier upload timestamp.
    received=datetime.fromisoformat('2099-05-13T04:00:00+00:00').timestamp()
    monkeypatch.setattr(amendment_service,'time',SimpleNamespace(time=lambda:received))
    late=action(admin,app,eid,'roster',sid='000001000004',block_no='1',subject_code='SUB1',reason='Principal authorized late form')
    assert late.status_code==302,late.data
    data=assert_valid(app,eid)
    person=next(p for p in data['config']['students'] if p['sid']=='000001000004')
    assert person['uploaded_at']==received
    assert person['emergency_admission']['reason']=='Principal authorized late form'
    assert action(admin,app,eid,'approve').status_code==302
    state=exam_state(app,eid)
    assert action(admin,app,eid,'roster',sid='000001000005',block_no='1',subject_code='WRONG',reason='Invalid mixed-subject block').status_code==422
    assert exam_state(app,eid)==state
    with app.app_context():assert not get_db().execute('SELECT 1 FROM students WHERE exam_id=? AND sid=?',(eid,'000001000005')).fetchone()


def test_all_linked_pdf_sessions_get_room_numbers(app,admin,tmp_path):
    if not shutil.which('gs'):pytest.skip('Ghostscript required')
    lines=report_lines()+report_lines(date='15-May-99',sizes=(1,1))
    location=upload_pdf(admin,lines=lines);assert post(admin,location,sessions=['0','1']).status_code==302
    eid=first_exam(app)['id']
    response=admin.get(f'/admin/exams/{eid}/filled-pdf?scope=all')
    assert response.status_code==200,response.data
    path=tmp_path/'all.pdf';path.write_bytes(response.data)
    extracted=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,check=True).stdout
    assert len(re.findall(rb'Room\s+No\s*:\s*721',extracted))==4
