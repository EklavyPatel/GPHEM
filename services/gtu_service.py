"""GTU persistence adapter; room pools are independent for each date/shift."""
import json
from .db import get_db
from .gtu_engine import validate_config,room_sequence
from .gtu_import_service import check_deadline


def settings_for(exam=None):
    if exam is not None and exam['mode']=='gtu':
        return validate_config(json.loads(exam['gtu_config']))
    row=get_db().execute('SELECT config FROM gtu_settings WHERE id=1').fetchone()
    return validate_config(json.loads(row['config']))


def roster(exam_id):
    people=[dict(r) for r in get_db().execute('SELECT * FROM gtu_students WHERE exam_id=? ORDER BY block_no,enrollment_no',(exam_id,))]
    exceptions={r['sid']:dict(r) for r in get_db().execute('SELECT * FROM emergency_admissions WHERE exam_id=?',(exam_id,))}
    for person in people:
        if person['enrollment_no'] in exceptions:
            person['emergency_admission']=exceptions[person['enrollment_no']]
    return people


def build_gtu_input(exam):
    settings=settings_for(exam)
    disabled=json.loads(exam['gtu_disabled'])
    people=[{**p,'sid':p['enrollment_no']} for p in roster(exam['id'])]
    if not people:
        raise ValueError('Upload complete, subject-wise GTU blocks on or before D−1 before generating rooms.')
    config={'version':1,'mode':'gtu','settings':settings,'disabled_rooms':disabled,'students':people,
            'exam_date':exam['gtu_date'],'shift':exam['shift'],'timezone':exam['timezone'], 'historical':bool(exam['historical'])}
    fixed={r['sid']:r['seat_id'] for r in get_db().execute('SELECT sid,seat_id FROM emergency_seats WHERE exam_id=?',(exam['id'],))}
    if fixed:config['emergency_seats']=fixed
    identities={r['sid']:dict(r) for r in get_db().execute('SELECT * FROM students WHERE exam_id=?',(exam['id'],))}
    validate_receipts(config)
    metadata={'rooms':{r['id']:r for r in room_sequence(settings,disabled)},
              'students':{p['sid']:{**p,**{k:identities[p['sid']][k] if p['sid'] in fixed else '' for k in ('name','branch','batch','year')}} for p in people},
              'exam':{k:exam[k] for k in ('id','title','starts_at','timezone','show_names','mode','shift','gtu_date','source','historical')}}
    source=get_db().execute('SELECT source_id FROM exam_pdf_sources WHERE exam_id=?',(exam['id'],)).fetchone()
    if source:metadata['source_pdf']=source['source_id']
    return config,metadata


def validate_receipts(config):
    for p in config['students']:
        if p['exam_date']!=config['exam_date'] or p['session']!=config['shift'] or p['sid']!=p['enrollment_no']:
            raise ValueError('GTU snapshot contains a student from a different date/shift or enrollment identity.')
        exception=p.get('emergency_admission')
        if exception and (not exception.get('reason','').strip() or not exception.get('admin_id') or exception.get('sid')!=p['sid']):
            raise ValueError('Invalid emergency admission authorization.')
        if not config.get('historical',False) and not exception:
            check_deadline(config['exam_date'],config['timezone'],p['uploaded_at'])


def form_settings(form):
    orders=form.getlist('floor_order');names=form.getlist('floor_name');rooms=form.getlist('floor_rooms')
    if not (len(orders)==len(names)==len(rooms)):
        raise ValueError('Each floor needs an order, name and room list.')
    try:
        config={'room_capacity':int(form.get('room_capacity','')),
                'max_blocks_per_room':int(form.get('max_blocks_per_room','')),
                'floors':[{'order':int(order),'name':name,'rooms':[n.strip() for n in numbers.split(',')]}
                          for order,name,numbers in zip(orders,names,rooms)]}
    except ValueError as exc:
        raise ValueError('Room capacity, maximum blocks and floor orders must be integers.') from exc
    return validate_config(config)
