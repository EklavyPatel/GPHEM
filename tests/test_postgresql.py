"""Real PostgreSQL contracts; no production records or shared tables are used."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading
import pytest
from services.postgres import translate, Row


def test_parameters_and_row_contract():
    assert translate("SELECT '?', ? AS x, 'it''s ?' AS y") == "SELECT '?', %s AS x, 'it''s ?' AS y"
    assert translate("json_extract(r.exam_info,'$.show_names')=e.show_names") == "((r.exam_info::jsonb ->> 'show_names'))::bigint=e.show_names"
    row = Row(('sid', 'name'), ('001', 'Student'))
    assert row[0] == row['sid'] == '001'
    assert tuple(row) == ('001', 'Student')
    assert dict(row) == {'sid': '001', 'name': 'Student'}


def test_all_21_tables_and_private_namespace(pg_database):
    from services.postgres import direct_connect, application_tables
    url, schema = pg_database
    db = direct_connect(url, schema)
    try:
        tables = {row[0] for row in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=?', (schema,))}
        assert len(application_tables()) == 21
        assert tables == set(application_tables()) | {'schema_migrations'}
        assert db.execute('SELECT count(*) FROM pg_tables WHERE schemaname=? AND rowsecurity', (schema,)).fetchone()[0] == 21
        assert db.execute("SELECT NOT EXISTS(SELECT 1 FROM pg_namespace n, LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a WHERE n.nspname=? AND a.grantee=0 AND a.privilege_type='USAGE')", (schema,)).fetchone()[0] is True
    finally:
        db.close()


def test_nested_rollback_and_generated_ids(pg_database):
    import psycopg
    from services.db import transaction
    from services.postgres import direct_connect
    db = direct_connect(*pg_database)
    try:
        with transaction(db):
            first = db.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', ('001', 'hash')).lastrowid
            with pytest.raises(psycopg.IntegrityError):
                with transaction(db):
                    db.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', ('001', 'duplicate'))
            second = db.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', ('002', 'hash')).lastrowid
        assert first < second
        assert db.execute('SELECT count(*) FROM admins').fetchone()[0] == 2
        with pytest.raises(RuntimeError):
            with transaction(db):
                db.execute("DELETE FROM admins")
                raise RuntimeError('rollback')
        assert db.execute('SELECT count(*) FROM admins').fetchone()[0] == 2
    finally:
        db.close()


def test_backup_roundtrip_all_fields_and_identity(pg_database, tmp_path):
    from services.db import SCHEMA, transaction
    from services.postgres import direct_connect, backup_to_sqlite, application_tables
    from scripts.import_sqlite import import_backup
    from werkzeug.security import generate_password_hash
    source = tmp_path / 'approved.sqlite'
    db = sqlite3.connect(source)
    db.executescript(SCHEMA)
    db.execute('PRAGMA user_version=5')
    from services.gtu_engine import DEFAULT_CONFIG
    db.execute('INSERT INTO gtu_settings VALUES(1,?,1)', (json.dumps(DEFAULT_CONFIG),))
    db.execute('INSERT INTO admins VALUES(42,?,?)', ('test-admin', generate_password_hash('a-test-password-123!')))
    db.execute('INSERT INTO exams(id,title,starts_at,timezone) VALUES(77,?,?,?)', ('Test', '2026-12-15T04:00:00+00:00', 'Asia/Kolkata'))
    db.execute('INSERT INTO students VALUES(77,?,?,?,?,?)', ('000001', 'Unicode વિદ્યાર્થી', 'ICT', '2024', '2'))
    db.execute('INSERT INTO pdf_sources VALUES(?,?,?)', ('pdf-test', b'%PDF\x00\xff\x01', 1234567890.123456))
    db.execute('INSERT INTO exam_pdf_sources VALUES(77,?)', ('pdf-test',))
    db.commit(); db.close()
    target = direct_connect(*pg_database)
    try:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        counts = import_backup(source, digest, target)
        assert len(counts) == 21 and counts['students'] == 1
        assert target.execute('SELECT sid FROM students').fetchone()[0] == '000001'
        assert target.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', ('next', 'hash')).lastrowid == 43
        with pytest.raises(ValueError, match='not empty'):
            import_backup(source, digest, target)
        exported = tmp_path / 'roundtrip.sqlite'
        backup_to_sqlite(target, exported)
        copy = sqlite3.connect(exported)
        try:
            assert copy.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert copy.execute('PRAGMA foreign_key_check').fetchall() == []
            assert copy.execute('SELECT content FROM pdf_sources').fetchone()[0] == b'%PDF\x00\xff\x01'
            assert len(copy.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()) == 21
        finally:
            copy.close()
    finally:
        target.close()


def test_rate_limit_is_atomic_under_concurrent_requests(app):
    if 'postgres_pool' not in app.extensions:
        pytest.skip('PostgreSQL concurrency contract')
    from services.security import rate_limit
    from werkzeug.exceptions import TooManyRequests
    barrier = threading.Barrier(8)
    def attempt(_):
        with app.test_request_context('/'):
            barrier.wait(timeout=10)
            try:
                rate_limit('pg-concurrent-test', 2, 60, identity='test')
                return True
            except TooManyRequests:
                return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 2


def test_startup_refuses_unprovisioned_or_wrong_schema(pg_database):
    from app import create_app
    url, schema = pg_database
    with pytest.raises(Exception):
        create_app({'TESTING': True, 'DATABASE': url, 'DATABASE_SCHEMA': schema + '_missing'})
    from services.postgres import direct_connect
    db = direct_connect(url, schema)
    try:
        db.execute("UPDATE schema_migrations SET checksum='wrong'")
        with pytest.raises(RuntimeError, match='checksum'):
            create_app({'TESTING': True, 'DATABASE': url, 'DATABASE_SCHEMA': schema})
    finally:
        db.close()


def test_migration_refuses_existing_schema_without_changing_records(pg_database):
    import psycopg
    from services.postgres import direct_connect
    from scripts.migrate_postgresql import provision
    db = direct_connect(*pg_database)
    try:
        db.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', ('keep', 'hash'))
        with pytest.raises(psycopg.errors.DuplicateSchema):
            provision(db.raw, pg_database[1])
        assert db.execute('SELECT username FROM admins').fetchone()[0] == 'keep'
    finally:
        db.close()
