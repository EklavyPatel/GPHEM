import json
import re
import pytest


@pytest.fixture
def app(tmp_path):
    from app import create_app
    from werkzeug.security import generate_password_hash
    from services.db import get_db
    app=create_app({'TESTING':True,'DATABASE':str(tmp_path/'test.sqlite')})
    with app.app_context():
        get_db().execute('INSERT INTO admins(username,password_hash) VALUES(?,?)',
                         ('exam-admin',generate_password_hash('a-test-password-123!')))
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    with client.session_transaction() as session:
        if 'csrf' not in session:
            session['csrf']='test-csrf-token'
        return session['csrf']


def post(client,path,**data):
    return client.post(path,data={'csrf_token':csrf(client),**data})


@pytest.fixture
def admin(client):
    response=post(client,'/admin/login',username='exam-admin',password='a-test-password-123!')
    assert response.status_code==302
    return client


def seed(app, count=10, rules=None, rows=5, columns=3, seats_per_bench=1, states=None):
    from services.db import get_db
    with app.app_context():
        db=get_db()
        room=db.execute('INSERT INTO rooms(building,number,layout) VALUES(?,?,?)',
                        ('Science Block','101',json.dumps({'rows':rows,'columns':columns,
                        'seats_per_bench':seats_per_bench,'seats':states or {}}))).lastrowid
        exam=db.execute('INSERT INTO exams(title,starts_at,timezone,rules) VALUES(?,?,?,?)',
                        ('Semester Examination','2026-12-15T04:00:00+00:00','Asia/Kolkata',json.dumps(rules or []))).lastrowid
        db.execute('INSERT INTO exam_rooms VALUES(?,?)',(exam,room))
        db.executemany('INSERT INTO students VALUES(?,?,?,?,?,?)',
                       [(exam,f'{i:05}',f'Student {i}','ICT' if i%3 else 'ECE','2024' if i%2 else '2023','2') for i in range(count)])
        return exam,room


def exam_state(app,eid):
    from services.db import get_db
    with app.app_context():
        return dict(get_db().execute('SELECT * FROM exams WHERE id=?',(eid,)).fetchone())


def action(client,app,eid,endpoint,**data):
    return post(client,f'/admin/exams/{eid}/{endpoint}',version=exam_state(app,eid)['version'],**data)


def release_window(app,eid,seconds=0):
    """Move the test clock, never production exam timestamps, to the 24h boundary."""
    from datetime import datetime,timedelta
    start=datetime.fromisoformat(exam_state(app,eid)['starts_at'])
    instant=start-timedelta(hours=24)+timedelta(seconds=seconds)
    app.config['NOW_UTC']=lambda:instant
    return instant
