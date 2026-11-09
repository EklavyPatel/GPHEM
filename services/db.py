"""SQLite persistence. Every state transition uses an explicit write transaction."""
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from flask import current_app, g

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS admins (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS web_sessions (
 token_hash TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits (
 key TEXT PRIMARY KEY, count INTEGER NOT NULL, resets REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rooms (
 id INTEGER PRIMARY KEY, building TEXT NOT NULL, number TEXT NOT NULL,
 layout TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, UNIQUE(building,number));
CREATE TABLE IF NOT EXISTS exams (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, starts_at TEXT NOT NULL, timezone TEXT NOT NULL,
 show_names INTEGER NOT NULL DEFAULT 0, rules TEXT NOT NULL DEFAULT '[]', seed INTEGER NOT NULL DEFAULT 42,
 version INTEGER NOT NULL DEFAULT 1, draft_id INTEGER, approved_id INTEGER, published_id INTEGER,
 publication TEXT NOT NULL DEFAULT 'off' CHECK(publication IN ('off','manual','scheduled')),
 publish_at TEXT, mode TEXT NOT NULL DEFAULT 'seating', shift TEXT NOT NULL DEFAULT '',
 gtu_date TEXT NOT NULL DEFAULT '', gtu_config TEXT NOT NULL DEFAULT '{}',
 gtu_disabled TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT 'spreadsheet',
 historical INTEGER NOT NULL DEFAULT 0, auto_publish INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS unique_gtu_session ON exams(gtu_date,shift) WHERE mode='gtu';
CREATE TABLE IF NOT EXISTS exam_rooms (
 exam_id INTEGER NOT NULL REFERENCES exams(id), room_id INTEGER NOT NULL REFERENCES rooms(id),
 PRIMARY KEY(exam_id,room_id));
CREATE TABLE IF NOT EXISTS students (
 exam_id INTEGER NOT NULL REFERENCES exams(id), sid TEXT NOT NULL, name TEXT NOT NULL,
 branch TEXT NOT NULL, batch TEXT NOT NULL, year TEXT NOT NULL,
 PRIMARY KEY(exam_id,sid));
CREATE TABLE IF NOT EXISTS imports (
 id TEXT PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id), admin_id INTEGER NOT NULL REFERENCES admins(id),
 version INTEGER NOT NULL, records TEXT NOT NULL, errors TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id), input_version INTEGER NOT NULL,
 config TEXT NOT NULL, preview TEXT NOT NULL, metadata TEXT NOT NULL, exam_info TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, release_at TEXT);
CREATE TABLE IF NOT EXISTS assignments (
 revision_id INTEGER NOT NULL REFERENCES revisions(id), sid TEXT NOT NULL, seat_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(revision_id,sid), UNIQUE(revision_id,seat_id));
CREATE TABLE IF NOT EXISTS presets (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, rules TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, admin_id INTEGER REFERENCES admins(id), action TEXT NOT NULL,
 detail TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS generation_errors (
 id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id), message TEXT NOT NULL,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS gtu_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS gtu_students (
 exam_id INTEGER NOT NULL, enrollment_no TEXT NOT NULL, exam_date TEXT NOT NULL,
 session TEXT NOT NULL, block_no TEXT NOT NULL, subject_code TEXT NOT NULL,
 subject_name TEXT NOT NULL, uploaded_at REAL NOT NULL, pdf_bench INTEGER, pdf_page INTEGER,
 PRIMARY KEY(exam_id,enrollment_no),
 FOREIGN KEY(exam_id,enrollment_no) REFERENCES students(exam_id,sid));
CREATE TABLE IF NOT EXISTS pdf_imports (
 id TEXT PRIMARY KEY, admin_id INTEGER NOT NULL REFERENCES admins(id), created REAL NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS emergency_admissions (
 exam_id INTEGER NOT NULL, sid TEXT NOT NULL, reason TEXT NOT NULL, admin_id INTEGER NOT NULL REFERENCES admins(id),
 created REAL NOT NULL, PRIMARY KEY(exam_id,sid),
 FOREIGN KEY(exam_id,sid) REFERENCES students(exam_id,sid));
CREATE TABLE IF NOT EXISTS pdf_sources (
 id TEXT PRIMARY KEY, content BLOB NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS exam_pdf_sources (
 exam_id INTEGER PRIMARY KEY REFERENCES exams(id), source_id TEXT NOT NULL REFERENCES pdf_sources(id));
CREATE TABLE IF NOT EXISTS publication_overrides (
 exam_id INTEGER PRIMARY KEY REFERENCES exams(id), release_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS emergency_seats (
 exam_id INTEGER NOT NULL, sid TEXT NOT NULL, seat_id TEXT NOT NULL,
 PRIMARY KEY(exam_id,sid), UNIQUE(exam_id,seat_id),
 FOREIGN KEY(exam_id,sid) REFERENCES students(exam_id,sid));
'''


def connect(path):
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=30000')
    return db


def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config['DATABASE'])
    return g.db


@contextmanager
def transaction(db=None):
    db = db or get_db()
    if db.in_transaction:
        import secrets
        name='nested_'+secrets.token_hex(8)
        db.execute(f'SAVEPOINT {name}')
        try:
            yield db
        except BaseException:
            db.execute(f'ROLLBACK TO {name}')
            db.execute(f'RELEASE {name}')
            raise
        else:
            db.execute(f'RELEASE {name}')
        return
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


def init_db(app):
    """Upgrade v1 in place with a consistent backup; never rewrite saved revisions."""
    import json
    import tempfile
    from .gtu_engine import DEFAULT_CONFIG
    db = connect(app.config['DATABASE'])
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > 5:
            raise RuntimeError('This database requires a newer application version.')
        existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='exams'").fetchone()
        backup_name = None
        if existing and version < 5:
            path = Path(app.config['DATABASE'])
            fd, backup_name = tempfile.mkstemp(prefix=path.stem+('-before-gtu-' if version<2 else '-before-pdf-'),suffix='.sqlite',dir=path.parent)
            os.close(fd)
            target = sqlite3.connect(backup_name)
            try:
                db.backup(target)
            finally:
                target.close()
        db.execute('PRAGMA journal_mode=WAL')
        with transaction(db):
            if existing:
                columns = {r['name'] for r in db.execute('PRAGMA table_info(exams)')}
                additions = {
                    'mode': "TEXT NOT NULL DEFAULT 'seating'", 'shift': "TEXT NOT NULL DEFAULT ''",
                    'gtu_date': "TEXT NOT NULL DEFAULT ''", 'gtu_config': "TEXT NOT NULL DEFAULT '{}'",
                    'gtu_disabled': "TEXT NOT NULL DEFAULT '[]'",
                    'source': "TEXT NOT NULL DEFAULT 'spreadsheet'", 'historical': 'INTEGER NOT NULL DEFAULT 0',
                    'auto_publish': 'INTEGER NOT NULL DEFAULT 0'}
                for name, definition in additions.items():
                    if name not in columns:
                        db.execute(f'ALTER TABLE exams ADD COLUMN {name} {definition}')
            for statement in SCHEMA.split(';'):
                if statement.strip() and not statement.strip().upper().startswith('PRAGMA'):
                    db.execute(statement)
            for table, additions in {
                'revisions': {'release_at':'TEXT'},
                'gtu_students': {'pdf_bench':'INTEGER','pdf_page':'INTEGER'}
            }.items():
                columns={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
                for name, definition in additions.items():
                    if name not in columns:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            from .publication_service import release_at
            for r in db.execute('SELECT r.id,r.exam_info,e.starts_at,e.historical FROM revisions r JOIN exams e ON e.id=r.exam_id WHERE r.release_at IS NULL').fetchall():
                try:
                    info=json.loads(r['exam_info'])
                    if r['historical'] or info.get('historical'):
                        continue
                    when=release_at(info.get('starts_at',r['starts_at']))
                except (ValueError,TypeError):
                    continue  # A corrupt date fails closed: NULL is never published.
                db.execute('UPDATE revisions SET release_at=? WHERE id=?',(when,r['id']))
            db.execute('INSERT OR IGNORE INTO gtu_settings(id,config) VALUES(1,?)', (json.dumps(DEFAULT_CONFIG),))
            if backup_name:
                db.execute("INSERT INTO audit(action,detail) VALUES('schema_migration',?)",
                           (f'v{version} to v5; backup: '+Path(backup_name).name,))
            db.execute('PRAGMA user_version=5')
    finally:
        db.close()


def close_db(exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def cleanup_pdf_storage():
    """Retain sources referenced by immutable revisions, sessions or live previews."""
    import time
    db=get_db()
    db.execute('DELETE FROM pdf_imports WHERE created<?',(time.time()-1800,))
    db.execute('''DELETE FROM pdf_sources WHERE
        NOT EXISTS (SELECT 1 FROM exam_pdf_sources e WHERE e.source_id=pdf_sources.id)
        AND NOT EXISTS (SELECT 1 FROM revisions r WHERE json_extract(r.metadata,'$.source_pdf')=pdf_sources.id)
        AND NOT EXISTS (SELECT 1 FROM pdf_imports p WHERE p.id=pdf_sources.id)''')


def audit(action, detail, admin_id=None):
    from flask import session
    get_db().execute('INSERT INTO audit(admin_id,action,detail) VALUES(?,?,?)',
                     (admin_id or session.get('admin_id'), action, str(detail)))
