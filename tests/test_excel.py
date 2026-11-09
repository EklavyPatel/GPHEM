from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
import pytest
from openpyxl import Workbook,load_workbook
from services.excel_service import parse_students, FIELDS
from services.export_service import student_template,validation_report


def workbook(rows, headings=None):
    book=Workbook(); sheet=book.active
    sheet.append(headings or list(FIELDS.values()))
    for row in rows: sheet.append(row)
    out=BytesIO();book.save(out);return out.getvalue()


def record(sid='001',**fields):
    return [sid,fields.get('name','Student'),fields.get('branch','ICT'),'2024','2',fields.get('session','Exam')]


def test_text_sid_and_template():
    records,errors=parse_students(workbook([record()]),'students.xlsx',1,'Exam')
    assert not errors and records[0]['sid']=='001'
    wb=load_workbook(student_template('Exam'))
    assert wb.active['A2'].value=='001' and wb.active['A2'].number_format=='@'


@pytest.mark.parametrize('row,part',[(record(''),'SID is required'),(record(1),'Excel Text'),
 (record(' 001'),'whitespace'),(record(name=''),'Student Name is required'),
 (record(session='Unknown'),'must match'),(record('=1+1'),'formula')])
def test_invalid_records_preserved(row,part):
    records,errors=parse_students(workbook([row]),'students.xlsx',1,'Exam')
    assert len(records)==1 and any(part in e['message'] for e in errors)
    assert records[0]['valid'] is False


def test_duplicate_session_sid_and_existing():
    records,errors=parse_students(workbook([record(),record()]),'a.xlsx',1,'Exam',existing=['001'])
    assert len(records)==2 and sum('Duplicate' in e['message'] for e in errors)==2


def test_custom_mapping_and_ambiguous_heading():
    headings=['ID','Name','Department','Cohort','Level','Test']
    mapping=dict(zip(FIELDS,headings))
    records,errors=parse_students(workbook([record()],headings),'a.xlsx',1,'Exam',mapping)
    assert not errors and records[0]['sid']=='001'
    _,errors=parse_students(workbook([record()],['SID','SID','Branch','Batch','Year','Examination / Session']),'a.xlsx',1,'Exam')
    assert errors


@pytest.mark.parametrize('filename,data', [('bad.csv',b'x'),('bad.xlsx',b'bad'),('big.xlsx',b'x'*(5*1024*1024+1))])
def test_unsafe_workbooks_rejected(filename,data):
    with pytest.raises(ValueError):parse_students(data,filename,1,'Exam')


def test_expansion_limit():
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z: z.writestr('large.xml',b'0'*(31*1024*1024))
    with pytest.raises(ValueError,match='expands'):parse_students(out.getvalue(),'bomb.xlsx',1,'Exam')


def test_formula_injection_export():
    records,errors=parse_students(workbook([record('=1+1')]),'a.xlsx',1,'Exam')
    report=load_workbook(validation_report(records,errors),data_only=False)
    assert report['All submitted records']['B2'].data_type=='s'


@pytest.mark.parametrize('count',[10,100,1000,5000])
def test_import_dataset_sizes(count):
    records,errors=parse_students(workbook([record(f'{i:06}') for i in range(count)]),'a.xlsx',1,'Exam')
    assert not errors and len(records)==count and records[0]['sid']=='000000'
