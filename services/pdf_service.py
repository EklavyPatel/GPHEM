"""Strict import of text-based GTU Crystal Reports block-arrangement PDFs.

Uses the locally installed Poppler tools; no uploads leave this computer.
Every header, declared total and 1..N source bench sequence must reconcile.
"""
from collections import defaultdict
from datetime import date
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HEADER=re.compile(r'Subject\s+Code\s*:\s*(\S+)\s+(\d{1,2}-[A-Za-z]{3}-\d{2,4})\s+(AM|PM)\s+Block\s+No\s*:\s*(\S+)\s+Room\s+No[ \t]*:[ \t]*([^\n\f]*)',re.I)
PAIR=re.compile(r'(?<!\w)(\d{8,25})\s+([1-9]\d{0,2})(?!\w)')
MONTHS={m:i for i,m in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],1)}


def tools_available():
    return bool(shutil.which('pdftotext') and shutil.which('pdfinfo'))


def extract_text(data):
    if len(data)>5*1024*1024 or not data.startswith(b'%PDF-'):
        raise ValueError('Upload a valid PDF smaller than 5 MB.')
    if not tools_available():
        raise ValueError('PDF import needs Poppler (pdftotext and pdfinfo). Install poppler-utils on Linux or add Poppler to PATH on your computer.')
    with tempfile.TemporaryDirectory(prefix='gtu-pdf-') as directory:
        source=Path(directory)/'upload.pdf';output=Path(directory)/'content.txt'
        source.write_bytes(data)
        try:
            info=subprocess.run([shutil.which('pdfinfo'),str(source)],capture_output=True,timeout=10,check=False)
            if info.returncode or len(info.stdout)>20000:
                raise ValueError('PDF is encrypted, corrupt, or cannot be read. Upload the original text-based GTU report.')
            pages=re.search(rb'^Pages:\s*(\d+)',info.stdout,re.M)
            if not pages or not 1<=int(pages[1])<=100:
                raise ValueError('PDF imports support between 1 and 100 pages.')
            result=subprocess.run([shutil.which('pdftotext'),'-layout','-enc','UTF-8',str(source),str(output)],
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,check=False)
            if result.returncode or not output.exists() or output.stat().st_size>5*1024*1024:
                raise ValueError('PDF text extraction failed or exceeded the safe text limit.')
            text=output.read_text(encoding='utf-8')
        except subprocess.TimeoutExpired as exc:
            raise ValueError('PDF processing took too long. Use a smaller original GTU report.') from exc
    if not text.strip():
        raise ValueError('This PDF has no readable text. Scanned/image PDFs require OCR and are not supported; upload the original GTU PDF or CSV/Excel.')
    return text,int(pages[1])


def parse_report(text):
    matches=list(HEADER.finditer(text))
    if len(matches)>2000:
        raise ValueError('PDF import supports at most 2,000 blocks per file.')
    if not matches:
        raise ValueError('No GTU block headers were found. Expected Subject Code, date, AM/PM, Block No and Room No.')
    if len(matches)!=len(re.findall(r'Subject\s+Code\s*:',text,re.I)):
        raise ValueError('Some GTU block headers could not be read. No blocks were silently skipped.')
    if len(matches)!=len(re.findall(r'Total\s*:',text,re.I)):
        raise ValueError('Block headers and totals do not reconcile. Upload the complete original report.')
    exam=re.search(r'Exam\s*:\s*([^\n\f]+)',text)
    center=re.search(r'Center\s*:\s*([^\n\f]+)',text)
    if exam and len(exam[1].strip())>150:
        raise ValueError('PDF examination title exceeds 150 characters.')
    if center and len(center[1].strip())>250:
        raise ValueError('PDF center name exceeds 250 characters.')
    sessions={};seen_blocks=set()
    for index,match in enumerate(matches):
        code,raw_date,shift,block,source_room=match.groups()
        if len(code)>100 or len(block)>100:
            raise ValueError('PDF subject codes and block numbers must be at most 100 characters.')
        day,month,year=raw_date.split('-');year=int(year);year=2000+year if year<100 else year
        try:exam_date=date(year,MONTHS[month.lower()],int(day)).isoformat()
        except (ValueError,KeyError) as exc:raise ValueError(f'Invalid PDF examination date: {raw_date}.') from exc
        shift='morning' if shift.upper()=='AM' else 'afternoon'
        key=(exam_date,shift)
        block_key=(*key,block)
        if block_key in seen_blocks:
            raise ValueError(f'Duplicate PDF block {block} in {exam_date} / {shift}; blocks cannot be guessed or combined.')
        seen_blocks.add(block_key)
        section=text[match.end():matches[index+1].start() if index+1<len(matches) else len(text)]
        total_matches=re.findall(r'Total\s*:\s*(\d+)',section,re.I)
        pairs=PAIR.findall(section)
        if len(total_matches)!=1 or len(pairs)!=int(total_matches[0]):
            raise ValueError(f'Block {block} ({exam_date}) declares {total_matches or "no total"} but {len(pairs)} enrollments were extracted.')
        total=int(total_matches[0])
        if not 1<=total<=30:
            raise ValueError(f'PDF block {block} has {total} students; GTU blocks must contain 1–30 students.')
        if sorted(int(bench) for _,bench in pairs)!=list(range(1,total+1)):
            raise ValueError(f'Block {block} has missing or repeated PDF bench numbers.')
        page=text[:match.start()].count('\f')+1
        session=sessions.setdefault(key,{'exam_date':exam_date,'shift':shift,'records':[],'blocks':0})
        session['blocks']+=1
        for sid,bench in pairs:
            session['records'].append({'exam_date':exam_date,'session':shift,'block_no':block,'subject_code':code,
                                      'subject_name':code,'enrollment_no':sid,'sid':sid,
                                      'pdf_bench':int(bench),'pdf_page':page,'source_room':source_room.strip()})
    if len(sessions)>100 or sum(len(s['records']) for s in sessions.values())>10000:
        raise ValueError('PDF import supports at most 100 sessions and 10,000 enrollments per file.')
    for session in sessions.values():
        ids=[r['sid'] for r in session['records']]
        if len(ids)!=len(set(ids)):
            raise ValueError(f'Duplicate enrollment numbers in PDF session {session["exam_date"]} / {session["shift"]}.')
    return {'title':exam[1].strip() if exam else 'GTU Examination',
            'center':center[1].strip() if center else '',
            'sessions':[sessions[k] for k in sorted(sessions)],'blocks':len(matches),
            'students':sum(len(s['records']) for s in sessions.values()),
            'note':'This PDF supplies subject codes, not subject names. Codes are shown as subject labels. Original PDF bench numbers are retained as provenance.'}


def read_pdf(data):
    text,pages=extract_text(data)
    return {**parse_report(text),'pages':pages}
