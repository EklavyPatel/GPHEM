import json
import re
import sqlite3
from io import BytesIO
from datetime import datetime,timedelta,timezone
import pytest
from openpyxl import load_workbook
from services.db import get_db
from .conftest import post,csrf,seed,action,exam_state,release_window
from .test_excel import workbook,record


def test_auth_csrf_and_server_sessions(client,app):
    assert client.get('/admin').status_code==302
    assert client.post('/admin/login',data={'username':'exam-admin','password':'a-test-password-123!'}).status_code==400
    before=client.get('/admin/login');assert before.status_code==200
    old_token=client.get_cookie('seating_session').value
    assert post(client,'/admin/login',username='exam-admin',password='wrong').status_code==200
    assert post(client,'/admin/login',username='exam-admin',password='a-test-password-123!').status_code==302
    new_token=client.get_cookie('seating_session').value
    assert old_token!=new_token and 'exam-admin' not in new_token
    assert client.get('/admin').status_code==200
    assert post(client,'/admin/logout').status_code==302
    assert client.get('/admin').status_code==302
    stolen=app.test_client();stolen.set_cookie('seating_session',new_token)
    assert stolen.get('/admin').status_code==302


def test_login_rate_limiting(client):
    for _ in range(10): assert post(client,'/admin/login',username='exam-admin',password='bad').status_code==200
    assert post(client,'/admin/login',username='exam-admin',password='bad').status_code==429


def test_exam_and_classroom_creation(admin,app):
    layout={'rows':3,'columns':4,'seats_per_bench':2,'seats':{'1/1/1':'blocked','1/2/1':'reserved','2/1/1':'accessible'}}
    r=post(admin,'/admin/rooms/new',building='A',number='001',layout=json.dumps(layout))
    assert r.status_code==302
    r=post(admin,'/admin/exams/new',title='Test Exam',starts_at='2026-12-15T09:30',timezone='Asia/Kolkata')
    assert r.status_code==302
    with app.app_context():
        exam=dict(get_db().execute('SELECT * FROM exams').fetchone())
        room=get_db().execute('SELECT * FROM rooms').fetchone()
        assert exam['starts_at']=='2026-12-15T04:00:00+00:00'
    assert admin.get(f'/admin/rooms/{room["id"]}').status_code==200
    r=post(admin,f'/admin/exams/{exam["id"]}',version=1,title='Test Exam',starts_at='2026-12-15T09:30',timezone='Asia/Kolkata',room_ids=str(room['id']))
    assert r.status_code==302


@pytest.mark.parametrize('layout',[{'rows':0,'columns':2,'seats_per_bench':1},
 {'rows':2,'columns':2,'seats_per_bench':1,'seats':{'9/1/1':'blocked'}},
 {'rows':2,'columns':2,'seats_per_bench':1,'seats':{'1/1/1':'magic'}}])
def test_invalid_room_rejected(admin,layout):
    assert post(admin,'/admin/rooms/new',building='A',number='1',layout=json.dumps(layout)).status_code==422


def test_excel_preview_confirm_and_duplicate(app,admin):
    eid,_=seed(app,count=0)
    response=post(admin,f'/admin/exams/{eid}/students',version=1,workbook=(BytesIO(workbook([record('001',session='Semester Examination')])),'a.xlsx'))
    assert response.status_code==302
    location=response.location
    preview=admin.get(location);assert b'001' in preview.data
    with app.app_context():assert get_db().execute('SELECT count(*) FROM students').fetchone()[0]==0
    assert post(admin,location).status_code==302
    with app.app_context():assert get_db().execute('SELECT sid FROM students').fetchone()[0]=='001'
    assert post(admin,location).status_code==404
    response=post(admin,f'/admin/exams/{eid}/students',version=exam_state(app,eid)['version'],workbook=(BytesIO(workbook([record('001',session='Semester Examination')])),'a.xlsx'))
    assert b'Duplicate' in admin.get(response.location).data
    assert post(admin,response.location).status_code==422
    report=admin.get(response.location+'/report');assert report.status_code==200
    assert load_workbook(BytesIO(report.data))['Validation errors'].max_row>1


