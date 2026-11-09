"""Small original PDF fixture, containing invented enrollments only."""

def make_pdf(lines):
    commands=['BT /F1 10 Tf 40 800 Td']
    for index,line in enumerate(lines):
        if index:commands.append('0 -18 Td')
        safe=line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
        commands.append('('+safe+') Tj')
    commands.append('ET');stream='\n'.join(commands).encode('ascii')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 841] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
             b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
             b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=b'%PDF-1.4\n';offsets=[0]
    for index,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{index} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(data);data+=b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets[1:]:data+=f'{offset:010d} 00000 n \n'.encode()
    return data+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def report_lines(date='13-May-99',sizes=(3,2),subjects=None):
    result=['GUJARAT TECHNOLOGICAL UNIVERSITY','BLOCK ARRANGEMENT','Exam : Invented Examination','Center : 999 - TEST COLLEGE']
    for block,size in enumerate(sizes,1):
        code=subjects[block-1] if subjects else 'SUB'+str(block)
        result.append(f'Subject Code : {code} {date} AM Block No : {block} Room No :')
        result.append('Seat No Bench No Seat No Bench No Seat No Bench No')
        for start in range(1,size+1,3):
            result.append('     '.join(f'000{block:03}{i:06} {i}' for i in range(start,min(start+3,size+1))))
        result.append(f'Total : {size}')
    return result
