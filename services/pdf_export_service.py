"""Fill room blanks on the retained original PDF using local Poppler/Ghostscript."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from defusedxml import ElementTree as ET
from .pdf_service import MONTHS


def ps_string(value):
    # Room numbers and the generated footer are ASCII only; escape PostScript syntax.
    return str(value).replace('\\','\\\\').replace('(','\\(').replace(')','\\)')


def fill_rooms(content, data, revision_id, approved, related=()):
    gs=shutil.which('gs');poppler=shutil.which('pdftotext')
    if not gs or not poppler:
        raise ValueError('Original PDF room filling needs Ghostscript and Poppler. Install ghostscript and poppler-utils, then retry.')
    rooms={};source_pages={};labels={}
    for snapshot,rid,is_approved in [(data,revision_id,approved),*related]:
        metadata=snapshot['metadata']
        for seat in snapshot['preview']['positions']:
            if not seat.get('sid'):continue
            person=metadata['students'][seat['sid']]
            if person.get('pdf_page') is None:continue  # Late admissions use the separate current allocation report.
            key=(person['pdf_page'],person['block_no'],person['subject_code'],person['exam_date'],person['session'])
            rooms.setdefault(key,set()).add(str(metadata['rooms'][seat['room']]['number']))
            source_pages[key]=person
            labels.setdefault(person['pdf_page'],set()).add(f'{"APPROVED" if is_approved else "DRAFT"} #{rid}')
    if not rooms:raise ValueError('This revision has no original PDF block references. Download the allocation report instead.')
    if any(len(v)!=1 for v in rooms.values()):
        raise ValueError('Custom Mode split a source block across rooms. A single room blank would be misleading; download the complete allocation report instead.')
    with tempfile.TemporaryDirectory(prefix='gtu-filled-') as directory:
        root=Path(directory);source=root/'source.pdf';bbox=root/'words.xml';out=root/'rooms.pdf';overlay=root/'overlay.ps'
        source.write_bytes(content)
        try:
            result=subprocess.run([poppler,'-bbox',str(source),str(bbox)],capture_output=True,timeout=20)
            if result.returncode or not bbox.exists() or bbox.stat().st_size>15*1024*1024:
                raise ValueError('Cannot locate room blanks in the original PDF.')
            # Poppler emits its own safe XHTML doctype. Disable DTD rejection only;
            # entity/external resolution remains forbidden by defusedxml.
            document=ET.fromstring(bbox.read_bytes())
            pages=list(document.iter('{http://www.w3.org/1999/xhtml}page'))
            commands=[];found=set()
            for number,page in enumerate(pages,1):
                words=list(page);height=float(page.attrib['height']);width=float(page.attrib['width']);draw=[]
                for word in words:
                    if word.text!='Room':continue
                    y=float(word.attrib['yMin']);line=sorted([w for w in words if abs(float(w.attrib['yMin'])-y)<3],key=lambda w:float(w.attrib['xMin']))
                    texts=[w.text or '' for w in line]
                    try:
                        b=texts.index('Block');c=b+1
                        while c<len(texts) and (texts[c] in ('No',':','No:') or texts[c].strip()==':'):c+=1
                        block=texts[c]
                        dates=[re.fullmatch(r'(\d{1,2})-([A-Za-z]{3})-(\d{2,4})',t) for t in texts]
                        date=next(d for d in dates if d)
                        year=int(date[3]);year=year+2000 if year<100 else year
                        exam_date=f'{year:04}-{MONTHS[date[2].lower()]:02}-{int(date[1]):02}'
                        shift='morning' if 'AM' in texts else 'afternoon' if 'PM' in texts else ''
                        keys=[k for k in rooms if k[0]==number and k[1]==block and k[2] in texts and k[3]==exam_date and k[4]==shift]
                        if not keys:continue
                        if len(keys)!=1:raise ValueError('Source PDF block identity is ambiguous.')
                        key=keys[0]
                        # Fill only the retained session's original block header.
                        person=source_pages[key]
                        if person['subject_code'] not in texts:raise ValueError('Source PDF subject and revision metadata differ.')
                        r=line.index(word);colon=next(w for w in line[r+1:] if ':' in (w.text or ''))
                        x=float(colon.attrib['xMax'])+7;baseline=height-float(word.attrib['yMax'])+2
                        room=next(iter(rooms[key]))
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,20}',room):raise ValueError('Room number cannot be safely inserted into this PDF.')
                        font=min(10,max(5,(width-x-20)/(max(len(room),1)*0.65)))
                        draw.append(f'gsave 1 setgray {x:.2f} {baseline-2:.2f} {width-x-15:.2f} 13 rectfill 0 setgray /Helvetica-Bold findfont {font:.2f} scalefont setfont {x:.2f} {baseline:.2f} moveto ({ps_string(room)}) show grestore')
                        found.add(key)
                    except (ValueError,IndexError,StopIteration,KeyError) as exc:
                        if isinstance(exc,ValueError) and str(exc).startswith(('Source','Room number')):raise
                        continue
                if draw:
                    label=f'{"APPROVED" if approved else "DRAFT"} revision {revision_id}; page: {", ".join(sorted(labels[number]))}. Only linked sessions filled. Original roster; amendments: allocation report.'
                    draw.append(f'/Helvetica findfont 6 scalefont setfont 18 12 moveto ({ps_string(label)}) show')
                    commands.append(f'pg {number-1} eq {{ '+ '\n'.join(draw)+' } if')
            if found!=set(rooms):raise ValueError('Not every block room blank could be located. No partially filled PDF was returned.')
            overlay.write_text('<< /EndPage { /why exch def /pg exch def why 2 ne { gsave\n'+'\n'.join(commands)+'\ngrestore true } { false } ifelse } >> setpagedevice\n',encoding='ascii')
            result=subprocess.run([gs,'-dSAFER','-dBATCH','-dNOPAUSE','-sDEVICE=pdfwrite','-dCompatibilityLevel=1.7','-sOutputFile='+str(out),'-f',str(overlay),str(source)],capture_output=True,timeout=45)
            if result.returncode or not out.exists() or out.stat().st_size>20*1024*1024:raise ValueError('Could not create the filled original PDF. No source data was changed.')
            return out.read_bytes()
        except subprocess.TimeoutExpired as exc:raise ValueError('PDF room filling timed out. Try a smaller source PDF.') from exc
