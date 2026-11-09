"""Bounded, preview-first Excel imports. Numeric SIDs are rejected to avoid data loss."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from openpyxl import load_workbook

FIELDS = {'sid': 'SID', 'name': 'Student Name', 'branch': 'Branch', 'batch': 'Batch',
          'year': 'Year', 'session': 'Examination / Session'}
MAX_ROWS = 10000


def parse_students(data, filename, exam_id, exam_title, mapping=None, existing=()):
    if not filename.lower().endswith('.xlsx'):
        raise ValueError('Upload an .xlsx workbook. Legacy .xls and macro-enabled files are not supported.')
    if len(data) > 5 * 1024 * 1024:
        raise ValueError('Workbook exceeds the 5 MB limit.')
    try:
        with ZipFile(BytesIO(data)) as archive:
            files = archive.infolist()
            if len(files) > 1000 or sum(i.file_size for i in files) > 30*1024*1024:
                raise ValueError('Workbook expands beyond the safe processing limit.')
            if any(i.flag_bits & 1 for i in files):
                raise ValueError('Encrypted workbooks are not supported.')
            if any('vbaproject' in i.filename.lower() for i in files):
                raise ValueError('Workbooks containing macros are not supported.')
        book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('This file is not a readable .xlsx workbook.') from exc
    try:
        sheet = book.active
        if sheet.max_row and sheet.max_row > MAX_ROWS + 1:
            raise ValueError(f'Import at most {MAX_ROWS:,} student rows per workbook.')
        if sheet.max_column and sheet.max_column > 50:
            raise ValueError('Use a worksheet with at most 50 columns.')
        rows = sheet.iter_rows(max_col=50)
        header = next(rows, ())
        headings = [str(c.value).strip() if c.value is not None else '' for c in header]
        mapping = mapping or FIELDS
        indices = {}
        errors, records = [], []
        for field, default in FIELDS.items():
            wanted = mapping.get(field, default).strip()
            matches = [i for i, h in enumerate(headings) if h == wanted]
            if len(matches) != 1:
                errors.append({'row': 1, 'sid': '', 'message': f'Expected exactly one column named {wanted!r}.'})
            else:
                indices[field] = matches[0]
        if errors:
            return records, errors
        if len(set(indices.values())) != len(indices):
            return [], [{'row': 1, 'sid': '', 'message': 'Each field must map to a different column.'}]
        seen = set(existing)
        for row_number, cells in enumerate(rows, 2):
            if row_number > MAX_ROWS + 1:
                raise ValueError('Workbook exceeds the row limit.')
            if all(c.value is None for c in cells):
                continue
            record = {'row': row_number}
            row_errors = []
            for field, index in indices.items():
                cell = cells[index]
                value = cell.value
                if cell.data_type == 'f' or cell.data_type == 'e':
                    row_errors.append(f'{FIELDS[field]} contains a formula or Excel error; use a literal value.')
                if field == 'sid' and value is not None and not isinstance(value, str):
                    row_errors.append('SID must be stored as Excel Text; numeric cells can lose leading zeros.')
                if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
                    row_errors.append(f'{FIELDS[field]} has an unexpected data type.')
                text = '' if value is None else str(value)
                if field != 'sid':
                    text = text.strip()
                if not text.strip():
                    row_errors.append(f'{FIELDS[field]} is required.')
                if field == 'sid' and (text != text.strip() or len(text) > 100):
                    row_errors.append('SID must be 1–100 characters without surrounding whitespace.')
                if len(text) > 250 or any(ord(c) < 32 for c in text):
                    row_errors.append(f'{FIELDS[field]} contains invalid or excessively long text.')
                record[field] = text
            sid = record['sid']
            if sid in seen:
                row_errors.append('Duplicate SID within this examination (including already imported students).')
            seen.add(sid)
            if record['session'] not in (str(exam_id), exam_title):
                row_errors.append('Examination / Session must match this examination title or its ID.')
            errors.extend({'row': row_number, 'sid': sid, 'message': e} for e in row_errors)
            record['valid'] = not row_errors
            records.append(record)
        if not records:
            errors.append({'row': 2, 'sid': '', 'message': 'No student records found.'})
        return records, errors
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('The worksheet contains malformed or unsupported Excel content.') from exc
    finally:
        book.close()
