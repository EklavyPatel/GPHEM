"""College examination seating allocation. Run `flask --app app create-admin` first."""
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import click
from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from pydantic import ValidationError
from engine import Conflict, Preset, Exam, Plan
from services.db import get_db, connect, init_db, close_db, transaction, audit
from services.security import SQLiteSessions, admin_required, csrf_protect, csrf_token, rotate_session, rate_limit
from services.excel_service import FIELDS, parse_students
from services.room_service import validate_layout, available
from services.gtu_service import settings_for, roster as gtu_roster, form_settings
from services.gtu_engine import room_sequence
from services.gtu_import_service import parse_gtu, check_deadline
from services.publication_service import release_at, configured_release
from services.allocation_service import (exam_or_404, revision, decoded, generate, edit_draft,
                                        approve, published_exams, assert_version, save_revision, ensure_current)
from services.export_service import allocation_report, validation_report, student_template, generation_error_report


def local_datetime(value, zone):
    try:
        tz = ZoneInfo(zone)
        value = datetime.fromisoformat(value)
        if value.tzinfo is not None:
            raise ValueError('Use local date and time without an offset.')
        aware = value.replace(tzinfo=tz)
        if aware.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != value:
            raise ValueError('This local time does not exist in the selected time zone.')
        if value.replace(tzinfo=tz, fold=0).utcoffset() != value.replace(tzinfo=tz, fold=1).utcoffset():
            raise ValueError('This local time is ambiguous. Choose a time outside the daylight-saving transition.')
        return aware.astimezone(timezone.utc).isoformat()
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise ValueError('Enter a valid date, time and IANA time zone, such as Asia/Kolkata.') from exc


def required(name, maximum=150):
    value = request.form.get(name, '').strip()
    if not value or len(value)>maximum or any(ord(c)<32 for c in value):
        raise ValueError(f'{name.replace("_", " ").title()} is required and must be at most {maximum} characters.')
    return value


