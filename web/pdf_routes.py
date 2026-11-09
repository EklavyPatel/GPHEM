"""Preview-first, atomic multi-session PDF import and automatic draft generation."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import json
import secrets
import time
from flask import Blueprint,abort,flash,g,redirect,render_template,request,url_for
from services.db import get_db,transaction,audit,cleanup_pdf_storage
from services.security import admin_required
from services.pdf_service import read_pdf,tools_available
from services.gtu_service import settings_for
from services.gtu_engine import pack
from services.gtu_import_service import check_deadline
from services.room_service import available
from services.allocation_service import generate


def create_blueprint(time_parser):
    bp=Blueprint('pdf_admin',__name__)

    @bp.route('/admin/pdf',methods=['GET','POST'])
    @admin_required
    def upload_pdf():
        rooms=get_db().execute('SELECT * FROM rooms ORDER BY building,number').fetchall()
        if request.method=='GET':
            return render_template('admin/pdf_upload.html',rooms=rooms,pdf_available=tools_available())
        upload=request.files.get('pdf')
        if not upload or not upload.filename or not upload.filename.lower().endswith('.pdf'):
            raise ValueError('Choose the original GTU block-arrangement .pdf file.')
        mode=request.form.get('mode','gtu')
        if mode not in ('gtu','seating'):raise ValueError('Choose GTU mode or Custom Mode.')
        zone=request.form.get('timezone','Asia/Kolkata')
        time_parser('2099-01-01T09:30',zone)  # validate the IANA zone before processing a file
        received=time.time()
        content=upload.read(5*1024*1024+1)
        report=read_pdf(content)
        chosen=request.form.getlist('room_ids') if mode=='seating' else []
        selected=[dict(r) for r in rooms if str(r['id']) in chosen]
        if mode=='seating' and (not selected or len(chosen)!=len(set(chosen)) or len(selected)!=len(set(chosen))):
            raise ValueError('Custom Mode needs participating classrooms. Configure their physical layouts, then select them before uploading.')
        settings=settings_for()
        today=datetime.fromtimestamp(received,timezone.utc).astimezone(ZoneInfo(zone)).date().isoformat()
        for session in report['sessions']:
            session['historical']=session['exam_date']<today
            session['errors']=[]
            session['clock']=request.form.get(session['shift']+'_time','09:30' if session['shift']=='morning' else '14:30')
            time_parser(session['exam_date']+'T'+session['clock'],zone)
            if not session['historical'] and mode=='gtu':
                try:check_deadline(session['exam_date'],zone,received)
                except ValueError as exc:session['errors'].append(str(exc))
            if mode=='gtu':
                existing=get_db().execute("SELECT id FROM exams WHERE mode='gtu' AND gtu_date=? AND shift=?",(session['exam_date'],session['shift'])).fetchone()
                if existing:
                    session['existing_id']=existing['id']
                    session['errors'].append(f'GTU session already exists as examination #{existing["id"]}. Use its Revised PDF action to replace the roster with review.')
                try:pack({'settings':settings,'students':session['records'],'disabled_rooms':[]})
                except ValueError as exc:session['errors'].append(str(exc))
            elif len(session['records'])>sum(available(json.loads(r['layout'])) for r in selected):
                session['errors'].append('Selected Custom Mode classrooms have insufficient usable seats for this session.')
        report.update(mode=mode,timezone=zone,received=received,settings=settings,
                      rooms=[{'id':r['id'],'version':r['version']} for r in selected],
                      auto_publish=request.form.get('auto_publish')=='on')
        token=secrets.token_urlsafe(24)
        with transaction() as db:
            cleanup_pdf_storage()
            db.execute('INSERT INTO pdf_sources VALUES(?,?,?)',(token,content,received))
            db.execute('INSERT INTO pdf_imports VALUES(?,?,?,?)',(token,g.admin['id'],received,json.dumps(report)))
            audit('pdf_preview',f'{report["pages"]} pages, {report["blocks"]} blocks, {len(report["sessions"])} sessions; mode={mode}')
        return redirect(url_for('pdf_admin.preview_pdf',token=token))

    @bp.route('/admin/pdf/<token>',methods=['GET','POST'])
    @admin_required
    def preview_pdf(token):
        row=get_db().execute('SELECT * FROM pdf_imports WHERE id=? AND admin_id=? AND created>?',
                             (token,g.admin['id'],time.time()-1800)).fetchone()
        if row is None:abort(404,'This private PDF preview expired. Upload the PDF again.')
        report=json.loads(row['payload'])
        if 'sessions' not in report:abort(404,'Use this examination’s revised PDF confirmation page.')
        if request.method=='GET':return render_template('admin/pdf_preview.html',report=report,token=token)
        try:indices=[int(v) for v in request.form.getlist('sessions')]
        except ValueError as exc:raise ValueError('Choose valid PDF sessions.') from exc
        if not indices or len(indices)!=len(set(indices)) or any(i<0 or i>=len(report['sessions']) for i in indices):
            raise ValueError('Select at least one distinct session from the preview.')
        created=[]
        with transaction() as db:
            # Reject replay/concurrent confirmation, and stale physical room definitions.
            if not db.execute('SELECT 1 FROM pdf_imports WHERE id=?',(token,)).fetchone():
                raise ValueError('This PDF preview was already confirmed.')
            for room in report['rooms']:
                actual=db.execute('SELECT version FROM rooms WHERE id=?',(room['id'],)).fetchone()
                if actual is None or actual['version']!=room['version']:
                    raise ValueError('A selected classroom changed after PDF preview. Upload again to recalculate capacity.')
            for index in indices:
                session=report['sessions'][index]
                if session['errors']:raise ValueError('Resolve the selected session errors before importing.')
                clock=request.form.get(f'time_{index}',session['clock'])
                starts_at=time_parser(session['exam_date']+'T'+clock,report['timezone'])
                if not session['historical'] and report['mode']=='gtu':
                    check_deadline(session['exam_date'],report['timezone'],report['received'])
                if report['mode']=='gtu' and db.execute("SELECT 1 FROM exams WHERE mode='gtu' AND gtu_date=? AND shift=?",(session['exam_date'],session['shift'])).fetchone():
                    raise ValueError('A selected GTU date/shift was created in another tab. Existing data was preserved.')
                eid=db.execute('''INSERT INTO exams(title,starts_at,timezone,rules,mode,shift,gtu_date,gtu_config,source,historical,auto_publish)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(report['title'],starts_at,report['timezone'],'[]',report['mode'],session['shift'],session['exam_date'],
                    json.dumps(report['settings']),'pdf',int(session['historical']),int(report['auto_publish'] and not session['historical']))).lastrowid
                db.executemany('INSERT INTO students VALUES(?,?,?,?,?,?)',
                               [(eid,r['sid'],'',r['subject_code'],r['block_no'],'') for r in session['records']])
                db.executemany('''INSERT INTO gtu_students(exam_id,enrollment_no,exam_date,session,block_no,subject_code,subject_name,uploaded_at,pdf_bench,pdf_page)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',[(eid,r['sid'],r['exam_date'],r['session'],r['block_no'],r['subject_code'],r['subject_name'],
                    report['received'],r['pdf_bench'],r['pdf_page']) for r in session['records']])
                db.executemany('INSERT INTO exam_rooms VALUES(?,?)',[(eid,r['id']) for r in report['rooms']])
                db.execute('INSERT INTO exam_pdf_sources VALUES(?,?)',(eid,token))
                created.append(eid)
                audit('pdf_import',f'exam={eid}, date={session["exam_date"]}, shift={session["shift"]}, historical={session["historical"]}')
            db.execute('DELETE FROM pdf_imports WHERE id=?',(token,))
        failures=0
        for eid in created:
            try:generate(eid,1)
            except ValueError as exc:
                failures+=1
                with transaction() as db:
                    db.execute('INSERT INTO generation_errors(exam_id,message) VALUES(?,?)',(eid,str(exc)[:4000]))
                    audit('generation_failed',f'exam={eid}: {str(exc)[:500]}')
        flash(f'Imported {len(created)} PDF sessions and generated {len(created)-failures} arrangements. '
              +('Some drafts need attention; see their generation errors. ' if failures else '')
              +'Review and approve before automatic 24-hour release. Historical sessions remain private.','success' if not failures else 'error')
        return redirect(url_for('dashboard'))
    return bp
