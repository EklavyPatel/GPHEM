"""Adapter around the supplied Astra engine; immutable revisions isolate approvals."""
import json
from flask import abort
from engine import Plan, Exam, Conflict
from .db import get_db, transaction, audit

MAX_SOLVER_PAIRS = 250000


def exam_or_404(exam_id):
    row = get_db().execute('SELECT * FROM exams WHERE id=?', (exam_id,)).fetchone()
    if row is None:
        abort(404, 'Examination not found.')
    return row


def revision(revision_id, exam_id):
    r = get_db().execute('SELECT * FROM revisions WHERE id=? AND exam_id=?', (revision_id, exam_id)).fetchone()
    if r is None:
        raise ValueError('Generate a draft allocation first.')
    return r


def decoded(row):
    return {k: json.loads(row[k]) for k in ('config', 'preview', 'metadata')}


def build_input(exam):
    if exam['mode'] == 'gtu':
        from .gtu_service import build_gtu_input
        return build_gtu_input(exam)
    db = get_db()
    roster = [dict(r) for r in db.execute('SELECT * FROM students WHERE exam_id=? ORDER BY sid', (exam['id'],))]
    rooms = [dict(r) for r in db.execute('SELECT r.* FROM rooms r JOIN exam_rooms er ON er.room_id=r.id WHERE er.exam_id=? ORDER BY r.id', (exam['id'],))]
    if not roster:
        raise ValueError('Import students before generating an allocation.')
    if not rooms:
        raise ValueError('Select at least one available classroom.')
    rules = json.loads(exam['rules'])
    engine_rooms, metadata_rooms = [], {}
    for room in rooms:
        layout = json.loads(room['layout'])
        key = f'R{room["id"]}'
        engine_rooms.append({'id': key, **{k:v for k,v in layout.items() if k != 'seats'}})
        metadata_rooms[key] = {**room, 'layout': layout}
        for local, status in layout['seats'].items():
            if status in ('blocked', 'reserved'):
                r, c, p = map(int, local.split('/'))
                rules.append({'id': f'physical-{key}-{local}', 'type': 'blocked',
                              'scope': {'room': key, 'row': r, 'column': c, 'position': p}})
    if sum(r['rows'] * r['columns'] * r['seats_per_bench'] for r in engine_rooms) > 10000:
        raise ValueError('Use at most 10,000 physical seats per examination.')
    config = {'version':1, 'seed':exam['seed'], 'rooms':engine_rooms,
              'students':[{k:p[k] for k in ('sid','branch','batch')} for p in roster], 'rules':rules}
    native={r['enrollment_no']:dict(r) for r in db.execute('SELECT * FROM gtu_students WHERE exam_id=?',(exam['id'],))}
    for person in roster:
        if person['sid'] in native:
            person.update(native[person['sid']])
    metadata = {'rooms':metadata_rooms, 'students':{p['sid']:p for p in roster},
                'exam': {k:exam[k] for k in ('id','title','starts_at','timezone','show_names','mode','source','historical','shift')}}
    source = db.execute('SELECT source_id FROM exam_pdf_sources WHERE exam_id=?',(exam['id'],)).fetchone()
    if source: metadata['source_pdf']=source['source_id']
    return config, metadata


def allocate_bounded(plan):
    # Preserve the supplied verified greedy path; prevent a dense MILP model exhausting a laptop.
    pairs = sum(len(v) for v in plan.domain.values())
    if pairs <= MAX_SOLVER_PAIRS:
        return plan.allocate(seconds=20)
    assignment = dict.fromkeys(plan.keys)
    assignment.update(plan.fixed)
    used = set(plan.fixed.values())
    for _, keys, ranks in plan.orders + [('remaining', plan.keys, plan.people)]:
        queue = [sid for sid in ranks if sid not in used]
        for key in keys:
            if key in plan.fixed or assignment[key] is not None:
                continue
            for i, sid in enumerate(queue):
                if sid in plan.domain[key]:
                    assignment[key] = queue.pop(i)
                    used.add(sid)
                    break
    try:
        return plan.preview(assignment, 'verified_greedy')
    except Conflict as exc:
        raise ValueError('This policy needs a solver model larger than the 250,000 candidate-pair safety limit. '
                         'Restrict branches to rooms/columns or simplify the policy. No allocation was changed. '
                         + str(exc)) from exc


