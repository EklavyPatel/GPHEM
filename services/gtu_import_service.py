"""CSV/XLSX GTU roster validation with exact enrollment IDs and D-1 receipts."""
from collections import defaultdict
from datetime import date,datetime,timezone,timedelta
from io import BytesIO,StringIO
from zoneinfo import ZoneInfo
from zipfile import ZipFile
import csv
from openpyxl import load_workbook
from .gtu_engine import validate_config,room_sequence

FIELDS=['exam_date','session','block_no','subject_code','subject_name','enrollment_no']


def check_deadline(exam_date,timezone_name,uploaded_at):
    instant=datetime.fromtimestamp(uploaded_at,timezone.utc)
    uploaded_date=instant.astimezone(ZoneInfo(timezone_name)).date()
    if uploaded_date>=date.fromisoformat(exam_date):
        raise ValueError(f'GTU roster upload must be on or before D−1 ({(date.fromisoformat(exam_date)-timedelta(days=1)).isoformat()}) in {timezone_name}. '
                         'Exam-day and later uploads are blocked; no deadline override is enabled.')


def read_rows(data,filename):
    if len(data)>5*1024*1024:
        raise ValueError('GTU roster exceeds the 5 MB upload limit.')
    extension=filename.lower().rsplit('.',1)[-1]
    if extension=='csv':
        try:
            for line in csv.reader(StringIO(data.decode('utf-8-sig')),strict=True):
                yield [(v,False) for v in line]
        except (UnicodeError,csv.Error) as exc:
            raise ValueError('Upload a valid UTF-8 CSV file with quoted comma-containing values.') from exc
    elif extension=='xlsx':
        try:
            with ZipFile(BytesIO(data)) as archive:
                files=archive.infolist()
                if len(files)>1000 or sum(i.file_size for i in files)>30*1024*1024:
                    raise ValueError('GTU workbook expands beyond the safe processing limit.')
                if any(i.flag_bits&1 or 'vbaproject' in i.filename.lower() for i in files):
                    raise ValueError('Encrypted or macro-containing workbooks are not supported.')
            book=load_workbook(BytesIO(data),read_only=True,data_only=False,keep_links=False)
        except ValueError:raise
        except Exception as exc:raise ValueError('Upload a readable .xlsx GTU workbook.') from exc
        try:
            if book.active.max_row and book.active.max_row>10001:
                raise ValueError('GTU imports may contain at most 10,000 records.')
            if book.active.max_column and book.active.max_column>50:
                raise ValueError('GTU workbooks may contain at most 50 columns.')
            for row in book.active.iter_rows(max_col=50):
                yield [(cell.value,cell.data_type in ('f','e')) for cell in row]
        except ValueError:raise
        except Exception as exc:raise ValueError('The GTU worksheet contains malformed content.') from exc
        finally:book.close()
    else:
        raise ValueError('GTU rosters support .csv and .xlsx files only.')


def parse_gtu(data,filename,exam,settings,existing=(),uploaded_at=None):
    uploaded_at=datetime.now(timezone.utc).timestamp() if uploaded_at is None else uploaded_at
    settings=validate_config(settings)
    rows=read_rows(data,filename)
    records,errors=[],[]
    def error(row,sid,message):errors.append({'row':row,'sid':sid,'message':message})
    try:
        try:check_deadline(exam['gtu_date'],exam['timezone'],uploaded_at)
        except ValueError as exc:error(1,'',str(exc))
        header=next(rows,[])
        if len(header)>50:
            raise ValueError('GTU roster headers may contain at most 50 columns.')
        headings=[str(v).strip() if v is not None else '' for v,_ in header]
        indices={}
        for field in FIELDS:
            matches=[i for i,h in enumerate(headings) if h==field]
            if len(matches)!=1:error(1,'',f'Expected exactly one GTU column named {field}.')
            else:indices[field]=matches[0]
        if len(indices)!=len(FIELDS):return records,errors
        existing=list(existing)
        seen={p['enrollment_no'] for p in existing}
        old_blocks={p['block_no'] for p in existing}
        blocks=defaultdict(list)
        subject_names={p['subject_code'].casefold():p['subject_name'] for p in existing}
        for row_no,cells in enumerate(rows,2):
            if row_no>10001:raise ValueError('GTU imports may contain at most 10,000 records.')
            if len(cells)>50:raise ValueError('GTU CSV files may contain at most 50 columns.')
            if not cells or all(v is None or v=='' for v,_ in cells):continue
            record={'row':row_no,'uploaded_at':uploaded_at}
            for field,index in indices.items():
                value,formula=cells[index] if index<len(cells) else (None,False)
                if field=='exam_date' and isinstance(value,(date,datetime)):
                    value=value.date().isoformat() if isinstance(value,datetime) else value.isoformat()
                text='' if value is None else str(value)
                record[field]=text
                if formula:error(row_no,text if field=='enrollment_no' else '',f'{field} contains a formula or Excel error; use literal values.')
                if not text or text!=text.strip() or len(text)>250 or any(ord(c)<32 for c in text):
                    error(row_no,record.get('enrollment_no',''),f'{field} is required text without surrounding whitespace or control characters (maximum 250 characters).')
                if field=='enrollment_no' and (not isinstance(value,str) or len(text)>100):
                    error(row_no,text,'Enrollment numbers must be Excel Text (maximum 100 characters) to preserve leading zeros.')
                if field=='block_no' and not isinstance(value,(str,int)):
                    error(row_no,'','block_no must be a GTU block identifier, not a fraction, boolean or date.')
                if field in ('block_no','subject_code') and isinstance(value,bool):
                    error(row_no,'',f'{field} cannot be a boolean.')
            sid=record['enrollment_no'];record['sid']=sid
            if sid in seen:error(row_no,sid,'Duplicate enrollment number within this date and shift.')
            seen.add(sid)
            if record['exam_date']!=exam['gtu_date'] or record['session']!=exam['shift']:
                error(row_no,sid,f'Every row must reference {exam["gtu_date"]} / {exam["shift"]}; upload other sessions separately.')
            block=record['block_no']
            if block in old_blocks:
                error(row_no,sid,f'Block {block} is already imported. Upload each complete GTU block once; do not extend or split it between files.')
            blocks[block].append(record)
            code=record['subject_code'].casefold()
            if code in subject_names and subject_names[code]!=record['subject_name']:
                error(row_no,sid,f'Subject {record["subject_code"]} has inconsistent names.')
            subject_names[code]=record['subject_name']
            records.append(record)
        for block,members in blocks.items():
            message=None
            if len(members)>settings['room_capacity']:
                message=f'GTU block {block} has {len(members)} students; maximum {settings["room_capacity"]}. Blocks cannot be split.'
            if len({(p['subject_code'].casefold(),p['subject_name']) for p in members})!=1:
                message=f'GTU block {block} must contain exactly one subject.'
            if message:
                for p in members:error(p['row'],p['sid'],message)
        total=len(records)+len(existing)
        capacity=len(room_sequence(settings,exam.get('disabled_rooms',[])))*settings['room_capacity']
        if total>capacity:error(1,'',f'Insufficient session capacity: {total} students, {capacity} available seats; shortfall {total-capacity}.')
        if not records:error(2,'','No GTU student records found.')
        bad_rows={e['row'] for e in errors}
        for p in records:p['valid']=p['row'] not in bad_rows and 1 not in bad_rows
        return records,errors
    finally:
        rows.close()