def test_full_approval_publication_lookup_export(app,admin):
    eid,_=seed(app)
    release_window(app,eid)
    assert action(admin,app,eid,'generate').status_code==302
    state=exam_state(app,eid)
    assert state['approved_id'] is None and state['published_id'] is None
    assert admin.get(f'/admin/exams/{eid}/chart').status_code==200
    public=app.test_client()
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='00000').data
    assert action(admin,app,eid,'publication',action='publish').status_code==422
    assert action(admin,app,eid,'approve').status_code==302
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='00000').data
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    response=post(public,'/',exam_id=eid,sid='00000')
    assert b'00000' in response.data and b'Science Block' in response.data and b'Student 0' not in response.data
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='0000').data
    export=admin.get(f'/admin/exams/{eid}/export');assert export.status_code==200
    book=load_workbook(BytesIO(export.data))
    assert book['Complete allocation']['A2'].value=='00000'
    assert book['Complete allocation']['A2'].data_type=='s'
    assert book['Unallocated students'].max_row==1
    assert book['Complete allocation'].max_row==11
    assert {'Room-wise lists','Branch-wise lists','Classroom utilization','Allocation validation'}<=set(book.sheetnames)
    assert action(admin,app,eid,'publication',action='unpublish').status_code==302
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='00000').data
    assert public.get(f'/admin/exams/{eid}/export').status_code==302


