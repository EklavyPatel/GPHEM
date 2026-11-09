"""GTU block/room reports and session-specific text-safe Excel templates."""
from collections import defaultdict
import json
from openpyxl import Workbook
from .db import get_db
from .allocation_service import decoded,verify_revision
from .export_service import sheet,finish


def gtu_template(exam):
    book=Workbook();book.remove(book.active)
    sheet(book,'GTU blocks',['exam_date','session','block_no','subject_code','subject_name','enrollment_no'],
          [(exam['gtu_date'],exam['shift'],'001','3110001','Example Subject','001')])
    return finish(book)


def gtu_report(row):
    data=decoded(row);config=data['config'];preview=data['preview'];metadata=data['metadata']
    verify_revision(config,preview)
    payloads=[json.loads(r['payload']) for r in get_db().execute('SELECT payload FROM assignments WHERE revision_id=?',(row['id'],))]
    order={key:i for i,key in enumerate(metadata['rooms'])}
    payloads.sort(key=lambda p:(order[p['room']],p['seat_number']))
    headers=['Room','Floor','Block number','Subject code','Subject name','Seat number','Enrollment number','Attendance / Signature','PDF source bench']
    def values(p):return [p['room_number'],p['floor'],'Emergency admission' if p.get('emergency') else p['block_no'],p['subject_code'],p['subject_name'],p['seat_number'],p['sid'],'',p.get('pdf_bench')]
    book=Workbook();book.remove(book.active)
    sheet(book,'Room-wise list',headers,map(values,payloads))
    by_block=defaultdict(list)
    for p in payloads:by_block[p['block_no']].append(p)
    sheet(book,'Block-wise list',['Block number','Subject code','Subject name','Room','Floor','Students','Enrollment numbers'],
          [('Emergency admission '+ps[0]['sid'] if ps[0].get('emergency') else b,ps[0]['subject_code'],ps[0]['subject_name'],ps[0]['room_number'],ps[0]['floor'],len(ps),', '.join(p['sid'] for p in ps)) for b,ps in sorted(by_block.items())])
    room_rows=[]
    for key,room in metadata['rooms'].items():
        members=[p for p in payloads if p['room']==key]
        room_rows.append((room['number'],room['floor'],len({p['block_no'] for p in members if not p.get('emergency')}),len(members),room['capacity']-len(members)))
        if members:sheet(book,f'Attendance {key}',headers,map(values,members))
    sheet(book,'Room utilization',['Room','Floor','Blocks','Students','Vacant seats'],room_rows)
    used=len({p['room'] for p in payloads});capacity=config['settings']['room_capacity'];total=len(payloads)
    sheet(book,'Session summary',['Field','Value'],[
        ('Examination',metadata['exam']['title']),('Exam date',config['exam_date']),('Shift',config['shift']),
        ('Time zone',config['timezone']),('Available rooms',len(metadata['rooms'])),('Rooms used',used),
        ('Students',total),('Blocks',len({p['block_no'] for p in payloads if not p.get('emergency')})),('Direct emergency admissions',sum(bool(p.get('emergency')) for p in payloads)),('Room capacity',capacity),('Maximum blocks per room',config['settings']['max_blocks_per_room']),
        ('Vacant seats in used rooms',used*capacity-total),('Total session capacity',len(metadata['rooms'])*capacity),
        ('Remaining seats across all available rooms',len(metadata['rooms'])*capacity-total)])
    sheet(book,'Allocation validation',['Check','Result'],[
        ('Every enrollment allocated exactly once','PASS'),('Regular GTU blocks stay in exactly one room','PASS'),
        ('Regular blocks: distinct subjects and block limits; all students: room capacity','PASS'),
        ('Regular blocks: full-block exclusivity','PASS'),
        ('Automatic floor order / full-block room priority',
         'Administrator-selected rooms: floor gaps and cross-floor placement permitted' if preview.get('manual_room_selection') else 'PASS'),
        ('Regular blocks: consecutive seats and enrollment order','PASS'),('Receipt policy','Private historical rehearsal' if config.get('historical') else 'Normal D-1 receipts; recorded late-admission authorizations permitted'),
        ('Direct emergency seats', 'Explicit fixed-seat exceptions to GTU grouping, subject separation and ordering; capacity and identities verified' if config.get('emergency_seats') else 'None'),('Method',preview['method']),('Revision',row['id']),('Approved',bool(row['approved']))])
    return finish(book)
