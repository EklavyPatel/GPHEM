from copy import deepcopy
from datetime import datetime,timezone
from io import BytesIO,StringIO
import csv
import pytest
from openpyxl import Workbook
from services.gtu_import_service import parse_gtu,check_deadline,FIELDS
from services.gtu_engine import DEFAULT_CONFIG

EXAM={'gtu_date':'2099-11-09','shift':'morning','timezone':'Asia/Kolkata','disabled_rooms':[]}


def rows_for(sizes):
    return [[EXAM['gtu_date'],'morning',f'{b:03}',f'S{b}',f'Subject {b}',f'{b:03}{i:03}'] for b,size in enumerate(sizes) for i in range(size)]


def csv_data(rows):
    out=StringIO();writer=csv.writer(out);writer.writerow(FIELDS);writer.writerows(rows);return out.getvalue().encode('utf-8-sig')


def xlsx_data(rows):
    book=Workbook();book.active.append(FIELDS)
    for row in rows:book.active.append(row)
    out=BytesIO();book.save(out);return out.getvalue()


@pytest.mark.parametrize('format',['csv','xlsx'])
def test_gtu_native_import(format):
    data=rows_for([13,17])
    payload=csv_data(data) if format=='csv' else xlsx_data(data)
    records,errors=parse_gtu(payload,'blocks.'+format,EXAM,DEFAULT_CONFIG)
    assert not errors and len(records)==30 and records[0]['enrollment_no']=='000000'
    assert len({p['block_no'] for p in records})==2


@pytest.mark.parametrize('field,value,part',[
 (0,'2099-11-10','Every row must reference'),(1,'afternoon','Every row must reference'),
 (2,'','block_no is required'),(3,'','subject_code is required'),(5,'','enrollment_no is required'),
 (5,' 001','surrounding whitespace')])
def test_bad_rows_are_reported(field,value,part):
    rows=rows_for([1]);rows[0][field]=value
    records,errors=parse_gtu(csv_data(rows),'a.csv',EXAM,DEFAULT_CONFIG)
    assert len(records)==1 and any(part in e['message'] for e in errors)


def test_numeric_enrollment_rejected():
    rows=rows_for([1]);rows[0][5]=1
    _,errors=parse_gtu(xlsx_data(rows),'a.xlsx',EXAM,DEFAULT_CONFIG)
    assert any('Excel Text' in e['message'] for e in errors)


def test_block_size_subject_and_duplicate_errors():
    records,errors=parse_gtu(csv_data(rows_for([31])),'a.csv',EXAM,DEFAULT_CONFIG)
    assert len(records)==31 and any('block 000 has 31' in e['message'] for e in errors)
    rows=rows_for([2]);rows[1][3]='OTHER'
    _,errors=parse_gtu(csv_data(rows),'a.csv',EXAM,DEFAULT_CONFIG)
    assert any('exactly one subject' in e['message'] for e in errors)
    rows=rows_for([2]);rows[1][5]=rows[0][5]
    _,errors=parse_gtu(csv_data(rows),'a.csv',EXAM,DEFAULT_CONFIG)
    assert any('Duplicate enrollment' in e['message'] for e in errors)


def test_existing_block_cannot_be_extended():
    records,errors=parse_gtu(csv_data(rows_for([1])),'a.csv',EXAM,DEFAULT_CONFIG)
    assert not errors
    rows=rows_for([1]);rows[0][5]='NEW'
    _,errors=parse_gtu(csv_data(rows),'a.csv',EXAM,DEFAULT_CONFIG,records)
    assert any('already imported' in e['message'] for e in errors)


def test_capacity_with_unavailable_rooms():
    exam={**EXAM,'disabled_rooms':[r for f in DEFAULT_CONFIG['floors'] for r in f['rooms']][1:]}
    _,errors=parse_gtu(csv_data(rows_for([20,20])),'a.csv',exam,DEFAULT_CONFIG)
    assert any('shortfall 10' in e['message'] for e in errors)


def test_deadline_uses_exam_timezone_and_midnight_boundary():
    allowed=datetime(2026,11,8,18,29,59,tzinfo=timezone.utc).timestamp()
    late=datetime(2026,11,8,18,30,0,tzinfo=timezone.utc).timestamp()
    check_deadline('2026-11-09','Asia/Kolkata',allowed)
    with pytest.raises(ValueError,match='D−1'):check_deadline('2026-11-09','Asia/Kolkata',late)
    rows=rows_for([1]);rows[0][0]='2026-11-09'
    records,errors=parse_gtu(csv_data(rows),'a.csv',{**EXAM,'gtu_date':'2026-11-09'},DEFAULT_CONFIG,uploaded_at=late)
    assert any('D−1' in e['message'] for e in errors) and not records[0]['valid']


def test_xlsx_dates_and_formulas():
    rows=rows_for([1]);rows[0][0]=datetime(2099,11,9)
    records,errors=parse_gtu(xlsx_data(rows),'a.xlsx',EXAM,DEFAULT_CONFIG)
    assert not errors and records[0]['exam_date']=='2099-11-09'
    rows[0][5]='=1+1'
    _,errors=parse_gtu(xlsx_data(rows),'a.xlsx',EXAM,DEFAULT_CONFIG)
    assert any('formula' in e['message'] for e in errors)


@pytest.mark.parametrize('filename,data',[('a.xls',b'not an XLSX'),('a.xlsx',b'bad'),('a.csv',b'\xff\xff')])
def test_invalid_gtu_file_is_rejected(filename,data):
    with pytest.raises(ValueError):parse_gtu(data,filename,EXAM,DEFAULT_CONFIG)


def test_gtu_missing_and_duplicate_headers():
    _,errors=parse_gtu(b'block_no,block_no\n1,1\n','a.csv',EXAM,DEFAULT_CONFIG)
    assert any('exactly one GTU column' in e['message'] for e in errors)


def test_shipped_gtu_examples_allocate_as_documented():
    from pathlib import Path
    from services.gtu_engine import allocate
    for name in ['gtu_blocks.csv','gtu_blocks.xlsx']:
        path=Path(__file__).resolve().parent.parent/'examples'/name
        records,errors=parse_gtu(path.read_bytes(),path.name,EXAM,DEFAULT_CONFIG)
        assert not errors and len(records)==82
        config={'settings':DEFAULT_CONFIG,'disabled_rooms':[],'students':records}
        preview=allocate(config)
        assert len({p['room'] for p in preview['positions'] if p['sid']})==3
