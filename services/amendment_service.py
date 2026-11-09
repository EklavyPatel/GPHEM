"""Reviewed roster changes; the old publication remains an immutable snapshot."""
import json
import re
import time
from flask import g
from engine import Exam, Plan
from .db import get_db, transaction, audit
from .allocation_service import (exam_or_404, assert_version, build_input, revision, decoded,
                                  allocate_bounded, save_revision)


def text(value, label, maximum=100, optional=False):
    if not isinstance(value,str) or value!=value.strip() or len(value)>maximum or any(ord(c)<32 for c in value) or (not optional and not value):
        raise ValueError(f'{label}: enter valid text without surrounding spaces (maximum {maximum} characters).')
    return value


def student_record(exam, form):
    sid=text(form.get('sid',''),'SID')
    if exam['mode']=='gtu' or exam['source']=='pdf':
        if exam['source']=='pdf' and not re.fullmatch(r'\d{8,25}',sid):
            raise ValueError('GTU enrollment must contain 8–25 digits, including any leading zeros.')
        block=text(form.get('block_no',''),'Official block number')
        subject=text(form.get('subject_code',''),'Subject code')
        subject_name=text(form.get('subject_name','') or subject,'Subject name',250)
        return {'sid':sid,'name':'','branch':subject,'batch':block,'year':'',
                'block_no':block,'subject_code':subject,'subject_name':subject_name,
                'exam_date':exam['gtu_date'],'session':exam['shift'],'pdf_bench':None,'pdf_page':None}
    return {key:text(form.get(key,''),key.replace('_',' ').title(),150,optional=key=='year')
            for key in ('sid','name','branch','batch','year')}


def emergency_record(exam, form):
    """Direct emergency admission requires no official block membership."""
    person={key:text(form.get(key,''),key.title(),100 if key=='sid' else 150,optional=key!='sid')
            for key in ('sid','name','branch','batch','year')}
    person['branch']=person['branch'] or 'Emergency'
    person['batch']=person['batch'] or 'Emergency'
    if exam['mode']=='gtu' or exam['source']=='pdf':
        if exam['source']=='pdf' and not re.fullmatch(r'\d{8,25}',person['sid']):
            raise ValueError('GTU enrollment must contain 8–25 digits, including leading zeros.')
        subject=text(form.get('subject_code',''),'Subject code',100,optional=True) or 'EMERGENCY'
        person.update(block_no='EMERGENCY:'+person['sid'],subject_code=subject,
                      subject_name=text(form.get('subject_name',''),'Subject name',250,optional=True) or subject,
                      exam_date=exam['gtu_date'],session=exam['shift'],pdf_bench=None,pdf_page=None)
    return person


def authorize(exam_id, sid, reason, received=None):
    db=get_db()
    db.execute('INSERT OR REPLACE INTO emergency_admissions VALUES(?,?,?,?,?)',
               (exam_id,sid,reason,g.admin['id'],received if received is not None else time.time()))


