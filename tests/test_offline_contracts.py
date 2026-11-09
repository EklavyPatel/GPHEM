"""Schema/OOXML checks that can run even when Flask and openpyxl are unavailable."""
import ast
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from engine import Preset

ROOT=Path(__file__).resolve().parent.parent


def test_database_statements_compile_against_schema():
    tree=ast.parse((ROOT/'services/db.py').read_text())
    schema=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                and any(isinstance(target,ast.Name) and target.id=='SCHEMA' for target in node.targets))
    db=sqlite3.connect(':memory:')
    db.executescript(schema)
    try:
        for path in [ROOT/'app.py',*(ROOT/'services').glob('*.py'),*(ROOT/'web').glob('*.py'),ROOT/'tests/conftest.py']:
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr not in ('execute','executemany') or not node.args:
                    continue
                try:sql=ast.literal_eval(node.args[0])
                except (ValueError,TypeError):continue
                if isinstance(sql,str) and sql.lstrip().upper().startswith(('SELECT','INSERT','UPDATE','DELETE')):
                    try:db.execute('EXPLAIN '+sql,[None]*sql.count('?'))
                    except sqlite3.Error as exc:raise AssertionError(f'{path}:{node.lineno}: {exc}') from exc
    finally:db.close()


def test_shipped_excel_artifacts_have_literal_text_sids():
    ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    for name in ['student_template.xlsx','example_students.xlsx']:
        with ZipFile(ROOT/'examples'/name) as archive:
            assert archive.testzip() is None
            root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            for cell in root.findall('.//x:c',ns):
                assert cell.attrib['t']=='inlineStr'
                assert cell.find('x:f',ns) is None
            if name=='student_template.xlsx':
                cell=root.find('.//x:c[@r="A2"]/x:is/x:t',ns)
                assert cell.text=='001'


def test_shipped_policy_documents_match_engine_schema():
    presets=json.loads((ROOT/'examples/rule-presets.json').read_text())
    for preset in presets.values():Preset.model_validate(preset)
