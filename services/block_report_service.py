"""Consolidated, snapshot-based block/classroom register without student lists."""
from collections import defaultdict
from .db import get_db
from .allocation_service import decoded,verify_revision
from .export_service import sheet,finish
from openpyxl import Workbook


def register(exam_id=None,include_drafts=False):
    exams=get_db().execute('SELECT * FROM exams ORDER BY starts_at,id').fetchall()
    rows=[]
    for exam in exams:
        if exam_id is not None and exam['id']!=exam_id:continue
        rid=exam['approved_id'] or (exam['draft_id'] if include_drafts else None)
        if not rid:continue
        saved=get_db().execute('SELECT * FROM revisions WHERE id=? AND exam_id=?',(rid,exam['id'])).fetchone()
        data=decoded(saved);verify_revision(data['config'],data['preview'])
        info=data['metadata']['exam'];groups=defaultdict(int)
        for seat in data['preview']['positions']:
            if not seat.get('sid'):continue
            person=data['metadata']['students'][seat['sid']]
            emergency=bool(seat.get('emergency'))
            block='' if emergency else seat.get('block_no') or person.get('block_no','')
            subject=seat.get('subject_code') or person.get('subject_code') or person.get('branch','')
            groups[(seat['room'],block,subject,emergency)]+=1
        for (room_id,block,subject,emergency),count in sorted(groups.items()):
            room=data['metadata']['rooms'][room_id]
            rows.append({'exam_id':exam['id'],'title':info['title'],'starts_at':info['starts_at'],'timezone':info['timezone'],
                'shift':info.get('shift',''),'block':block,'subject':subject,'emergency':emergency,
                'building':room.get('floor') or room.get('building',''),'room':room['number'],'count':count,
                'revision_id':rid,'approved':bool(saved['approved'])})
    return rows


def workbook(rows):
    book=Workbook();book.remove(book.active)
    sheet(book,'Block classroom register',
          ['Examination','Start time (UTC)','Time zone','Shift','Block','Subject / Branch','Building / Floor','Classroom','Students','Type','Revision','Status'],
          ([r['title'],r['starts_at'],r['timezone'],r['shift'],r['block'],r['subject'],r['building'],r['room'],r['count'],
            'Emergency admission' if r['emergency'] else 'Official block' if r['block'] else 'Custom group',r['revision_id'],
            'Approved' if r['approved'] else 'Draft'] for r in rows))
    return finish(book)