def test_scheduled_release_is_enforced_and_name_permission(app,admin):
    eid,_=seed(app)
    with app.app_context():get_db().execute('UPDATE exams SET show_names=1 WHERE id=?',(eid,))
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    with app.app_context():get_db().execute('UPDATE exams SET publish_at=? WHERE id=?',((datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),eid))
    release_window(app,eid,-1)
    assert action(admin,app,eid,'publication',action='schedule').status_code==302
    public=app.test_client()
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='00000').data
    with app.app_context():get_db().execute('UPDATE exams SET publish_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),eid))
    release_window(app,eid)
    response=post(public,'/',exam_id=eid,sid='00000')
    assert b'00000' in response.data and b'Student 0' in response.data


def test_swaps_locks_and_approved_immutability(app,admin):
    eid,rid=seed(app)
    assert action(admin,app,eid,'generate').status_code==302
    original=exam_state(app,eid)['draft_id']
    assert action(admin,app,eid,'edit',operation='swap',source=f'R{rid}/1/1/1',target=f'R{rid}/1/2/1').status_code==302
    assert action(admin,app,eid,'edit',operation='lock',source=f'R{rid}/1/1/1').status_code==302
    assert action(admin,app,eid,'edit',operation='swap',source=f'R{rid}/1/1/1',target=f'R{rid}/1/2/1').status_code==422
    assert action(admin,app,eid,'edit',operation='regenerate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    approved=exam_state(app,eid)['approved_id']
    assert action(admin,app,eid,'edit',operation='lock',source=f'R{rid}/1/1/1').status_code==422
    assert action(admin,app,eid,'copy').status_code==302
    assert exam_state(app,eid)['approved_id']==approved
    assert exam_state(app,eid)['draft_id']!=approved
    with app.app_context():
        assert get_db().execute('SELECT count(*) FROM revisions WHERE id IN (?,?)',(original,approved)).fetchone()[0]==2


def test_failed_generation_preserves_approved_publication(app,admin):
    eid,_=seed(app)
    release_window(app,eid)
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    old=exam_state(app,eid)
    with app.app_context():
        get_db().execute('UPDATE exams SET rules=?,version=version+1 WHERE id=?',(json.dumps([{'id':'none','type':'allow','values':['Unknown']}]),eid))
    response=action(admin,app,eid,'generate');assert response.status_code==422
    report=admin.get(f'/admin/exams/{eid}/errors.xlsx')
    assert report.status_code==200 and load_workbook(BytesIO(report.data)).active.max_row==2
    after=exam_state(app,eid)
    assert (after['approved_id'],after['published_id'],after['draft_id'])==(old['approved_id'],old['published_id'],old['draft_id'])
    assert b'00000' in post(app.test_client(),'/',exam_id=eid,sid='00000').data


def test_rules_schema_stale_edits_and_ordered_swap(app,admin):
    eid,rid=seed(app)
    response=action(admin,app,eid,'rules',rules=json.dumps([{'id':'x','type':'magic'}]),seed=42)
    assert response.status_code==422
    response=action(admin,app,eid,'rules',rules=json.dumps([{'id':'x','type':'order','mode':'ascending_sid'}]),seed=42,preset_name='Sequential')
    assert response.status_code==302
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'edit',operation='swap',source=f'R{rid}/1/1/1',target=f'R{rid}/1/2/1').status_code==422
    stale=exam_state(app,eid)['version']-1
    assert post(admin,f'/admin/exams/{eid}/approve',version=stale).status_code==422
    response=action(admin,app,eid,'rules',rules='[]',seed=1)
    assert response.status_code==302
    assert action(admin,app,eid,'approve').status_code==422


def test_blocked_reserved_accessible_and_invalid_swap(app,admin):
    eid,rid=seed(app,states={'1/1/1':'blocked','1/2/1':'reserved','1/3/1':'accessible'})
    assert action(admin,app,eid,'generate').status_code==302
    with app.app_context():
        row=get_db().execute('SELECT preview FROM revisions').fetchone()
        positions=json.loads(row['preview'])['positions']
        assert positions[0]['sid'] is None and positions[1]['sid'] is None
        assert positions[2]['sid'] is not None
    assert action(admin,app,eid,'edit',operation='swap',source=f'R{rid}/1/3/1',target=f'R{rid}/1/1/1').status_code==422
    assert action(admin,app,eid,'edit',operation='swap',source='unknown',target='unknown').status_code==422


def test_all_admin_pages_and_backups(app,admin):
    eid,rid=seed(app)
    for url in ['/admin','/admin/rooms',f'/admin/rooms/{rid}',f'/admin/exams/{eid}',
                f'/admin/exams/{eid}/students',f'/admin/exams/{eid}/rules','/admin/audit','/admin/exams/new']:
        response=admin.get(url); assert response.status_code==200,(url,response.data)
    response=admin.get('/admin/backup'); assert response.status_code==200 and response.data.startswith(b'SQLite format 3')
    assert admin.get('/admin/template.xlsx').status_code==200


def test_backup_restores_and_duplicate_assignment_constraint(app,admin,tmp_path):
    eid,_=seed(app)
    assert action(admin,app,eid,'generate').status_code==302
    backup=tmp_path/'restored.sqlite';backup.write_bytes(admin.get('/admin/backup').data)
    db=sqlite3.connect(backup)
    assert db.execute('SELECT count(*) FROM students').fetchone()[0]==10
    db.close()
    with app.app_context():
        db=get_db();row=db.execute('SELECT * FROM assignments LIMIT 1').fetchone()
        from services.db import INTEGRITY_ERRORS
        with pytest.raises(INTEGRITY_ERRORS):db.execute('INSERT INTO assignments VALUES(?,?,?,?)',tuple(row))


def test_first_run_cli_and_no_default_credentials(app):
    runner=app.test_cli_runner()
    response=runner.invoke(args=['create-admin','--username','new-admin'],input='strong-example-password\nstrong-example-password\n')
    assert response.exit_code==0,response.output
    response=runner.invoke(args=['create-admin','--username','short'],input='short\nshort\n')
    assert response.exit_code!=0
    response=runner.invoke(args=['reset-password','--username','new-admin'],input='another-long-password\nanother-long-password\n')
    assert response.exit_code==0,response.output


def test_public_lookup_rate_limit_and_no_lists(app,admin):
    eid,_=seed(app)
    for endpoint in ['generate','approve']:assert action(admin,app,eid,endpoint).status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    public=app.test_client()
    for _ in range(60):assert post(public,'/',sid='missing',exam_id=eid).status_code==200
    assert post(public,'/',sid='00000',exam_id=eid).status_code==429
    assert public.get('/api/students').status_code==404
    assert 'no-store' in public.get('/').headers['Cache-Control']


def test_unicode_csrf_is_rejected_without_server_error(client):
    client.get('/admin/login')
    assert client.post('/admin/login',data={'csrf_token':'é'}).status_code==400


def test_revoked_session_cannot_be_resurrected(app,admin):
    from services.security import ServerSession,SQLiteSessions,digest
    cookie=admin.get_cookie('seating_session').value
    # Model an in-flight request that loaded the session before concurrent logout.
    with app.app_context():
        row=get_db().execute('SELECT data FROM web_sessions WHERE token_hash=?',(digest(cookie),)).fetchone()
        stale=ServerSession(json.loads(row['data']),cookie,is_new=False)
        stale['pending_flash']='A late request modified its session.'
    assert post(admin,'/admin/logout').status_code==302
    with app.app_context():
        response=app.response_class()
        SQLiteSessions().save_session(app,stale,response)
        assert get_db().execute('SELECT 1 FROM web_sessions WHERE token_hash=?',(digest(cookie),)).fetchone() is None


def test_entire_workflow_through_real_forms(app,admin):
    """Create, configure, import, allocate, approve, publish and look up without seed shortcuts."""
    created=post(admin,'/admin/exams/new',title='College Finals',starts_at='2026-12-15T09:30',timezone='Asia/Kolkata')
    assert created.status_code==302
    eid=int(created.location.rstrip('/').split('/')[-1])
    release_window(app,eid)
    layout={'rows':4,'columns':3,'seats_per_bench':1,'seats':{'4/3/1':'blocked'}}
    assert post(admin,'/admin/rooms/new',building='Main Block',number='A101',layout=json.dumps(layout)).status_code==302
    with app.app_context():rid=get_db().execute('SELECT id FROM rooms WHERE number=?',('A101',)).fetchone()[0]
    assert post(admin,f'/admin/exams/{eid}',version=exam_state(app,eid)['version'],title='College Finals',
                starts_at='2026-12-15T09:30',timezone='Asia/Kolkata',room_ids=str(rid)).status_code==302
    uploaded=post(admin,f'/admin/exams/{eid}/students',version=exam_state(app,eid)['version'],
                  workbook=(BytesIO(workbook([record(f'{i:03}',session='College Finals') for i in range(10)])),'roster.xlsx'))
    assert uploaded.status_code==302
    assert admin.get(uploaded.location).status_code==200
    assert post(admin,uploaded.location).status_code==302
    assert action(admin,app,eid,'rules',rules=json.dumps([{'id':'order','type':'order','mode':'ascending_sid'}]),seed=42).status_code==302
    assert action(admin,app,eid,'generate').status_code==302
    assert b'A101' in admin.get(f'/admin/exams/{eid}/chart').data
    assert action(admin,app,eid,'approve').status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    public=app.test_client()
    seat=post(public,'/',exam_id=eid,sid='000')
    assert b'Seat confirmed' in seat.data and b'000' in seat.data and b'Main Block' in seat.data
    assert admin.get(f'/admin/exams/{eid}/export').status_code==200
    assert action(admin,app,eid,'publication',action='unpublish').status_code==302
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='000').data


@pytest.mark.parametrize('count,rows,columns,seats',[(10,3,5,1),(100,11,10,1),(1000,21,25,2),(5000,50,50,3)])
def test_allocation_integration_dataset_sizes(app,admin,count,rows,columns,seats):
    eid,_=seed(app,count=count,rows=rows,columns=columns,seats_per_bench=seats,
               states={'1/1/1':'blocked','1/2/1':'reserved','1/3/1':'accessible'})
    assert action(admin,app,eid,'generate').status_code==302
    state=exam_state(app,eid)
    with app.app_context():
        db=get_db()
        assert db.execute('SELECT count(*) FROM assignments WHERE revision_id=?',(state['draft_id'],)).fetchone()[0]==count
        row=db.execute('SELECT * FROM revisions WHERE id=?',(state['draft_id'],)).fetchone()
        from engine import Plan,Exam
        config,preview=json.loads(row['config']),json.loads(row['preview'])
        Plan(Exam.model_validate(config),preview).verify({p['seat_id']:p['sid'] for p in preview['positions']})
    assert action(admin,app,eid,'approve').status_code==302
