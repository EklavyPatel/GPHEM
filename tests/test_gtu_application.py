from io import BytesIO
import json
from pathlib import Path
import sqlite3
import pytest
from openpyxl import load_workbook
from app import create_app
from services.db import get_db
from services.gtu_engine import DEFAULT_CONFIG
from .conftest import post,action,exam_state,release_window
from .test_gtu_import import csv_data,rows_for,EXAM


def create_gtu(admin,shift='morning',date='2099-11-09'):
    response=post(admin,'/admin/exams/new',title='GTU Winter Examination',mode='gtu',shift=shift,
                  starts_at=date+'T09:30',timezone='Asia/Kolkata')
    assert response.status_code==302,response.data
    return int(response.location.rstrip('/').split('/')[-1])


def upload(admin,app,eid,rows=None):
    response=action(admin,app,eid,'students',workbook=(BytesIO(csv_data(rows or rows_for([13,17]))),'gtu.csv'))
    assert response.status_code==302,response.data
    return response.location


def settings_form(settings=None,**extra):
    config=settings or DEFAULT_CONFIG
    return {'room_capacity':config['room_capacity'],'max_blocks_per_room':config['max_blocks_per_room'],
            'floor_order':[str(f['order']) for f in config['floors']],
            'floor_name':[f['name'] for f in config['floors']],
            'floor_rooms':[','.join(f['rooms']) for f in config['floors']],**extra}


def test_gtu_entire_form_workflow_and_reports(app,admin):
    eid=create_gtu(admin)
    release_window(app,eid)
    assert exam_state(app,eid)['mode']=='gtu'
    for page in ['', '/students','/rules']:
        response=admin.get(f'/admin/exams/{eid}{page}')
        assert response.status_code==200,response.data
    assert admin.get('/admin/gtu-settings').status_code==200
    template=load_workbook(BytesIO(admin.get(f'/admin/template.xlsx?exam_id={eid}').data))
    assert template.active['A2'].value=='2099-11-09' and template.active['F2'].value=='001'
    preview=upload(admin,app,eid)
    assert b'passed validation' in admin.get(preview).data
    assert admin.get(preview+'/report').status_code==200
    assert post(admin,preview).status_code==302
    assert action(admin,app,eid,'generate').status_code==302
    chart=admin.get(f'/admin/exams/{eid}/chart')
    assert chart.status_code==200 and b'GTU Examination' in chart.data and b'Room 721' in chart.data
    assert b'Swap selected seats' not in chart.data
    with app.app_context():
        assignments=[json.loads(r[0]) for r in get_db().execute('SELECT payload FROM assignments')]
        assert len(assignments)==30 and {p['room_number'] for p in assignments}=={'721'}
        first=min(assignments,key=lambda p:p['seat_number'])
        assert first['block_no']=='001' and first['seat_number']==1
        assert first['row'] is None and first['column'] is None
    assert action(admin,app,eid,'edit',operation='swap',source='G721/1',target='G721/2').status_code==422
    public=app.test_client()
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='000000').data
    assert action(admin,app,eid,'approve').status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    ticket=post(public,'/',exam_id=eid,sid='000000')
    assert ticket.status_code==200 and b'Seat confirmed' in ticket.data and b'000000' in ticket.data
    assert b'GTU block' in ticket.data and b'Subject 0' in ticket.data and b'Ground Floor' in ticket.data
    assert b'Bench number' not in ticket.data
    report=admin.get(f'/admin/exams/{eid}/export');assert report.status_code==200
    book=load_workbook(BytesIO(report.data))
    assert {'Room-wise list','Block-wise list','Attendance G721','Session summary','Allocation validation'}<=set(book.sheetnames)
    assert book['Room-wise list']['G2'].value=='001000' and book['Room-wise list']['G2'].data_type=='s'
    summary=dict(book['Session summary'].iter_rows(min_row=2,values_only=True))
    assert summary['Rooms used']==1 and summary['Students']==30 and summary['Vacant seats in used rooms']==0
    assert action(admin,app,eid,'publication',action='unpublish').status_code==302
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='000000').data


