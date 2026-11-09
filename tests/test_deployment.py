"""Deployment entry point and persistent database initialization."""
import sys
from types import SimpleNamespace
from pathlib import Path
import pytest
from serve import main,server_options


def test_production_server_honors_assigned_port_and_application_upload_limit(monkeypatch):
    calls=[];application=SimpleNamespace(config={'MAX_CONTENT_LENGTH':6*1024*1024})
    monkeypatch.setitem(sys.modules,'app',SimpleNamespace(app=application))
    monkeypatch.setitem(sys.modules,'waitress',SimpleNamespace(serve=lambda app,**kwargs:calls.append((app,kwargs))))
    monkeypatch.setenv('PORT','9321');monkeypatch.setenv('WEB_THREADS','3');monkeypatch.setenv('BIND_HOST','0.0.0.0')
    monkeypatch.setattr('serve.bootstrap_admin', lambda app: None)
    main()
    assert calls==[(application,{'host':'0.0.0.0','port':9321,'threads':3,'max_request_body_size':6*1024*1024})]


@pytest.mark.parametrize('values',[{'PORT':'bad'},{'PORT':'0'},{'PORT':'70000'},{'WEB_THREADS':'0'},{'WEB_THREADS':'100'},{'BIND_HOST':' '}])
def test_invalid_server_configuration_fails_before_binding(values):
    with pytest.raises(ValueError):server_options(values)


def test_fresh_persistent_database_directory_is_created(tmp_path):
    from app import create_app
    from services.db import get_db
    path=tmp_path/'persistent'/'college'/'seating.sqlite'
    application=create_app({'TESTING':True,'DATABASE':str(path)})
    assert path.is_file()
    assert application.test_client().get('/health').json=={'status':'ok'}
    with application.app_context():assert get_db().execute('SELECT count(*) FROM admins').fetchone()[0]==0


def test_hosting_bootstrap_creates_hashed_admin_once(tmp_path):
    from app import create_app
    from services.db import get_db
    from serve import bootstrap_admin
    from werkzeug.security import check_password_hash
    application = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'db.sqlite')})
    settings = {'ADMIN_USERNAME': 'Test Admin', 'ADMIN_PASSWORD': 'test-only-long-password'}
    bootstrap_admin(application, settings)
    bootstrap_admin(application, {'ADMIN_USERNAME': 'Another Admin', 'ADMIN_PASSWORD': 'another-test-password'})
    with application.app_context():
        rows = get_db().execute('SELECT * FROM admins').fetchall()
        assert len(rows) == 1
        assert rows[0]['username'] == 'Test Admin'
        assert check_password_hash(rows[0]['password_hash'], settings['ADMIN_PASSWORD'])
        assert rows[0]['password_hash'] != settings['ADMIN_PASSWORD']
        assert get_db().execute("SELECT count(*) FROM audit WHERE action='create_admin'").fetchone()[0] == 1


@pytest.mark.parametrize('settings', [ {'ADMIN_USERNAME': 'Test Admin'}, {'ADMIN_PASSWORD': 'test-only-long-password'}, {'ADMIN_USERNAME': 'Test Admin', 'ADMIN_PASSWORD': 'short'}])
def test_hosting_bootstrap_requires_valid_credentials(tmp_path, settings):
    from app import create_app
    from services.db import get_db
    from serve import bootstrap_admin
    application = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'db.sqlite')})
    with pytest.raises(ValueError):
        bootstrap_admin(application, settings)
    with application.app_context():
        assert get_db().execute('SELECT count(*) FROM admins').fetchone()[0] == 0


def test_default_admin_is_created_without_hosting_variables_and_preserved(tmp_path):
    from app import create_app
    from services.db import get_db
    from serve import bootstrap_admin, DEFAULT_ADMIN_PASSWORD_HASH
    application = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'db.sqlite')})
    bootstrap_admin(application, {})
    with application.app_context():
        row = get_db().execute('SELECT * FROM admins').fetchone()
        assert row['username'] == 'naresh patel'
        assert row['password_hash'] == DEFAULT_ADMIN_PASSWORD_HASH
        get_db().execute("UPDATE admins SET password_hash='changed-hash'")
    bootstrap_admin(application, {})
    with application.app_context():
        assert get_db().execute('SELECT count(*) FROM admins').fetchone()[0] == 1
        assert get_db().execute('SELECT password_hash FROM admins').fetchone()[0] == 'changed-hash'