def insert_person(exam, person, reason, received=None):
    db=get_db();eid=exam['id'];received=time.time() if received is None else received
    db.execute('INSERT INTO students VALUES(?,?,?,?,?,?)',(eid,person['sid'],person['name'],person['branch'],person['batch'],person['year']))
    if 'block_no' in person:
        db.execute('''INSERT INTO gtu_students(exam_id,enrollment_no,exam_date,session,block_no,subject_code,subject_name,uploaded_at,pdf_bench,pdf_page)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',(eid,person['sid'],person['exam_date'],person['session'],person['block_no'],person['subject_code'],person['subject_name'],received,person.get('pdf_bench'),person.get('pdf_page')))
    authorize(eid,person['sid'],reason,received)


def revised_preview(config, previous, repack=False):
    if config.get('mode')=='gtu':
        from .gtu_engine import allocate, grouped_blocks, room_sequence, verify, regular_input
        if repack or previous is None:
            return allocate(config)
        fixed=config.get('emergency_seats',{})
        settings,blocks=grouped_blocks(regular_input(config) if fixed else config)
        rooms=room_sequence(settings,config.get('disabled_rooms',[]));groups={r['id']:[] for r in rooms}
        old={p['seat_id']:p for p in previous['positions']}
        reserved=set(fixed.values())
        limits={r['id']:min([int(key.rsplit('/',1)[1])-1 for key in reserved if key.rsplit('/',1)[0]==r['id']]+[settings['room_capacity']]) for r in rooms}
        for p in sorted(previous['positions'],key=lambda p:p.get('seat_number',0)):
            if p.get('sid') and p['block_no'] in blocks:
                if p['room'] not in groups:
                    raise ValueError('A previously used room is unavailable. Enable repacking to review new room assignments.')
                if p['block_no'] not in groups[p['room']]:groups[p['room']].append(p['block_no'])
        assigned={b for bs in groups.values() for b in bs}
        for block in blocks.values():
            if block['id'] in assigned:continue
            for r in rooms:
                bs=groups[r['id']]
                if (sum(len(blocks[b]['students']) for b in bs)+len(block['students'])<=limits[r['id']]
                    and len(bs)<settings['max_blocks_per_room'] and all(blocks[b]['subject']!=block['subject'] for b in bs)):
                    bs.append(block['id']);break
            else:raise ValueError('No compatible room for this block. Review capacity or explicitly allow repacking.')
        positions=[]
        for room in rooms:
            people=[p for b in groups[room['id']] for p in blocks[b]['students']]
            if len(people)>settings['room_capacity']:
                raise ValueError(f'Room {room["number"]} cannot accommodate the revised block. Enable repacking or add capacity.')
            for n in range(1,settings['room_capacity']+1):
                person=people[n-1] if n<=len(people) else None
                key=f'{room["id"]}/{n}'
                if key in reserved:
                    if person:raise ValueError('The revised block would overlap a confirmed emergency seat. Nothing was changed.')
                    import copy
                    positions.append(copy.deepcopy(old[key]));continue
                positions.append({'seat_id':f'{room["id"]}/{n}','room':room['id'],'seat_number':n,
                    'sid':person['sid'] if person else None,**{k:person[k] if person else None for k in ('block_no','subject_code','subject_name')},'locked':False,'blocked':False})
        preview={'version':1,'mode':'gtu','method':'reviewed_roster_amendment','positions':positions}
        if previous.get('manual_room_selection') is True:
            preview['manual_room_selection']=True
        try:verify(config,preview)
        except ValueError as exc:
            raise ValueError(f'{exc} Enable repacking if existing rooms must change; nothing has been saved.') from exc
        return preview
    working=dict(config)
    if previous is not None and not repack:
        ids={p['sid'] for p in config['students']}
        working['pins']={p['seat_id']:p['sid'] for p in previous['positions'] if p.get('sid') in ids}
    result=allocate_bounded(Plan(Exam.model_validate(working),previous))
    if previous is not None and not repack:
        locks={p['sid']:p.get('locked',False) for p in previous['positions'] if p.get('sid')}
        for seat in result['positions']:
            seat['locked']=locks.get(seat.get('sid'),False)
    return result


def create_amended_draft(exam_id, expected, repack=False, action='roster_amendment'):
    # Caller holds the transaction: failed generation rolls back the roster too.
    exam=exam_or_404(exam_id);assert_version(exam,expected)
    previous=None
    if exam['draft_id'] or exam['approved_id']:
        previous=decoded(revision(exam['draft_id'] or exam['approved_id'],exam_id))['preview']
    config,metadata=build_input(exam)
    preview=revised_preview(config,previous,repack)
    rid=save_revision(exam_id,expected,config,preview,metadata,action)
    before={p['sid']:p['seat_id'] for p in (previous or {}).get('positions',[]) if p.get('sid')}
    changed=sum(p['sid'] in before and before[p['sid']]!=p['seat_id'] for p in preview['positions'] if p.get('sid'))
    audit(action,f'exam={exam_id}, revision={rid}, existing students moved={changed}, repack={repack}')
    return rid,changed


def place_emergency(exam_id, expected, base_id, person, target, reason):
    """Confirm one exact placement, preserving every existing occupant and release state."""
    import copy
    from .allocation_service import ensure_current, approve, verify_revision
    with transaction() as db:
        exam=exam_or_404(exam_id);assert_version(exam,expected)
        if base_id!=exam['draft_id']:
            raise ValueError('This is not the latest arrangement. Reload Visual arrangement before adding a student.')
        base=revision(base_id,exam_id);data=decoded(base)
        ensure_current(exam,data)
        preview=copy.deepcopy(data['preview'])
        seat=next((p for p in preview['positions'] if p['seat_id']==target),None)
        if seat is None or seat.get('sid') is not None or seat.get('blocked') or seat.get('locked'):
            raise ValueError('Choose an empty, available, unlocked seat. No student was added.')
        if db.execute('SELECT 1 FROM students WHERE exam_id=? AND sid=?',(exam_id,person['sid'])).fetchone():
            raise ValueError('This SID is already present in the examination.')
        insert_person(exam,person,reason)
        if exam['mode']=='gtu':
            db.execute('INSERT INTO emergency_seats VALUES(?,?,?)',(exam_id,person['sid'],target))
        config,metadata=build_input(exam)
        seat['sid']=person['sid']
        if exam['mode']=='gtu':
            seat.update({k:person[k] for k in ('block_no','subject_code','subject_name')})
            seat['emergency']=True
            preview['method']='gtu_direct_emergency_placement'
        else:
            assignment={p['seat_id']:p['sid'] for p in preview['positions']}
            preview=Plan(Exam.model_validate(config),data['preview']).preview(assignment,'emergency_exact_placement')
        next(p for p in preview['positions'] if p['seat_id']==target)['emergency']=True
        try:
            verify_revision(config,preview)
        except ValueError as exc:
            raise ValueError(f'This seat cannot be used under the current rules: {exc} Choose another seat or use the reviewed roster workflow. Nothing was changed.') from exc
        original={p['seat_id']:p['sid'] for p in data['preview']['positions']}
        if any(p['sid']!=original[p['seat_id']] for p in preview['positions'] if p['seat_id']!=target):
            raise ValueError('Emergency placement must preserve every existing assignment.')
        rid=save_revision(exam_id,expected,config,preview,metadata,'emergency_seat_placement')
        if base['approved']:
            approve(exam_id,expected+1)
            # Confirmation updates the stage of this arrangement, without arming a private
            # result or changing its release time simply because auto_publish is enabled.
            published=rid if exam['published_id']==base_id else exam['published_id']
            db.execute('UPDATE exams SET published_id=?,publication=?,publish_at=? WHERE id=?',
                       (published,exam['publication'],exam['publish_at'],exam_id))
        audit('emergency_placement_confirmed',f'exam={exam_id}, base={base_id}, revision={rid}, sid={person["sid"]}, seat={target}, approved={bool(base["approved"])}, published_updated={exam["published_id"]==base_id}, direct emergency policy applied, reason={reason}')
        return rid,bool(base['approved']),exam['published_id']==base_id and exam['publication']!='off'