def assert_version(exam, expected):
    if exam['version'] != expected:
        raise ValueError('This examination changed in another tab. Reload before saving.')


def verify_revision(config, preview):
    if config.get('mode') == 'gtu':
        from .gtu_engine import verify
        from .gtu_service import validate_receipts
        validate_receipts(config)
        verify(config, preview)
    else:
        plan = Plan(Exam.model_validate(config), preview)
        plan.verify({p['seat_id']:p['sid'] for p in preview['positions']})


def ensure_current(exam, data):
    """Compare actual inputs, including room versions; counters alone are insufficient."""
    config, metadata = build_input(exam)
    # Pins are explicit draft controls, not an alternative roster or room configuration.
    candidate={k:v for k,v in data['config'].items() if k not in ('pins','locks')}
    current={k:v for k,v in config.items() if k not in ('pins','locks')}
    if candidate != current or data['metadata'] != metadata:
        raise ValueError('Allocation inputs have changed. Generate a new draft using the current roster, rooms, rules and examination settings.')


def save_revision(exam_id, expected, config, preview, metadata, action):
    # Independently re-verify complete seat map before any persistence.
    verify_revision(config, preview)
    with transaction() as db:
        exam = exam_or_404(exam_id)
        assert_version(exam, expected)
        from .publication_service import configured_release
        release = None if metadata['exam'].get('historical') else configured_release(exam)
        rid = db.execute('INSERT INTO revisions(exam_id,input_version,config,preview,metadata,exam_info,release_at) VALUES(?,?,?,?,?,?,?)',
                         (exam_id, expected+1, json.dumps(config), json.dumps(preview), json.dumps(metadata), json.dumps(metadata['exam']),release)).lastrowid
        values = []
        for seat in preview['positions']:
            if seat['sid']:
                room = metadata['rooms'][seat['room']]
                student = metadata['students'][seat['sid']]
                if config.get('mode') == 'gtu':
                    payload = {**seat, 'mode':'gtu', 'name':student.get('name',''), 'year':student.get('year',''), 'building':room['floor'],
                               'floor':room['floor'], 'room_number':room['number'], 'row':None,'column':None,
                               'bench_number':None,'seat_position':seat['seat_number'], 'pdf_bench':student.get('pdf_bench')}
                    values.append((rid, seat['sid'], seat['seat_id'], json.dumps(payload)))
                    continue
                payload = {**seat, 'name':student['name'], 'year':student['year'],
                           'building':room['building'], 'room_number':room['number'],
                           'bench_number':(seat['row']-1)*room['layout']['columns']+seat['column']}
                for field in ('block_no','subject_code','subject_name','pdf_bench'):
                    if field in student:
                        payload[field]=student[field]
                values.append((rid, seat['sid'], seat['seat_id'], json.dumps(payload)))
        db.executemany('INSERT INTO assignments VALUES(?,?,?,?)', values)
        db.execute('UPDATE exams SET draft_id=?,version=version+1 WHERE id=?', (rid, exam_id))
        audit(action, f'exam={exam_id}, revision={rid}')
    return rid


def generate(exam_id, expected):
    # Read a consistent input snapshot, then release DB lock during computation.
    with transaction():
        exam = exam_or_404(exam_id)
        assert_version(exam, expected)
        config, metadata = build_input(exam)
        previous = None
        if exam['draft_id'] or exam['approved_id']:
            previous = decoded(revision(exam['draft_id'] or exam['approved_id'], exam_id))['preview']
    if config.get('mode') == 'gtu':
        from .gtu_engine import allocate
        preview = allocate(config)
    else:
        plan = Plan(Exam.model_validate(config), previous)
        preview = allocate_bounded(plan)
    return save_revision(exam_id, expected, config, preview, metadata, 'generate')


