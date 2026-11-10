"""Authorized roster amendments, revision-safe PDF replacement and deletion."""
import io
import json
import secrets
import time
from flask import Blueprint,abort,flash,g,redirect,render_template,request,send_file,url_for
from services.db import get_db,transaction,audit,cleanup_pdf_storage
from services.security import admin_required
from services.allocation_service import exam_or_404,assert_version,revision,decoded
from services.amendment_service import text,student_record,insert_person,create_amended_draft
from services.pdf_service import read_pdf

bp=Blueprint('amendments',__name__)


def expected():
    try:return int(request.form.get('version',''))
    except ValueError:raise ValueError('Reload the form before saving.') from None


@bp.route('/admin/exams/<int:exam_id>/roster',methods=['GET','POST'])
@admin_required
def roster(exam_id):
    exam=exam_or_404(exam_id);db=get_db()
    if request.method=='POST':
        reason=text(request.form.get('reason',''),'Authorization / correction reason',500)
        person=student_record(exam,request.form)
        with transaction():
            exam=exam_or_404(exam_id);assert_version(exam,expected())
            original=request.form.get('original_sid','')
            if original:
                if not db.execute('SELECT 1 FROM students WHERE exam_id=? AND sid=?',(exam_id,original)).fetchone():
                    raise ValueError('The original student no longer exists. Reload the roster.')
                provenance=db.execute('SELECT pdf_bench,pdf_page FROM gtu_students WHERE exam_id=? AND enrollment_no=?',(exam_id,original)).fetchone()
                if provenance and person['sid']==original:
                    person.update(dict(provenance))
                db.execute('DELETE FROM emergency_seats WHERE exam_id=? AND sid=?',(exam_id,original))
                db.execute('DELETE FROM emergency_admissions WHERE exam_id=? AND sid=?',(exam_id,original))
                db.execute('DELETE FROM gtu_students WHERE exam_id=? AND enrollment_no=?',(exam_id,original))
                db.execute('DELETE FROM students WHERE exam_id=? AND sid=?',(exam_id,original))
            if db.execute('SELECT 1 FROM students WHERE exam_id=? AND sid=?',(exam_id,person['sid'])).fetchone():
                raise ValueError('This SID is already present in the examination.')
            insert_person(exam,person,reason)
            rid,moved=create_amended_draft(exam_id,expected(),request.form.get('repack')=='on')
            audit('emergency_or_correction',f'exam={exam_id}, original={original}, sid={person["sid"]}, reason={reason}')
        flash(f'Review draft #{rid}: {moved} existing students changed seats. Previous publication is preserved until approval and release.','success')
        return redirect(url_for('arrangement',exam_id=exam_id))
    sid=request.args.get('sid','')
    people=[dict(r) for r in db.execute('''SELECT s.*,g.block_no,g.subject_code,g.subject_name FROM students s LEFT JOIN gtu_students g
        ON g.exam_id=s.exam_id AND g.enrollment_no=s.sid WHERE s.exam_id=? ORDER BY s.sid''',(exam_id,))]
    person=next((p for p in people if p['sid']==sid),None)
    if sid and person is None:abort(404)
    return render_template('admin/roster.html',exam=exam,people=people,person=person)


@bp.route('/admin/exams/<int:exam_id>/revised-pdf',methods=['GET','POST'])
@admin_required
def correct_pdf(exam_id):
    exam=exam_or_404(exam_id)
    if exam['source']!='pdf':raise ValueError('Revised PDF replacement is available for PDF-imported sessions.')
    if request.method=='GET':return render_template('admin/revised_pdf.html',exam=exam,report=None)
    assert_version(exam,expected())
    reason=text(request.form.get('reason',''),'Official revision / late receipt authorization',500)
    upload=request.files.get('pdf')
    if not upload or not upload.filename.lower().endswith('.pdf'):raise ValueError('Choose a revised GTU .pdf file.')
    content=upload.read(5*1024*1024+1);report=read_pdf(content)
    matching=[s for s in report['sessions'] if s['exam_date']==exam['gtu_date'] and s['shift']==exam['shift']]
    if len(matching)!=1:raise ValueError('The revised PDF must include exactly this examination date and shift.')
    session=matching[0]
    token=secrets.token_urlsafe(24)
    payload={'exam_id':exam_id,'version':exam['version'],'session':session,'reason':reason,'received':time.time()}
    with transaction() as db:
        cleanup_pdf_storage()
        db.execute('INSERT INTO pdf_sources VALUES(?,?,?)',(token,content,payload['received']))
        db.execute('INSERT INTO pdf_imports VALUES(?,?,?,?)',(token,g.admin['id'],payload['received'],json.dumps(payload)))
    old={r[0] for r in get_db().execute('SELECT sid FROM students WHERE exam_id=?',(exam_id,))};new={r['sid'] for r in session['records']}
    return render_template('admin/revised_pdf.html',exam=exam,report=session,token=token,added=len(new-old),removed=len(old-new),reason=reason)


