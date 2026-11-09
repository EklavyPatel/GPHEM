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