def edit_draft(exam_id, expected, operation, source=None, target=None):
    exam = exam_or_404(exam_id)
    assert_version(exam, expected)
    row = revision(exam['draft_id'], exam_id)
    if row['approved']:
        raise ValueError('Approved allocations are immutable. Create an editable copy first.')
    if row['input_version'] != expected:
        raise ValueError('Inputs changed since this draft. Regenerate before editing or approving.')
    data = decoded(row)
    ensure_current(exam, data)
    config, preview, metadata = data['config'], data['preview'], data['metadata']
    if config.get('mode')=='gtu':
        if operation not in ('move_block','swap_blocks','swap_rooms'):
            raise ValueError('GTU mode moves whole blocks or swaps room arrangements; individual seat swaps and locks would violate GTU ordering.')
        from .gtu_engine import edit_blocks
        preview=edit_blocks(config,preview,operation,source,target)
    elif operation == 'swap':
        preview = Plan(Exam.model_validate(config), preview).edit(preview, source, target)
    elif operation == 'lock':
        seats = {p['seat_id']:p for p in preview['positions']}
        if source not in seats:
            raise ValueError('Choose a valid seat.')
        if source in config.get('pins', {}) or config.get('locks'):
            raise ValueError('Remove configured pins/lock scopes before unlocking this seat.')
        seats[source]['locked'] = not seats[source]['locked']
    elif operation == 'regenerate':
        preview = allocate_bounded(Plan(Exam.model_validate(config), preview))
    else:
        raise ValueError('Unknown draft operation.')
    return save_revision(exam_id, expected, config, preview, metadata, operation)


def approve(exam_id, expected):
    with transaction() as db:
        exam = exam_or_404(exam_id)
        assert_version(exam, expected)
        row = revision(exam['draft_id'], exam_id)
        if row['input_version'] != expected or row['approved']:
            raise ValueError('Draft is stale or already approved. Generate or copy a draft first.')
        data = decoded(row)
        ensure_current(exam, data)
        verify_revision(data['config'], data['preview'])
        count = db.execute('SELECT count(*) FROM assignments WHERE revision_id=?', (row['id'],)).fetchone()[0]
        if count != len(data['config']['students']):
            raise ValueError('Stored assignments do not match the verified roster.')
        db.execute('UPDATE revisions SET approved=1 WHERE id=?', (row['id'],))
        db.execute('UPDATE exams SET approved_id=?,version=version+1 WHERE id=?', (row['id'], exam_id))
        if exam['auto_publish'] and not exam['historical']:
            db.execute("UPDATE exams SET published_id=?,publication='scheduled',publish_at=? WHERE id=?",(row['id'],row['release_at'],exam_id))
        audit('approve', f'exam={exam_id}, revision={row["id"]}')


def published_exams():
    from .publication_service import now_utc
    now=now_utc()
    return get_db().execute("""SELECT e.*,r.exam_info AS public_info FROM exams e JOIN revisions r ON e.published_id=r.id
        WHERE r.approved=1 AND e.historical=0 AND r.release_at IS NOT NULL
        AND COALESCE((SELECT o.release_at FROM publication_overrides o WHERE o.exam_id=e.id),r.release_at)<=?
        AND COALESCE(e.publish_at,r.release_at)<=? AND e.publication IN ('manual','scheduled')
        AND json_extract(r.exam_info,'$.starts_at')=e.starts_at
        AND json_extract(r.exam_info,'$.title')=e.title
        AND json_extract(r.exam_info,'$.timezone')=e.timezone
        AND json_extract(r.exam_info,'$.show_names')=e.show_names
        ORDER BY e.starts_at,e.id""",(now.isoformat(),now.isoformat())).fetchall()
