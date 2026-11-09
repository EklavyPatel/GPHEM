from pathlib import Path
from copy import deepcopy
import pytest
from services.pdf_service import parse_report,read_pdf,tools_available
from services.gtu_engine import allocate,DEFAULT_CONFIG
from .pdf_fixtures import make_pdf,report_lines


def test_parser_preserves_every_membership_and_source_bench():
    parsed=parse_report('\n'.join(report_lines()))
    assert parsed['blocks']==2 and parsed['students']==5
    session=parsed['sessions'][0]
    assert session['exam_date']=='2099-05-13' and session['shift']=='morning'
    assert session['records'][0]['sid']=='000001000001'
    assert session['records'][0]['pdf_bench']==1 and session['records'][0]['subject_name']=='SUB1'
    assert session['records'][0]['source_room']==''


@pytest.mark.skipif(not tools_available(),reason='Poppler is required for PDF extraction')
def test_real_pdf_extraction_on_generated_fixture():
    parsed=read_pdf(make_pdf(report_lines()))
    assert parsed['pages']==1 and parsed['blocks']==2 and parsed['students']==5


@pytest.mark.parametrize('change',[
 lambda s:s.replace('Total : 3','Total : 4'),
 lambda s:s.replace('000001000002 2','000001000002 1'),
 lambda s:s.replace('Block No : 2','Block No : 1'),
 lambda s:s.replace('SUB2 13-May-99 AM','SUB2 unknown AM'),
])
def test_unreadable_or_inconsistent_blocks_never_silently_discarded(change):
    with pytest.raises(ValueError):parse_report(change('\n'.join(report_lines())))


def test_missing_text_and_wrong_file():
    with pytest.raises(ValueError):read_pdf(b'not a pdf')
    with pytest.raises(ValueError):parse_report('Scanned text not recognized')


def test_date_shift_partition_does_not_merge_repeated_block_numbers():
    one='\n'.join(report_lines());two='\n'.join(report_lines(date='15-May-99'))
    parsed=parse_report(one+'\f'+two)
    assert len(parsed['sessions'])==2 and parsed['students']==10


@pytest.mark.skipif(not tools_available(),reason='Poppler is required for provided PDF verification')
def test_provided_private_pdf_when_present():
    path=Path(__file__).resolve().parent.parent/'624_DI-SEM4SUMMEREXAMINATION-2026 (1).pdf'
    if not path.exists():pytest.skip('Private user PDF is not distributed with source')
    report=read_pdf(path.read_bytes())
    assert (report['pages'],report['blocks'],report['students'],len(report['sessions']))==(24,103,1663,7)
    for session in report['sessions']:
        result=allocate({'settings':DEFAULT_CONFIG,'students':session['records'],'disabled_rooms':[]})
        assert sum(p['sid'] is not None for p in result['positions'])==len(session['records'])
