"""Institute branding, safe log cleanup and post-exam block/classroom register."""
from io import BytesIO
import json
from openpyxl import load_workbook
from services.db import get_db,audit
from .conftest import seed,post,action,exam_state,release_window
from .test_pdf_workflow import upload_pdf,first_exam

NOTICE=b'The exam management system is currently under testing. Please verify your seating arrangement on the institute notice board.'
NAME=b'GOVERNMENT POLYTECHNIC HIMMATNAGAR EXAM MANAGEMENT'


def test_student_notice_brand_logo_and_best_of_luck(app,client,admin):
    page=client.get('/')
    assert NAME in page.data and NOTICE in page.data and b'BEST OF LUCK' in page.data
    assert b'images/college-logo-original.jpg' in page.data
    logo=client.get('/static/images/college-logo-original.jpg');assert logo.status_code==200 and logo.data.startswith(b'\xff\xd8')
    eid,_=seed(app);release_window(app,eid)
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    ticket=post(client,'/',exam_id=eid,sid='00000')
    assert NOTICE in ticket.data and b'BEST OF LUCK' in ticket.data and b'Seat confirmed' in ticket.data
    assert NAME in admin.get('/admin').data


def audit_rows(app):
    with app.app_context():return [dict(r) for r in get_db().execute('SELECT * FROM audit ORDER BY id')]


def test_selected_log_deletion_requires_auth_csrf_and_confirmation(app,admin):
    rows=audit_rows(app);ids=[r['id'] for r in rows];cutoff=max(ids)
    old=rows
    assert post(admin,'/admin/audit/delete',scope='selected',cutoff=cutoff,log_ids=str(ids[0]),confirmation='wrong').status_code==422
    assert audit_rows(app)==old
    assert admin.post('/admin/audit/delete',data={}).status_code==400
    assert post(app.test_client(),'/admin/audit/delete',scope='all',cutoff=cutoff,confirmation='DELETE').status_code==302
    assert audit_rows(app)==old
    assert post(admin,'/admin/audit/delete',scope='selected',cutoff=cutoff,log_ids=str(ids[0]),confirmation='DELETE').status_code==302
    rows=audit_rows(app)
    assert ids[0] not in {r['id'] for r in rows}
    assert rows[-1]['action']=='delete_audit_logs' and rows[-1]['id']>cutoff
    assert b'Type DELETE to confirm' in admin.get('/admin/audit').data


def test_all_log_deletion_preserves_concurrent_events_and_college_data(app,admin):
    eid,_=seed(app);assert action(admin,app,eid,'generate').status_code==302
    cutoff=max(r['id'] for r in audit_rows(app))
    state=exam_state(app,eid)
    with app.test_request_context():
        with app.app_context():audit('newer_event','Created after page load')
    newest=audit_rows(app)[-1]['id']
    assert post(admin,'/admin/audit/delete',scope='all',cutoff=cutoff,confirmation='DELETE').status_code==302
    rows=audit_rows(app)
    assert all(r['id']>cutoff for r in rows) and any(r['id']==newest for r in rows)
    assert rows[-1]['action']=='delete_audit_logs'
    assert exam_state(app,eid)==state
    with app.app_context():assert get_db().execute('SELECT count(*) FROM students WHERE exam_id=?',(eid,)).fetchone()[0]==10
    assert post(admin,'/admin/audit/delete',scope='selected',cutoff=rows[-1]['id'],log_ids=['999999'],confirmation='DELETE').status_code==422


def test_gtu_register_all_blocks_rooms_and_excel_emergency(app,admin):
    location=upload_pdf(admin);assert post(admin,location,sessions='0').status_code==302
    eid=first_exam(app)['id']
    assert b'No approved allocations' in admin.get('/admin/block-classrooms').data
    assert b'SUB1' in admin.get('/admin/block-classrooms?include_drafts=yes').data
    assert action(admin,app,eid,'approve').status_code==302
    state=exam_state(app,eid)
    assert action(admin,app,eid,'emergency-seat',base_revision=state['draft_id'],confirmed='yes',sid='000009000001',target='G725/17').status_code==302
    report=admin.get(f'/admin/block-classrooms?exam_id={eid}')
    assert report.status_code==200 and b'SUB1' in report.data and b'SUB2' in report.data
    assert b'Emergency admissions' in report.data and b'725' in report.data
    assert b'000009000001' not in report.data.split(b'class="card top-space block-register"')[1]  # report table has no student list
    result=admin.get(f'/admin/block-classrooms?exam_id={eid}&download=xlsx')
    assert result.status_code==200
    ws=load_workbook(BytesIO(result.data)).active;rows=list(ws.iter_rows(min_row=2,values_only=True))
    assert len(rows)==3 and sum(r[8] for r in rows)==6
    assert {r[7] for r in rows}=={'721','725'}
    assert any(r[9]=='Emergency admission' for r in rows)
    assert ws['E2'].data_type=='s' and ws['E2'].number_format=='@'
    # Report uses the approved snapshot after the working exam metadata changes.
    with app.app_context():get_db().execute("UPDATE exams SET title='New working title' WHERE id=?",(eid,))
    assert b'Invented Examination' in admin.get(f'/admin/block-classrooms?exam_id={eid}').data
    assert app.test_client().get('/admin/block-classrooms').status_code==302
    assert app.test_client().get('/admin/block-classrooms?download=xlsx').status_code==302


def test_custom_register_reports_one_split_block_in_each_room(app,admin):
    eid,r1=seed(app,count=2,rows=1,columns=1)
    with app.app_context():
        db=get_db();r2=db.execute('INSERT INTO rooms(building,number,layout) VALUES(?,?,?)',('Other','002',json.dumps({'rows':1,'columns':1,'seats_per_bench':1,'seats':{}}))).lastrowid
        db.execute('INSERT INTO exam_rooms VALUES(?,?)',(eid,r2))
        db.execute("UPDATE students SET branch='SUB',batch='001' WHERE exam_id=?",(eid,))
        db.executemany('INSERT INTO gtu_students(exam_id,enrollment_no,exam_date,session,block_no,subject_code,subject_name,uploaded_at) VALUES(?,?,?,?,?,?,?,?)',[(eid,f'{i:05}','2099-01-01','morning','001','SUB','SUB',0) for i in range(2)])
    for endpoint in ('generate','approve'):assert action(admin,app,eid,endpoint).status_code==302
    result=admin.get(f'/admin/block-classrooms?exam_id={eid}&download=xlsx')
    rows=list(load_workbook(BytesIO(result.data)).active.iter_rows(min_row=2,values_only=True))
    assert len(rows)==2 and {r[4] for r in rows}=={'001'} and {r[7] for r in rows}=={'101','002'}
    assert admin.get('/admin/block-classrooms?exam_id=garbage').status_code==422
    assert admin.get('/admin/block-classrooms?exam_id=99999').status_code==404