def number(name):
    try:
        return int(request.form[name])
    except (KeyError, ValueError):
        raise ValueError(f'{name.replace("_", " ").title()} must be an integer.') from None


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(app.instance_path, 0o700)
    app.config.update(DATABASE=os.environ.get('SEATING_DATABASE',str(Path(app.instance_path)/'seating.sqlite')),
                      COLLEGE_NAME=os.environ.get('COLLEGE_NAME','GOVERNMENT POLYTECHNIC HIMMATNAGAR'), MAX_CONTENT_LENGTH=6*1024*1024,
                      MAX_FORM_MEMORY_SIZE=512*1024, SESSION_COOKIE_NAME='seating_session',
                      SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','0')=='1', SESSION_TTL=7200,
                      TRUSTED_HOSTS=os.environ.get('TRUSTED_HOSTS','').split(',') if os.environ.get('TRUSTED_HOSTS') else None)
    if test_config:
        app.config.update(test_config)
    database_path=Path(app.config['DATABASE']).expanduser().resolve()
    database_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    app.config['DATABASE']=str(database_path)
    init_db(app)
    os.chmod(app.config['DATABASE'], 0o600)
    app.session_interface = SQLiteSessions()
    app.teardown_appcontext(close_db)
    app.before_request(csrf_protect)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if app.config['SESSION_COOKIE_SECURE']:
            response.headers['Strict-Transport-Security']='max-age=31536000'
        if response.status_code==429:
            response.headers['Retry-After']='60'
        return response

    def publication_label(exam):
        if exam['historical']:
            return 'Historical — private'
        if 'visible_exam_ids' not in g:
            g.visible_exam_ids={row['id'] for row in published_exams()}
        if exam['id'] in g.visible_exam_ids:
            return 'Visible to students'
        return 'Student release scheduled' if exam['publication']!='off' else 'Private'

    @app.context_processor
    def shared():
        return {'csrf_token':csrf_token, 'college_name':app.config['COLLEGE_NAME'], 'available':available,
                'json_loads':json.loads, 'admin_user':getattr(g,'admin',None), 'publication_label':publication_label}

    @app.template_filter('localtime')
    def format_local(value, zone='Asia/Kolkata'):
        if not value:
            return 'Not scheduled'
        return datetime.fromisoformat(value).astimezone(ZoneInfo(zone)).strftime('%d %b %Y · %I:%M %p')

    @app.errorhandler(ValueError)
    @app.errorhandler(sqlite3.IntegrityError)
    def invalid(exc):
        message = str(exc)
        if isinstance(exc, ValidationError):
            message = '; '.join('.'.join(map(str,e['loc']))+': '+e['msg'] for e in exc.errors())
        if isinstance(exc, sqlite3.IntegrityError):
            message = 'This record duplicates an existing identifier or conflicts with saved data. No changes were saved.'
        return render_template('error.html', message=message, hint=getattr(exc,'hint',''), code=422),422

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return render_template('error.html',message=exc.description,code=exc.code),exc.code

    @app.errorhandler(500)
    def server_error(exc):
        return render_template('error.html',message='An unexpected error occurred. Your previously approved allocation is preserved.',code=500),500

    @app.get('/favicon.ico')
    def favicon():
        return redirect(url_for('static',filename='images/college-logo-original.jpg'))

    @app.get('/health')
    def health():
        get_db().execute('SELECT 1')
        return {'status':'ok'}

    @app.route('/',methods=['GET','POST'])
    def index():
        published = published_exams()
        exams = [{**dict(e), 'public':json.loads(e['public_info'])} for e in published]
        error = None
        if request.method=='POST':
            rate_limit('lookup-network',6000,60)
            rate_limit('lookup-client',60,60,session.token)
            sid = request.form.get('sid','')
            exam = next((e for e in exams if str(e['id'])==request.form.get('exam_id')),None)
            if len(sid)>100 or not sid or sid!=sid.strip():
                error='Enter your complete SID exactly as it appears on your college record.'
            elif exam:
                row = get_db().execute('SELECT payload FROM assignments WHERE revision_id=? AND sid=?',
                                       (exam['published_id'],sid)).fetchone()
                if row:
                    return render_template('result.html',seat=json.loads(row['payload']),exam=exam['public'])
                error='No published seat was found for that SID and examination. Check your details or contact the examination office.'
            else:
                error='Select an examination with published results.'
        return render_template('index.html',exams=exams,error=error)

    @app.route('/admin/login',methods=['GET','POST'])
    def login():
        ready = get_db().execute('SELECT 1 FROM admins LIMIT 1').fetchone() is not None
        if request.method=='POST':
            rate_limit('login-ip',10,300)
            username=request.form.get('username','')[:100]
            rate_limit('login-account',10,300,username.lower())
            row=get_db().execute('SELECT * FROM admins WHERE username=?',(username,)).fetchone()
            # Fixed valid hash prevents the absent-account path skipping password work.
            password=request.form.get('password','')[:1024]
            valid=check_password_hash(row['password_hash'] if row else app.config['DUMMY_HASH'],password)
            if row and valid:
                rotate_session()
                session['admin_id']=row['id']
                with transaction():
                    audit('login','Administrator signed in',row['id'])
                return redirect(url_for('dashboard'))
            flash('Incorrect username or password.','error')
        return render_template('admin/login.html',ready=ready)

    @app.post('/admin/logout')
    @admin_required
    def logout():
        with transaction():
            audit('logout','Administrator signed out')
        rotate_session()
        return redirect(url_for('login'))

    @app.get('/admin')
    @admin_required
    def dashboard():
        exams=[dict(e) for e in get_db().execute('''SELECT e.*,(SELECT count(*) FROM students WHERE exam_id=e.id) student_count,
            (SELECT count(*) FROM exam_rooms WHERE exam_id=e.id) room_count FROM exams e ORDER BY id DESC''')]
        for exam in exams:
            if exam['mode']=='gtu':
                exam['room_count']=len(room_sequence(settings_for(exam),json.loads(exam['gtu_disabled'])))
        rooms=get_db().execute('SELECT * FROM rooms ORDER BY building,number').fetchall()
        logs=get_db().execute('SELECT a.*,u.username FROM audit a LEFT JOIN admins u ON u.id=a.admin_id ORDER BY a.id DESC LIMIT 8').fetchall()
        return render_template('admin/dashboard.html',exams=exams,rooms=rooms,logs=logs,
                               student_count=get_db().execute('SELECT count(*) FROM students').fetchone()[0])

    @app.route('/admin/exams/new',methods=['GET','POST'])
    @admin_required
    def new_exam():
        if request.method=='POST':
            title=required('title'); zone=required('timezone')
            start=local_datetime(required('starts_at'),zone)
            mode=request.form.get('mode','seating')
            if mode not in ('seating','gtu'):
                raise ValueError('Choose GTU mode or Custom Mode.')
            shift=request.form.get('shift','') if mode=='gtu' else ''
            if mode=='gtu' and shift not in ('morning','afternoon'):
                raise ValueError('Choose the GTU morning or afternoon shift.')
            exam_date=datetime.fromisoformat(start).astimezone(ZoneInfo(zone)).date().isoformat() if mode=='gtu' else ''
            with transaction() as db:
                if mode=='gtu' and db.execute("SELECT 1 FROM exams WHERE mode='gtu' AND gtu_date=? AND shift=?",(exam_date,shift)).fetchone():
                    raise ValueError('A GTU examination already exists for this date and shift. Open that session to import its blocks.')
                eid=db.execute('INSERT INTO exams(title,starts_at,timezone,rules,mode,shift,gtu_date,gtu_config,auto_publish) VALUES(?,?,?,?,?,?,?,?,?)',
                               (title,start,zone,json.dumps([{'id':'sequential','type':'order','mode':'ascending_sid'}]) if mode=='seating' else '[]',
                                mode,shift,exam_date,json.dumps(settings_for()) if mode=='gtu' else '{}',int(request.form.get('auto_publish')=='on'))).lastrowid
                audit('create_exam',f'exam={eid}, mode={mode}, shift={shift}')
            return redirect(url_for('exam_detail',exam_id=eid))
        return render_template('admin/new_exam.html')

    @app.route('/admin/exams/<int:exam_id>',methods=['GET','POST'])
    @admin_required
    def exam_detail(exam_id):
        exam=exam_or_404(exam_id)
        if request.method=='POST':
            expected=number('version')
            title=required('title'); zone=required('timezone')
            start=local_datetime(required('starts_at'),zone)
            publish_at=local_datetime(request.form['publish_at'],zone) if request.form.get('publish_at') else release_at(start)
            if publish_at>start:
                raise ValueError('Student release time must be on or before the examination start.')
            selected=[int(i) for i in request.form.getlist('room_ids')]
            if len(set(selected))!=len(selected):
                raise ValueError('Duplicate classroom selections.')
            with transaction() as db:
                exam=exam_or_404(exam_id); assert_version(exam,expected)
                all_ids={r[0] for r in db.execute('SELECT id FROM rooms')}
                if not set(selected)<=all_ids:
                    raise ValueError('Unknown classroom selection.')
                if exam['mode']=='gtu' or exam['source']=='pdf':
                    new_date=datetime.fromisoformat(start).astimezone(ZoneInfo(zone)).date().isoformat()
                    shift=request.form.get('shift',exam['shift'])
                    if shift not in ('morning','afternoon'):
                        raise ValueError('GTU shift must be morning or afternoon.')
                    has_roster=db.execute('SELECT 1 FROM gtu_students WHERE exam_id=? LIMIT 1',(exam_id,)).fetchone()
                    if has_roster and (new_date!=exam['gtu_date'] or shift!=exam['shift'] or zone!=exam['timezone']):
                        raise ValueError('An imported GTU roster belongs to its date, shift and time zone. Create a new session to change these.')
                    db.execute('UPDATE exams SET shift=?,gtu_date=? WHERE id=?',(shift,new_date,exam_id))
                if request.form.get('publish_at'):
                    db.execute('INSERT OR REPLACE INTO publication_overrides VALUES(?,?)',(exam_id,publish_at))
                    audit('release_time_override',f'exam={exam_id}, release_at={publish_at}')
                else:
                    db.execute('DELETE FROM publication_overrides WHERE exam_id=?',(exam_id,))
                critical=(title!=exam['title'] or start!=exam['starts_at'] or zone!=exam['timezone'] or int(request.form.get('show_names')=='on')!=exam['show_names'])
                if critical or (exam['auto_publish'] and request.form.get('auto_publish')!='on'):
                    db.execute("UPDATE exams SET publication='off' WHERE id=?",(exam_id,))
                db.execute('UPDATE exams SET title=?,starts_at=?,timezone=?,publish_at=?,show_names=?,auto_publish=?,version=version+1 WHERE id=?',
                           (title,start,zone,publish_at,int(request.form.get('show_names')=='on'),int(request.form.get('auto_publish')=='on' and not exam['historical']),exam_id))
                db.execute('DELETE FROM exam_rooms WHERE exam_id=?',(exam_id,))
                db.executemany('INSERT INTO exam_rooms VALUES(?,?)',[(exam_id,r) for r in selected])
                audit('update_exam',f'exam={exam_id}')
            flash('Examination settings saved. Regenerate any draft to use the updated settings.','success')
            return redirect(url_for('exam_detail',exam_id=exam_id))
        rooms=get_db().execute('SELECT * FROM rooms ORDER BY building,number').fetchall()
        selected={r[0] for r in get_db().execute('SELECT room_id FROM exam_rooms WHERE exam_id=?',(exam_id,))}
        count=get_db().execute('SELECT count(*) FROM students WHERE exam_id=?',(exam_id,)).fetchone()[0]
        history=get_db().execute('SELECT id,approved,created FROM revisions WHERE exam_id=? ORDER BY id DESC LIMIT 20',(exam_id,)).fetchall()
        errors=get_db().execute('SELECT * FROM generation_errors WHERE exam_id=? ORDER BY id DESC LIMIT 5',(exam_id,)).fetchall()
        local_start=datetime.fromisoformat(exam['starts_at']).astimezone(ZoneInfo(exam['timezone'])).strftime('%Y-%m-%dT%H:%M')
        local_publish=datetime.fromisoformat(exam['publish_at']).astimezone(ZoneInfo(exam['timezone'])).strftime('%Y-%m-%dT%H:%M') if exam['publish_at'] else ''
        gtu_context={}
        if exam['mode']=='gtu':
            settings=settings_for(exam)
            active_rooms=room_sequence(settings,json.loads(exam['gtu_disabled']))
            gtu_context={'gtu_settings':settings,'gtu_rooms':active_rooms,'gtu_blocks':len({p['block_no'] for p in gtu_roster(exam_id)})}
        local_publish=datetime.fromisoformat(exam['publish_at'] or release_at(exam['starts_at'])).astimezone(ZoneInfo(exam['timezone'])).strftime('%Y-%m-%dT%H:%M')
        return render_template('admin/exam.html',exam=exam,rooms=rooms,selected=selected,count=count,**gtu_context,
                               history=history,errors=errors,local_start=local_start,local_publish=local_publish)

    @app.route('/admin/exams/<int:exam_id>/students',methods=['GET','POST'])
    @admin_required
    def students(exam_id):
        exam=exam_or_404(exam_id)
        if request.method=='POST' and exam['source']=='pdf':
            raise ValueError('This session retains the PDF source roster. Use Emergency admission / correct student records or Replace roster with revised PDF.')
        if request.method=='POST':
            assert_version(exam,number('version'))
            upload=request.files.get('workbook')
            if not upload or not upload.filename:
                raise ValueError('Choose a student .xlsx workbook.')
            received=time.time()
            if exam['mode']=='gtu':
                native_exam={**dict(exam),'disabled_rooms':json.loads(exam['gtu_disabled'])}
                records,errors=parse_gtu(upload.read(5*1024*1024+1),upload.filename,native_exam,settings_for(exam),gtu_roster(exam_id),received)
            else:
                mapping={k:request.form.get('map_'+k,v) for k,v in FIELDS.items()}
                existing=[r[0] for r in get_db().execute('SELECT sid FROM students WHERE exam_id=?',(exam_id,))]
                records,errors=parse_students(upload.read(5*1024*1024+1),upload.filename,exam_id,exam['title'],mapping,existing)
            token=secrets.token_urlsafe(24)
            with transaction() as db:
                db.execute('DELETE FROM imports WHERE created<?',(time.time()-1800,))
                db.execute('INSERT INTO imports VALUES(?,?,?,?,?,?,?)',
                           (token,exam_id,g.admin['id'],exam['version'],json.dumps(records),json.dumps(errors),received))
                audit('preview_import',f'exam={exam_id}, rows={len(records)}, errors={len(errors)}')
            return redirect(url_for('import_preview',exam_id=exam_id,token=token))
        roster=get_db().execute('SELECT * FROM students WHERE exam_id=? ORDER BY sid LIMIT 100',(exam_id,)).fetchall()
        count=get_db().execute('SELECT count(*) FROM students WHERE exam_id=?',(exam_id,)).fetchone()[0]
        if exam['mode']=='gtu' or exam['source']=='pdf':
            return render_template('admin/gtu_students.html',exam=exam,roster=gtu_roster(exam_id),count=count)
        return render_template('admin/students.html',exam=exam,roster=roster,count=count,fields=FIELDS)

    def get_import(exam_id,token):
        row=get_db().execute('SELECT * FROM imports WHERE id=? AND exam_id=? AND admin_id=? AND created>?',
                             (token,exam_id,g.admin['id'],time.time()-1800)).fetchone()
        if row is None:
            abort(404,'Import preview expired or does not belong to this administrator.')
        return row

    @app.route('/admin/exams/<int:exam_id>/imports/<token>',methods=['GET','POST'])
    @admin_required
    def import_preview(exam_id,token):
        row=get_import(exam_id,token)
        records,errors=json.loads(row['records']),json.loads(row['errors'])
        if request.method=='POST':
            if errors:
                raise ValueError('Fix every validation error and upload again. No invalid records can be imported.')
            with transaction() as db:
                exam=exam_or_404(exam_id); assert_version(exam,row['version'])
                if exam['mode']=='gtu':
                    check_deadline(exam['gtu_date'],exam['timezone'],row['created'])
                    existing=gtu_roster(exam_id)
                    if {p['block_no'] for p in records}&{p['block_no'] for p in existing}:
                        raise ValueError('A GTU block was already imported. No block may be extended or split between files.')
                    db.executemany('INSERT INTO students VALUES(?,?,?,?,?,?)',[(exam_id,r['sid'],'','','','') for r in records])
                    db.executemany('INSERT INTO gtu_students(exam_id,enrollment_no,exam_date,session,block_no,subject_code,subject_name,uploaded_at) VALUES(?,?,?,?,?,?,?,?)',
                                   [(exam_id,r['sid'],r['exam_date'],r['session'],r['block_no'],r['subject_code'],r['subject_name'],row['created']) for r in records])
                else:
                    db.executemany('INSERT INTO students VALUES(?,?,?,?,?,?)',
                                   [(exam_id,r['sid'],r['name'],r['branch'],r['batch'],r['year']) for r in records])
                db.execute('UPDATE exams SET version=version+1 WHERE id=?',(exam_id,))
                db.execute('DELETE FROM imports WHERE id=?',(token,))
                audit('confirm_import',f'exam={exam_id}, students={len(records)}')
            flash(f'Imported {len(records):,} students.','success')
            return redirect(url_for('students',exam_id=exam_id))
        exam=exam_or_404(exam_id)
        return render_template('admin/gtu_import.html' if exam['mode']=='gtu' else 'admin/import.html',exam=exam,records=records,errors=errors,token=token)

    @app.get('/admin/exams/<int:exam_id>/imports/<token>/report')
    @admin_required
    def import_report(exam_id,token):
        row=get_import(exam_id,token)
        return send_file(validation_report(json.loads(row['records']),json.loads(row['errors']),gtu=exam_or_404(exam_id)['mode']=='gtu'),
                         as_attachment=True,download_name='import-validation.xlsx')

    @app.get('/admin/template.xlsx')
    @admin_required
    def template_download():
        title='Example Examination'
        if request.args.get('exam_id'):
            exam=exam_or_404(int(request.args['exam_id']))
            if exam['mode']=='gtu' or exam['source']=='pdf':
                from services.gtu_export_service import gtu_template
                return send_file(gtu_template(exam),as_attachment=True,download_name='gtu-block-template.xlsx')
            title=exam['title']
        return send_file(student_template(title),as_attachment=True,download_name='student-template.xlsx')

    @app.get('/admin/rooms')
    @admin_required
    def rooms():
        return render_template('admin/rooms.html',rooms=get_db().execute('SELECT * FROM rooms ORDER BY building,number').fetchall())

    @app.route('/admin/rooms/new',methods=['GET','POST'],defaults={'room_id':None})
    @app.route('/admin/rooms/<int:room_id>',methods=['GET','POST'])
    @admin_required
    def room_edit(room_id):
        room=get_db().execute('SELECT * FROM rooms WHERE id=?',(room_id,)).fetchone() if room_id else None
        if room_id and room is None:
            abort(404)
        layout=json.loads(room['layout']) if room else {'rows':5,'columns':4,'seats_per_bench':1,'seats':{}}
        if request.method=='POST':
            building=required('building'); room_number=required('number')
            layout=validate_layout(json.loads(request.form.get('layout','{}')))
            with transaction() as db:
                if room_id:
                    changed=db.execute('UPDATE rooms SET building=?,number=?,layout=?,version=version+1 WHERE id=? AND version=?',
                                       (building,room_number,json.dumps(layout),room_id,number('version'))).rowcount
                    if not changed:
                        raise ValueError('This classroom changed in another tab. Reload before saving.')
                    db.execute('UPDATE exams SET version=version+1 WHERE id IN (SELECT exam_id FROM exam_rooms WHERE room_id=?)',(room_id,))
                else:
                    room_id=db.execute('INSERT INTO rooms(building,number,layout) VALUES(?,?,?)',
                                       (building,room_number,json.dumps(layout))).lastrowid
                audit('save_room',f'room={room_id}')
            flash('Classroom layout saved.','success')
            return redirect(url_for('rooms'))
        return render_template('admin/room_edit.html',room=room,layout=layout)

    def gtu_configuration(exam=None):
        defaults=get_db().execute('SELECT * FROM gtu_settings WHERE id=1').fetchone()
        settings=settings_for(exam)
        if request.method=='POST':
            settings=form_settings(request.form)
            disabled=request.form.getlist('disabled_rooms') if exam is not None else []
            room_sequence(settings,disabled)
            with transaction() as db:
                if exam is not None:
                    assert_version(exam_or_404(exam['id']),number('version'))
                    db.execute('UPDATE exams SET gtu_config=?,gtu_disabled=?,version=version+1 WHERE id=?',
                               (json.dumps(settings),json.dumps(disabled),exam['id']))
                    audit('gtu_session_rules',f'exam={exam["id"]}, disabled={disabled}')
                else:
                    changed=db.execute('UPDATE gtu_settings SET config=?,version=version+1 WHERE id=1 AND version=?',
                                       (json.dumps(settings),number('version'))).rowcount
                    if not changed:raise ValueError('GTU defaults changed in another tab. Reload before saving.')
                    audit('gtu_defaults','Updated GTU floor order and room limits')
            flash('GTU configuration saved. Existing approved/published snapshots are preserved.','success')
            return redirect(url_for('rules',exam_id=exam['id']) if exam is not None else url_for('gtu_settings'))
        return render_template('admin/gtu_settings.html',exam=exam,settings=settings,
                               disabled=json.loads(exam['gtu_disabled']) if exam is not None else [],
                               settings_version=exam['version'] if exam is not None else defaults['version'],
                               sequence=room_sequence(settings))

    @app.route('/admin/gtu-settings',methods=['GET','POST'])
    @admin_required
    def gtu_settings():
        return gtu_configuration()

    @app.route('/admin/exams/<int:exam_id>/rules',methods=['GET','POST'])
    @admin_required
    def rules(exam_id):
        exam=exam_or_404(exam_id)
        if exam['mode']=='gtu':
            return gtu_configuration(exam)
        if request.method=='POST':
            policy=Preset.model_validate({'version':1,'rules':json.loads(request.form.get('rules','[]'))})
            if len(policy.rules)>250 or any(r.id.startswith('physical-') for r in policy.rules):
                raise ValueError('Use at most 250 rules and avoid the reserved physical- ID prefix.')
            if len({r.id for r in policy.rules})!=len(policy.rules):
                raise ValueError('Every rule must have a unique ID.')
            seed=number('seed')
            if not -(2**31)<=seed<2**31:
                raise ValueError('Seed must be a 32-bit integer.')
            preset_name=request.form.get('preset_name','').strip()
            with transaction() as db:
                assert_version(exam_or_404(exam_id),number('version'))
                db.execute('UPDATE exams SET rules=?,seed=?,version=version+1 WHERE id=?',
                           (json.dumps([r.model_dump(exclude_none=True) for r in policy.rules]),seed,exam_id))
                if preset_name:
                    if len(preset_name)>100:
                        raise ValueError('Preset name is too long.')
                    db.execute('INSERT INTO presets(name,rules) VALUES(?,?)',(preset_name,json.dumps(json.loads(request.form['rules']))))
                audit('save_rules',f'exam={exam_id}, rules={len(policy.rules)}')
            flash('Rules validated and saved. Generation will check feasibility against the roster and rooms.','success')
            return redirect(url_for('rules',exam_id=exam_id))
        selected=get_db().execute('SELECT r.* FROM rooms r JOIN exam_rooms er ON er.room_id=r.id WHERE er.exam_id=?',(exam_id,)).fetchall()
        branches=[r[0] for r in get_db().execute('SELECT DISTINCT branch FROM students WHERE exam_id=? ORDER BY branch',(exam_id,))]
        presets=[dict(r) for r in get_db().execute('SELECT * FROM presets ORDER BY name')]
        return render_template('admin/rules.html',exam=exam,rooms=selected,branches=branches,presets=presets)

    @app.post('/admin/exams/<int:exam_id>/generate')
    @admin_required
    def generate_allocation(exam_id):
        try:
            generate(exam_id,number('version'))
        except (ValueError,ValidationError) as exc:
            with transaction() as db:
                db.execute('INSERT INTO generation_errors(exam_id,message) VALUES(?,?)',(exam_id,str(exc)[:4000]))
                audit('generation_failed',f'exam={exam_id}: {str(exc)[:500]}')
            raise
        flash('Draft generated and all hard constraints verified. Review before approval.','success')
        return redirect(url_for('chart',exam_id=exam_id))

    @app.get('/admin/exams/<int:exam_id>/chart')
    @admin_required
    def chart(exam_id):
        exam=exam_or_404(exam_id)
        rid=request.args.get('revision',type=int) or exam['draft_id'] or exam['approved_id']
        row=revision(rid,exam_id)
        data=decoded(row)
        rooms=data['metadata']['rooms']
        room_id=request.args.get('room') or next(iter(rooms))
        if room_id not in rooms:
            abort(404,'Classroom not in this allocation snapshot.')
        seats=[p for p in data['preview']['positions'] if p['room']==room_id]
        if data['config'].get('mode')=='gtu':
            used={p['room'] for p in data['preview']['positions'] if p['sid']}
            return render_template('admin/gtu_chart.html',exam=exam,revision=row,data=data,rooms=rooms,
                                   room_id=room_id,room=rooms[room_id],seats=seats,used_rooms=len(used),
                                   total_students=len(data['config']['students']),
                                   can_approve=not row['approved'] and row['id']==exam['draft_id'] and row['input_version']==exam['version'])
        grid={p['seat_id']:p for p in seats}
        editable=not row['approved'] and row['id']==exam['draft_id'] and row['input_version']==exam['version']
        return render_template('admin/chart.html',exam=exam,revision=row,data=data,rooms=rooms,
                               room_id=room_id,room=rooms[room_id],grid=grid,editable=editable)

    @app.get('/admin/exams/<int:exam_id>/arrangement')
    @admin_required
    def arrangement(exam_id):
        exam=exam_or_404(exam_id)
        row=revision(request.args.get('revision',type=int) or exam['draft_id'] or exam['approved_id'],exam_id)
        data=decoded(row)
        editable=not row['approved'] and row['id']==exam['draft_id'] and row['input_version']==exam['version']
        mode='gtu' if data['config'].get('mode')=='gtu' else 'seating'
        groups={key:[] for key in data['metadata']['rooms']}
        for seat in data['preview']['positions']:
            person=data['metadata']['students'].get(seat['sid'],{})
            groups[seat['room']].append({**seat,'block_no':seat.get('block_no') or person.get('block_no',''),
                                       'subject_code':seat.get('subject_code') or person.get('subject_code',''),
                                       'pdf_bench':person.get('pdf_bench')})
        board_editable=row['id']==exam['draft_id'] and (row['approved'] or row['input_version']==exam['version'])
        if board_editable:
            try:ensure_current(exam,data)
            except ValueError:board_editable=False
        return render_template('admin/arrangement.html',exam=exam,revision=row,data=data,mode=mode,groups=groups,editable=editable and board_editable,board_editable=board_editable)

    @app.post('/admin/exams/<int:exam_id>/edit')
    @admin_required
    def edit_allocation(exam_id):
        expected=number('version')
        if request.form.get('view')=='arrangement':
            with transaction():
                exam=exam_or_404(exam_id);assert_version(exam,expected)
                row=revision(exam['draft_id'],exam_id)
                if request.form.get('base_revision') and number('base_revision')!=row['id']:
                    raise ValueError('The arrangement changed. Reload before moving blocks or rooms.')
                if row['approved']:
                    if not request.form.get('base_revision'):
                        raise ValueError('Reload Visual arrangement before editing an approved allocation.')
                    data=decoded(row);ensure_current(exam,data)
                    save_revision(exam_id,expected,data['config'],data['preview'],data['metadata'],'copy_for_board_edit')
                    expected+=1
                edit_draft(exam_id,expected,required('operation'),request.form.get('source'),request.form.get('target'))
        else:
            edit_draft(exam_id,expected,required('operation'),request.form.get('source'),request.form.get('target'))
        flash('Move saved in a validated draft. Review and approve it to update the approved arrangement; the previous publication is preserved.','success')
        return redirect(url_for('arrangement',exam_id=exam_id)) if request.form.get('view')=='arrangement' else redirect(url_for('chart',exam_id=exam_id,room=request.form.get('room')))

    @app.post('/admin/exams/<int:exam_id>/copy')
    @admin_required
    def copy_approved(exam_id):
        exam=exam_or_404(exam_id); expected=number('version'); assert_version(exam,expected)
        data=decoded(revision(exam['approved_id'],exam_id))
        ensure_current(exam,data)
        # An explicit copy is editable but retains protected seats until explicitly unlocked.
        save_revision(exam_id,expected,data['config'],data['preview'],data['metadata'],'copy_approved')
        flash('Approved snapshot copied into an editable draft. Its original approval and publication are preserved.','success')
        return redirect(url_for('chart',exam_id=exam_id))

    @app.post('/admin/exams/<int:exam_id>/approve')
    @admin_required
    def approve_allocation(exam_id):
        approve(exam_id,number('version'))
        flash('Allocation approved. Automatic release, when enabled, uses the configured release time. Historical sessions stay private.','success')
        return redirect(url_for('exam_detail',exam_id=exam_id))

    @app.post('/admin/exams/<int:exam_id>/publication')
    @admin_required
    def publication(exam_id):
        action=required('action')
        if action not in ('publish','schedule','unpublish'):
            raise ValueError('Unknown publication action.')
        with transaction() as db:
            exam=exam_or_404(exam_id); assert_version(exam,number('version'))
            if action=='unpublish':
                db.execute("UPDATE exams SET publication='off',version=version+1 WHERE id=?",(exam_id,))
            else:
                approved=revision(exam['approved_id'],exam_id)
                ensure_current(exam,decoded(approved))
                if not approved['approved']:
                    raise ValueError('Only an approved allocation can be published.')
                if exam['historical'] or not approved['release_at']:
                    raise ValueError('Historical/rehearsal sessions are private and cannot be published.')
                db.execute("UPDATE exams SET published_id=?,publication='scheduled',publish_at=?,version=version+1 WHERE id=?",
                           (approved['id'],configured_release(exam),exam_id))
            audit(action,f'exam={exam_id}, revision={exam["approved_id"]}')
        flash({'publish':'Approved allocation armed for the configured release time.','schedule':'Approved allocation scheduled for the configured release time.',
               'unpublish':'Student access disabled.'}[action],'success')
        return redirect(url_for('exam_detail',exam_id=exam_id))

    @app.get('/admin/exams/<int:exam_id>/export')
    @admin_required
    def export(exam_id):
        exam=exam_or_404(exam_id)
        rid=request.args.get('revision',type=int) or exam['approved_id'] or exam['draft_id']
        row=revision(rid,exam_id)
        with transaction():
            audit('export',f'exam={exam_id}, revision={rid}')
        return send_file(allocation_report(row),as_attachment=True,download_name=f'exam-{exam_id}-revision-{rid}.xlsx')

    @app.get('/admin/exams/<int:exam_id>/errors.xlsx')
    @admin_required
    def error_report(exam_id):
        exam_or_404(exam_id)
        with transaction():
            audit('export_validation_errors', f'exam={exam_id}')
        return send_file(generation_error_report(exam_id), as_attachment=True,
                         download_name=f'exam-{exam_id}-validation-errors.xlsx')

    @app.get('/admin/audit')
    @admin_required
    def audit_page():
        logs=get_db().execute('SELECT a.*,u.username FROM audit a LEFT JOIN admins u ON u.id=a.admin_id ORDER BY a.id DESC LIMIT 500').fetchall()
        return render_template('admin/audit.html',logs=logs,log_cutoff=max((r['id'] for r in logs),default=0))

    @app.get('/admin/backup')
    @admin_required
    def backup():
        with transaction():
            audit('backup','Full SQLite snapshot downloaded')
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'backup.sqlite')
            dest=sqlite3.connect(path)
            try:
                get_db().backup(dest)
            finally:
                dest.close()
            data=Path(path).read_bytes()
        return send_file(io.BytesIO(data),as_attachment=True,download_name='seating-backup.sqlite',mimetype='application/octet-stream')

    @app.cli.command('create-admin')
    @click.option('--username',prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(username,password):
        """Create a local administrator interactively. There are no default credentials."""
        if not username.strip() or len(username)>100 or len(password)<12 or len(password)>1024:
            raise click.ClickException('Use a username up to 100 characters and a password of 12–1024 characters.')
        try:
            with transaction() as db:
                uid=db.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)',
                               (username.strip(),generate_password_hash(password))).lastrowid
                db.execute('INSERT INTO audit(admin_id,action,detail) VALUES(?,?,?)',(uid,'create_admin','Local CLI setup'))
        except sqlite3.IntegrityError:
            raise click.ClickException('That administrator username already exists.') from None
        click.echo('Administrator created. Sign in at /admin/login.')

    @app.cli.command('reset-password')
    @click.option('--username',prompt=True)
    @click.password_option(confirmation_prompt=True)
    def reset_password(username,password):
        """Local recovery; revokes all browser sessions."""
        if len(password)<12 or len(password)>1024:
            raise click.ClickException('Password must have 12–1024 characters.')
        with transaction() as db:
            row=db.execute('SELECT id FROM admins WHERE username=?',(username,)).fetchone()
            if not row:
                raise click.ClickException('Administrator not found.')
            db.execute('UPDATE admins SET password_hash=? WHERE id=?',(generate_password_hash(password),row['id']))
            db.execute('DELETE FROM web_sessions')
            db.execute('INSERT INTO audit(admin_id,action,detail) VALUES(?,?,?)',(row['id'],'reset_password','Local CLI; all sessions revoked'))
        click.echo('Password updated; all browser sessions revoked.')

    @app.cli.command('seed-demo')
    def seed_demo():
        """Create an unpublished example session and a reusable room. No administrator is created."""
        demo=json.loads((Path(__file__).parent/'engine/example.json').read_text())
        with transaction() as db:
            if db.execute('SELECT 1 FROM exams LIMIT 1').fetchone():
                raise click.ClickException('Demo seeding requires a database without examinations.')
            layout={'rows':5,'columns':3,'seats_per_bench':1,'seats':{'5/3/1':'blocked','5/2/1':'accessible','5/1/1':'reserved'}}
            room=db.execute('INSERT INTO rooms(building,number,layout) VALUES(?,?,?)',('Main Building','A101',json.dumps(layout))).lastrowid
            rules=demo['rules']
            eid=db.execute('INSERT INTO exams(title,starts_at,timezone,rules) VALUES(?,?,?,?)',
                           ('Semester Examination — Demo','2026-12-15T04:00:00+00:00','Asia/Kolkata',json.dumps(rules))).lastrowid
            db.execute('INSERT INTO exam_rooms VALUES(?,?)',(eid,room))
            db.executemany('INSERT INTO students VALUES(?,?,?,?,?,?)',
                           [(eid,p['sid'],f'Example Student {i}',p['branch'],p['batch'],'2') for i,p in enumerate(demo['students'],1)])
            db.execute("INSERT INTO audit(action,detail) VALUES('seed_demo','Unpublished sample data created')")
        click.echo('Unpublished demo created. Generate, review, approve and publish it through /admin.')

    from web.pdf_routes import create_blueprint
    app.register_blueprint(create_blueprint(local_datetime))
    from web.amendment_routes import bp as amendments_bp
    app.register_blueprint(amendments_bp)
    from web.report_routes import bp as reports_bp
    app.register_blueprint(reports_bp)

    app.config['DUMMY_HASH']=generate_password_hash(secrets.token_urlsafe(32))
    return app


app=create_app()

if __name__=='__main__':
    app.run(host='127.0.0.1',port=5000,debug=False)
