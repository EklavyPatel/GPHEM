"""Administrative consolidated allocation register and deliberate audit cleanup."""
from flask import Blueprint,flash,redirect,render_template,request,send_file,url_for
from services.db import get_db,transaction,audit
from services.security import admin_required
from services.allocation_service import exam_or_404
from services.block_report_service import register,workbook

bp=Blueprint('reports',__name__)


@bp.get('/admin/block-classrooms')
@admin_required
def block_classrooms():
    value=request.args.get('exam_id','')
    try:exam_id=int(value) if value else None
    except ValueError:raise ValueError('Choose a valid examination.') from None
    if exam_id is not None:exam_or_404(exam_id)
    include=request.args.get('include_drafts')=='yes'
    rows=register(exam_id,include)
    if request.args.get('download')=='xlsx':
        with transaction():audit('export_block_register',f'exam={exam_id or "all"}, rows={len(rows)}, include_drafts={include}')
        return send_file(workbook(rows),as_attachment=True,download_name='block-classroom-register.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    exams=get_db().execute('SELECT id,title,starts_at FROM exams ORDER BY starts_at DESC,id DESC').fetchall()
    return render_template('admin/block_classrooms.html',rows=rows,exams=exams,selected_exam=exam_id,include_drafts=include,
                           total_students=sum(r['count'] for r in rows),room_count=len({(r['exam_id'],r['room'],r['building']) for r in rows}))


@bp.post('/admin/audit/delete')
@admin_required
def delete_logs():
    if request.form.get('confirmation')!='DELETE':raise ValueError('Type DELETE to confirm log deletion.')
    scope=request.form.get('scope')
    if scope not in ('selected','all'):raise ValueError('Choose selected events or all events shown at page load.')
    try:cutoff=int(request.form.get('cutoff',''))
    except ValueError:raise ValueError('Reload the activity log before deleting events.') from None
    with transaction() as db:
        maximum=db.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0]
        if not 0<=cutoff<=maximum:raise ValueError('The log changed. Reload before deleting.')
        if scope=='selected':
            try:ids=[int(v) for v in request.form.getlist('log_ids')]
            except ValueError:raise ValueError('Select valid log events.') from None
            if not ids or len(ids)>500 or len(set(ids))!=len(ids) or any(i<1 or i>cutoff for i in ids):
                raise ValueError('Select up to 500 distinct events from this page.')
            existing={r[0] for r in db.execute('SELECT id FROM audit WHERE id<=?',(cutoff,))}
            if not set(ids)<=existing:raise ValueError('Some selected events were already removed. Reload the log.')
            count=len(ids)
        else:
            count=db.execute('SELECT count(*) FROM audit WHERE id<=?',(cutoff,)).fetchone()[0]
        # Insert first so the deletion marker receives a new ID above the cutoff,
        # even when every old event is removed (SQLite otherwise reuses row IDs).
        audit('delete_audit_logs',f'deleted={count}, scope={scope}, through event={cutoff}; concurrent newer events preserved')
        if scope=='selected':
            db.executemany('DELETE FROM audit WHERE id=?',[(i,) for i in ids])
        else:
            db.execute('DELETE FROM audit WHERE id<=?',(cutoff,))
    flash(f'Deleted {count} log events. A new deletion event records this action.','success')
    return redirect(url_for('audit_page'))