@bp.post('/admin/exams/<int:exam_id>/revised-pdf/<token>')
@admin_required
def confirm_pdf(exam_id,token):
    with transaction() as db:
        exam=exam_or_404(exam_id);assert_version(exam,expected())
        row=db.execute('SELECT * FROM pdf_imports WHERE id=? AND admin_id=? AND created>?',(token,g.admin['id'],time.time()-1800)).fetchone()
        if row is None:abort(404,'Preview expired; upload again.')
        data=json.loads(row['payload'])
        if data.get('exam_id')!=exam_id or data['version']!=exam['version']:raise ValueError('The examination changed after preview. Upload again.')
        db.execute('DELETE FROM emergency_seats WHERE exam_id=?',(exam_id,))
        db.execute('DELETE FROM emergency_admissions WHERE exam_id=?',(exam_id,))
        db.execute('DELETE FROM gtu_students WHERE exam_id=?',(exam_id,))
        db.execute('DELETE FROM students WHERE exam_id=?',(exam_id,))
        for p in data['session']['records']:
            insert_person(exam,{**p,'name':'','branch':p['subject_code'],'batch':p['block_no'],'year':''},data['reason'],data['received'])
        db.execute('INSERT INTO exam_pdf_sources VALUES(?,?) ON CONFLICT(exam_id) DO UPDATE SET source_id=excluded.source_id',(exam_id,token))
        rid,moved=create_amended_draft(exam_id,expected(),request.form.get('repack')=='on','revised_pdf')
        db.execute('DELETE FROM pdf_imports WHERE id=?',(token,))
        audit('revised_pdf_authorization',f'exam={exam_id}, reason={data["reason"]}')
    flash(f'Revised roster saved as draft #{rid}. {moved} existing students moved. Review and approve; the previous publication remains intact.','success')
    return redirect(url_for('arrangement',exam_id=exam_id))


@bp.get('/admin/exams/<int:exam_id>/filled-pdf')
@admin_required
def filled_pdf(exam_id):
    from services.pdf_export_service import fill_rooms
    exam=exam_or_404(exam_id)
    row=revision(request.args.get('revision',type=int) or exam['approved_id'] or exam['draft_id'],exam_id)
    data=decoded(row);source_id=data['metadata'].get('source_pdf')
    source=get_db().execute('SELECT content FROM pdf_sources WHERE id=?',(source_id,)).fetchone()
    if source is None:raise ValueError('The original PDF was not retained by the old app version. Upload it through Revised PDF, review the draft, then download again.')
    related=[]
    if request.args.get('scope')=='all':
        for other in get_db().execute('''SELECT r.* FROM exams e JOIN revisions r ON r.id=COALESCE(e.approved_id,e.draft_id)
            JOIN pdf_sources p ON p.id=json_extract(r.metadata,'$.source_pdf')
            WHERE e.id!=? AND e.mode=? AND p.content=(SELECT content FROM pdf_sources WHERE id=?)''',(exam_id,exam['mode'],source_id)):
            related.append((decoded(other),other['id'],bool(other['approved'])))
    result=fill_rooms(bytes(source['content']),data,row['id'],bool(row['approved']),related)
    return send_file(io.BytesIO(result),mimetype='application/pdf',as_attachment=True,download_name=f'GTU-exam-{exam_id}-revision-{row["id"]}-rooms.pdf')


@bp.post('/admin/exams/<int:exam_id>/delete')
@admin_required
def delete_exam(exam_id):
    with transaction() as db:
        exam=exam_or_404(exam_id);assert_version(exam,expected())
        if request.form.get('confirm_title')!=exam['title']:raise ValueError('Type the exact examination title to confirm deletion.')
        # Delete only this examination. Immutable snapshots of other sessions remain untouched.
        db.execute('DELETE FROM assignments WHERE revision_id IN (SELECT id FROM revisions WHERE exam_id=?)',(exam_id,))
        for table in ('emergency_seats','emergency_admissions','gtu_students','students','imports','generation_errors','exam_rooms','exam_pdf_sources','publication_overrides','revisions'):
            db.execute(f'DELETE FROM {table} WHERE exam_id=?',(exam_id,))
        db.execute('DELETE FROM exams WHERE id=?',(exam_id,))
        cleanup_pdf_storage()
        audit('delete_exam',f'exam={exam_id}, title={exam["title"]}; roster and revisions permanently deleted')
    flash('Examination deleted and student access removed.','success')
    return redirect(url_for('dashboard'))


@bp.post('/admin/exams/<int:exam_id>/emergency-seat')
@admin_required
def emergency_seat(exam_id):
    from services.amendment_service import place_emergency
    exam=exam_or_404(exam_id)
    if request.form.get('confirmed')!='yes':raise ValueError('Confirm the student and empty seat before saving.')
    try:base_id=int(request.form.get('base_revision',''))
    except ValueError:raise ValueError('Reload the visual arrangement before saving.') from None
    from services.amendment_service import emergency_record
    person=emergency_record(exam,request.form)
    reason=text(request.form.get('reason','') or 'Emergency admission confirmed on visual arrangement','Authorization reason',500)
    rid,approved,published=place_emergency(exam_id,expected(),base_id,person,text(request.form.get('target',''),'Target seat'),reason)
    status='Approved and student publication updated; the existing release time still applies.' if published else 'Approved arrangement updated; student access remains unchanged.' if approved else 'Draft updated; review and approve before publication.'
    flash(f'Student {person["sid"]} added to {request.form["target"]}. {status} Revision #{rid}.','success')
    return redirect(url_for('arrangement',exam_id=exam_id))
