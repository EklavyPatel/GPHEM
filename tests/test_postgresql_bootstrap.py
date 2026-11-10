"""Render's no-shell bootstrap, tested with a real restricted PostgreSQL login."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit, urlunsplit, quote
import uuid
import pytest


@pytest.fixture
def restricted_app(pg_database):
    from psycopg import sql
    from services.postgres import direct_connect
    from app import create_app
    url, schema = pg_database
    role = 'gphem_login_test_' + uuid.uuid4().hex
    password = secrets.token_urlsafe(32)
    owner = direct_connect(url, schema)
    script = (Path(__file__).resolve().parent.parent / 'deployment/runtime_role.sql').read_text()
    script = script.replace('"gphem"', '"' + schema + '"').replace('gphem_app', role)
    application = None
    try:
        owner.raw.execute(script, prepare=False)
        owner.raw.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
        parts = urlsplit(url)
        host = '[' + parts.hostname + ']' if ':' in parts.hostname else parts.hostname
        authority = quote(role, safe='') + ':' + quote(password, safe='') + '@' + host + (':' + str(parts.port) if parts.port else '')
        restricted_url = urlunsplit(parts._replace(netloc=authority))
        application = create_app({'TESTING': True, 'DATABASE': restricted_url, 'DATABASE_SCHEMA': schema,
                                  'SESSION_COOKIE_SECURE': True})
        yield application
    finally:
        if application:
            application.extensions['postgres_pool'].close()
        owner.raw.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
        owner.raw.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
        owner.close()


def test_private_bootstrap_persists_across_restart_login_logout_and_no_overwrite(restricted_app, capsys):
    from app import create_app
    from serve import bootstrap_admin
    from services.db import get_db
    from services.security import digest
    from werkzeug.security import check_password_hash
    app = restricted_app
    credentials = {'ADMIN_USERNAME': 'Synthetic Permanent Admin', 'ADMIN_PASSWORD': 'synthetic-only-long-passphrase'}
    bootstrap_admin(app, credentials)
    with app.app_context():
        row = dict(get_db().execute('SELECT * FROM admins').fetchone())
        assert row['username'] == credentials['ADMIN_USERNAME']
        assert row['password_hash'].startswith('scrypt:')
        assert row['password_hash'] != credentials['ADMIN_PASSWORD']
        assert check_password_hash(row['password_hash'], credentials['ADMIN_PASSWORD'])
        assert not check_password_hash(row['password_hash'], 'incorrect')
        assert get_db().execute('SELECT count(*) FROM admins').fetchone()[0] == 1
        assert credentials['ADMIN_PASSWORD'] not in str([tuple(r) for r in get_db().execute('SELECT * FROM audit')])
    client = app.test_client()
    origin = 'https://gphem.test'
    def post(browser, path, **data):
        with browser.session_transaction(base_url=origin) as session:
            session.setdefault('csrf', 'synthetic-csrf')
            token = session['csrf']
        return browser.post(path, base_url=origin, data={'csrf_token': token, **data})
    assert client.post('/admin/login', base_url=origin, data=credentials).status_code == 400
    client.get('/admin/login', base_url=origin)
    before = client.get_cookie('seating_session', domain='gphem.test').value
    assert post(client, '/admin/login', username=credentials['ADMIN_USERNAME'], password='incorrect').status_code == 200
    response = post(client, '/admin/login', username=credentials['ADMIN_USERNAME'], password=credentials['ADMIN_PASSWORD'])
    assert response.status_code == 302
    for flag in ('Secure', 'HttpOnly', 'SameSite=Lax'):
        assert flag in response.headers['Set-Cookie']
    token = client.get_cookie('seating_session', domain='gphem.test').value
    assert token != before
    with app.app_context():
        stored = get_db().execute('SELECT * FROM web_sessions WHERE token_hash=?', (digest(token),)).fetchone()
        assert stored and stored['token_hash'] != token
        assert credentials['ADMIN_PASSWORD'] not in stored['data']
    # Close the process's pool and recreate the app, retaining only PostgreSQL.
    app.extensions['postgres_pool'].close()
    restarted = create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'],
                            'DATABASE_SCHEMA': app.config['DATABASE_SCHEMA'], 'SESSION_COOKIE_SECURE': True})
    try:
        bootstrap_admin(restarted, {'ADMIN_USERNAME': 'Different Admin', 'ADMIN_PASSWORD': 'different-test-only-password'})
        bootstrap_admin(restarted, {})
        with restarted.app_context():
            assert dict(get_db().execute('SELECT * FROM admins').fetchone()) == row
            assert get_db().execute('SELECT count(*) FROM admins').fetchone()[0] == 1
        browser = restarted.test_client()
        browser.set_cookie('seating_session', token, domain='gphem.test', secure=True)
        assert browser.get('/admin', base_url=origin).status_code == 200
        assert post(browser, '/admin/logout').status_code == 302
        replay = restarted.test_client()
        replay.set_cookie('seating_session', token, domain='gphem.test', secure=True)
        assert replay.get('/admin', base_url=origin).status_code == 302
        with restarted.app_context():
            assert get_db().execute('SELECT 1 FROM web_sessions WHERE token_hash=?', (digest(token),)).fetchone() is None
            assert get_db().execute("SELECT count(*) FROM audit WHERE action='create_admin'").fetchone()[0] == 1
    finally:
        restarted.extensions['postgres_pool'].close()
    output = capsys.readouterr()
    assert credentials['ADMIN_PASSWORD'] not in output.out + output.err


def test_restricted_login_cannot_modify_schema_or_migration_metadata(restricted_app):
    import psycopg
    from services.db import get_db
    with restricted_app.app_context():
        db = get_db()
        row = db.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert tuple(row) == (False, False, False, False)
        assert db.execute('SELECT version FROM schema_migrations').fetchone()[0] == 1
        for statement in ('CREATE TABLE forbidden(id integer)', 'ALTER TABLE admins ADD COLUMN forbidden text',
                          'DROP TABLE admins', 'TRUNCATE admins', 'UPDATE schema_migrations SET version=99',
                          'SELECT * FROM pg_authid'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)
        assert db.execute('SELECT count(*) FROM admins').fetchone()[0] == 0


def test_concurrent_bootstrap_creates_one_administrator(restricted_app):
    from serve import bootstrap_admin
    from services.db import get_db
    barrier = threading.Barrier(2)
    def start(_):
        barrier.wait(timeout=10)
        bootstrap_admin(restricted_app, {'ADMIN_USERNAME': 'One Admin', 'ADMIN_PASSWORD': 'synthetic-only-long-password'})
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(start, range(2)))
    with restricted_app.app_context():
        assert get_db().execute('SELECT count(*) FROM admins').fetchone()[0] == 1
        assert get_db().execute("SELECT count(*) FROM audit WHERE action='create_admin'").fetchone()[0] == 1


def test_missing_private_credentials_create_no_administrator(restricted_app):
    from serve import bootstrap_admin
    from services.db import get_db
    with pytest.raises(ValueError, match='ADMIN_USERNAME'):
        bootstrap_admin(restricted_app, {})
    with restricted_app.app_context():
        assert get_db().execute('SELECT count(*) FROM admins').fetchone()[0] == 0