def test_date_shift_unique_and_rooms_reused(app,admin):
    morning=create_gtu(admin)
    duplicate=post(admin,'/admin/exams/new',title='Duplicate',mode='gtu',shift='morning',starts_at='2099-11-09T10:30',timezone='Asia/Kolkata')
    assert duplicate.status_code==422
    afternoon=create_gtu(admin,'afternoon')
    for eid,shift in [(morning,'morning'),(afternoon,'afternoon')]:
        rows=rows_for([1]);rows[0][1]=shift
        location=upload(admin,app,eid,rows)
        assert post(admin,location).status_code==302
        assert action(admin,app,eid,'generate').status_code==302
        with app.app_context():
            rid=exam_state(app,eid)['draft_id']
            p=json.loads(get_db().execute('SELECT payload FROM assignments WHERE revision_id=?',(rid,)).fetchone()[0])
            assert p['room_number']=='721'
    assert action(admin,app,morning,'rules',**settings_form(disabled_rooms=['721'])).status_code==302
    assert action(admin,app,morning,'generate').status_code==302
    assert b'Room 722' in admin.get(f'/admin/exams/{morning}/chart?room=G722').data
    assert exam_state(app,afternoon)['gtu_disabled']=='[]'


def test_deadline_blocks_preview_and_backend_confirmation(app,admin):
    eid=create_gtu(admin,date='2000-01-01')
    rows=rows_for([1]);rows[0][0]='2000-01-01'
    location=upload(admin,app,eid,rows)
    assert b'D' in admin.get(location).data and b'Import blocked' in admin.get(location).data
    assert post(admin,location).status_code==422
    assert action(admin,app,eid,'generate').status_code==422
    with app.app_context():assert get_db().execute('SELECT count(*) FROM gtu_students').fetchone()[0]==0


def test_no_extending_blocks_and_no_reassigning_roster_session(app,admin):
    eid=create_gtu(admin)
    location=upload(admin,app,eid,rows_for([1]));assert post(admin,location).status_code==302
    rows=rows_for([1]);rows[0][5]='NEW'
    location=upload(admin,app,eid,rows)
    assert b'already imported' in admin.get(location).data and post(admin,location).status_code==422
    changed=post(admin,f'/admin/exams/{eid}',version=exam_state(app,eid)['version'],title='GTU',
                 starts_at='2099-11-10T09:30',timezone='Asia/Kolkata',shift='morning')
    assert changed.status_code==422 and exam_state(app,eid)['gtu_date']=='2099-11-09'


def test_defaults_only_affect_new_sessions_and_stale_drafts(app,admin):
    eid=create_gtu(admin)
    modified=json.loads(json.dumps(DEFAULT_CONFIG));modified['floors'][0]['rooms']=['799']
    assert post(admin,'/admin/gtu-settings',version=1,**settings_form(modified)).status_code==302
    assert json.loads(exam_state(app,eid)['gtu_config'])['floors'][0]['rooms'][0]=='721'
    second=create_gtu(admin,'afternoon')
    assert json.loads(exam_state(app,second)['gtu_config'])['floors'][0]['rooms']==['799']
    assert post(admin,'/admin/gtu-settings',version=1,**settings_form()).status_code==422
    location=upload(admin,app,eid,rows_for([1]));assert post(admin,location).status_code==302
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'rules',**settings_form(disabled_rooms=['721'])).status_code==302
    assert action(admin,app,eid,'approve').status_code==422


def test_failed_gtu_generation_preserves_approved_and_published(app,admin):
    eid=create_gtu(admin)
    release_window(app,eid)
    location=upload(admin,app,eid);assert post(admin,location).status_code==302
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    before=exam_state(app,eid)
    all_rooms=[r for f in DEFAULT_CONFIG['floors'] for r in f['rooms']]
    assert action(admin,app,eid,'rules',**settings_form(disabled_rooms=all_rooms)).status_code==302
    assert action(admin,app,eid,'generate').status_code==422
    after=exam_state(app,eid)
    assert after['approved_id']==before['approved_id'] and after['published_id']==before['published_id']
    assert b'Seat confirmed' in post(app.test_client(),'/',exam_id=eid,sid='000000').data


