"""Text-safe Excel reports. Untrusted strings are never emitted as formulas."""
from collections import defaultdict
from io import BytesIO
import json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from .db import get_db
from .allocation_service import decoded
from .room_service import available

HEADERS = ['SID', 'Student Name', 'Branch', 'Batch', 'Year', 'Building', 'Classroom',
           'Row', 'Column', 'Bench', 'Seat', 'Attendance / Signature', 'GTU Block', 'Subject code', 'PDF bench']


def sheet(book, name, headers, rows):
    ws = book.create_sheet(name)
    ws.append(headers)
    for record in rows:
        ws.append(list(record))
    for row in ws:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
                cell.number_format = '@'
    for cell in ws[1]:
        cell.fill = PatternFill('solid', fgColor='163E37')
        cell.font = Font(color='FFFFFF', bold=True)
        cell.alignment = Alignment(wrap_text=True)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for column in ws.columns:
        ws.column_dimensions[column[0].column_letter].width = min(42, max(14, max(len(str(c.value or '')) for c in column)+2))
    ws.print_title_rows = '1:1'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    return ws


def finish(book):
    out = BytesIO()
    book.save(out)
    out.seek(0)
    return out


def validation_report(records, errors, gtu=False):
    book = Workbook(); book.remove(book.active)
    sheet(book, 'Validation errors', ['Excel row', 'SID', 'Problem'],
          [(e['row'], e['sid'], e['message']) for e in errors])
    if gtu:
        sheet(book,'All submitted records',['Excel/CSV row','Exam date','Shift','Block number','Subject code','Subject name','Enrollment number','Valid'],
              [[r.get(k,'') for k in ('row','exam_date','session','block_no','subject_code','subject_name','enrollment_no','valid')] for r in records])
    else:
        sheet(book, 'All submitted records', ['Excel row','SID','Student Name','Branch','Batch','Year','Session','Valid'],
              [[r.get(k, '') for k in ('row','sid','name','branch','batch','year','session','valid')] for r in records])
    return finish(book)


def student_template(exam_title='Example Examination'):
    book = Workbook(); book.remove(book.active)
    sheet(book, 'Students', ['SID','Student Name','Branch','Batch','Year','Examination / Session'],
          [('001','Example Student','ICT','2024','2',exam_title)])
    return finish(book)


def allocation_report(row):
    data = decoded(row)
    if data['config'].get('mode')=='gtu':
        from .gtu_export_service import gtu_report
        return gtu_report(row)
    metadata, preview = data['metadata'], data['preview']
    payloads = [json.loads(r['payload']) for r in get_db().execute(
        'SELECT payload FROM assignments WHERE revision_id=? ORDER BY sid', (row['id'],))]
    def values(p):
        return [p[k] for k in ('sid','name','branch','batch','year','building','room_number','row','column','bench_number','seat_position')] + ['',p.get('block_no',''),p.get('subject_code',''),p.get('pdf_bench')]
    book = Workbook(); book.remove(book.active)
    sheet(book, 'Complete allocation', HEADERS, map(values, payloads))
    sheet(book, 'Room-wise lists', HEADERS, map(values, sorted(payloads,key=lambda p:(p['building'],p['room_number'],p['row'],p['column'],p['seat_position']))))
    sheet(book, 'Branch-wise lists', HEADERS, map(values, sorted(payloads,key=lambda p:(p['branch'],p['sid']))))
    for key, room in metadata['rooms'].items():
        sheet(book, f'Attendance {key}', HEADERS, map(values, [p for p in payloads if p['room']==key]))
    sheet(book, 'Classroom utilization', ['Building','Room','Benches','Physical seats','Available','Allocated','Utilization %'],
          [(r['building'],r['number'],r['layout']['rows']*r['layout']['columns'],
            r['layout']['rows']*r['layout']['columns']*r['layout']['seats_per_bench'],available(r['layout']),
            sum(p['room']==k for p in payloads),round(100*sum(p['room']==k for p in payloads)/max(1,available(r['layout'])),2))
           for k,r in metadata['rooms'].items()])
    allocated = {p['sid'] for p in payloads}
    sheet(book, 'Unallocated students', ['SID','Student Name','Branch','Batch'],
          [(sid,p['name'],p['branch'],p['batch']) for sid,p in metadata['students'].items() if sid not in allocated])
    from engine import Exam, Plan
    Plan(Exam.model_validate(data['config']), preview).verify({p['seat_id']:p['sid'] for p in preview['positions']})
    sheet(book, 'Allocation validation', ['Check','Result'], [('Every student allocated exactly once','PASS'),
          ('Physical seats, eligibility, quotas, ordering, pins and locks','PASS'),
          ('Revision',row['id']),('Approved',bool(row['approved'])),('Engine method',preview['method']),('Seed',preview['seed'])])
    sheet(book, 'Examination', ['Field','Value'], metadata['exam'].items())
    return finish(book)


def generation_error_report(exam_id):
    book = Workbook(); book.remove(book.active)
    errors = get_db().execute('SELECT created,message FROM generation_errors WHERE exam_id=? ORDER BY id DESC LIMIT 1000', (exam_id,)).fetchall()
    sheet(book, 'Generation validation errors', ['Time (UTC)', 'Error'], [(e['created'],e['message']) for e in errors])
    return finish(book)