def test_gtu_pages_require_admin(client):
    assert client.get('/admin/gtu-settings').status_code==302


def test_v1_migration_backup_and_preservation(tmp_path):
    path=tmp_path/'old.sqlite';db=sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE exams(id INTEGER PRIMARY KEY,title TEXT NOT NULL,starts_at TEXT NOT NULL,timezone TEXT NOT NULL,
      show_names INTEGER NOT NULL DEFAULT 0,rules TEXT NOT NULL DEFAULT '[]',seed INTEGER NOT NULL DEFAULT 42,
      version INTEGER NOT NULL DEFAULT 1,draft_id INTEGER,approved_id INTEGER,published_id INTEGER,
      publication TEXT NOT NULL DEFAULT 'off',publish_at TEXT);
    CREATE TABLE revisions(id INTEGER PRIMARY KEY,exam_id INTEGER NOT NULL,input_version INTEGER NOT NULL,
      config TEXT NOT NULL,preview TEXT NOT NULL,metadata TEXT NOT NULL,exam_info TEXT NOT NULL,
      approved INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    INSERT INTO exams(id,title,starts_at,timezone,approved_id,published_id,publication)
      VALUES(1,'Existing Approved Exam','2026-12-15T04:00:00+00:00','Asia/Kolkata',7,7,'manual');
    INSERT INTO revisions(id,exam_id,input_version,config,preview,metadata,exam_info,approved)
      VALUES(7,1,1,'{"original":true}','{"sealed":true}','{}','{}',1);
    PRAGMA user_version=1;
    ''')
    db.commit();db.close()
    upgraded=create_app({'TESTING':True,'DATABASE':str(path)})
    with upgraded.app_context():
        db=get_db();exam=dict(db.execute('SELECT * FROM exams WHERE id=1').fetchone())
        assert exam['mode']=='seating' and exam['approved_id']==7 and exam['published_id']==7
        assert db.execute('SELECT preview FROM revisions WHERE id=7').fetchone()[0]=='{"sealed":true}'
        assert db.execute('PRAGMA user_version').fetchone()[0]==5
    backups=list(tmp_path.glob('old-before-gtu-*.sqlite'));assert len(backups)==1
    backup=sqlite3.connect(backups[0]);assert backup.execute('PRAGMA user_version').fetchone()[0]==1;backup.close()
    create_app({'TESTING':True,'DATABASE':str(path)})
    assert len(list(tmp_path.glob('old-before-gtu-*.sqlite')))==1


@pytest.mark.parametrize('operation',['swap','lock','regenerate'])
def test_gtu_rejects_student_level_operations(app,admin,operation):
    eid=create_gtu(admin);location=upload(admin,app,eid,rows_for([1]))
    assert post(admin,location).status_code==302
    assert action(admin,app,eid,'generate').status_code==302
    state=exam_state(app,eid)
    assert action(admin,app,eid,'edit',operation=operation,source='G721/1',target='G721/2').status_code==422
    assert exam_state(app,eid)['draft_id']==state['draft_id']
    assert action(admin,app,eid,'rules',rules='[]',seed=42).status_code==422


def test_gtu_scheduled_publication(app,admin):
    from datetime import datetime,timedelta,timezone
    eid=create_gtu(admin);location=upload(admin,app,eid,rows_for([1]))
    assert post(admin,location).status_code==302
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    with app.app_context():get_db().execute('UPDATE exams SET publish_at=? WHERE id=?',((datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),eid))
    release_window(app,eid,-1)
    assert action(admin,app,eid,'publication',action='schedule').status_code==302
    public=app.test_client()
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='000000').data
    with app.app_context():get_db().execute('UPDATE exams SET publish_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),eid))
    release_window(app,eid)
    assert b'Seat confirmed' in post(public,'/',exam_id=eid,sid='000000').data
