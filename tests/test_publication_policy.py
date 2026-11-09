from datetime import datetime,timedelta,timezone
import json
from services.publication_service import release_at
from services.db import get_db
from .conftest import seed,action,post,release_window,exam_state


def test_release_time_is_24_elapsed_hours_across_offsets():
    assert release_at('2099-01-10T09:30:00+05:30')=='2099-01-09T04:00:00+00:00'
    assert release_at('2099-01-10T08:00:00-04:00')=='2099-01-09T12:00:00+00:00'


def test_auto_approval_never_releases_early_even_with_forged_publication_state(app,admin):
    eid,_=seed(app)
    with app.app_context():get_db().execute('UPDATE exams SET auto_publish=1 WHERE id=?',(eid,))
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    state=exam_state(app,eid)
    assert state['publication']=='scheduled' and state['published_id']==state['approved_id']
    boundary=release_window(app,eid)
    app.config['NOW_UTC']=lambda:boundary-timedelta(microseconds=1)
    public=app.test_client()
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='00000').data
    with app.app_context():
        get_db().execute("UPDATE exams SET publication='manual',publish_at=? WHERE id=?",('2000-01-01T00:00:00+00:00',eid))
    assert b'Seat confirmed' not in post(public,'/',exam_id=eid,sid='00000').data
    app.config['NOW_UTC']=lambda:boundary
    assert b'Seat confirmed' in post(public,'/',exam_id=eid,sid='00000').data


def test_later_exam_time_cannot_leak_old_published_snapshot(app,admin):
    eid,_=seed(app);release_window(app,eid)
    assert action(admin,app,eid,'generate').status_code==302
    assert action(admin,app,eid,'approve').status_code==302
    assert action(admin,app,eid,'publication',action='publish').status_code==302
    assert b'Seat confirmed' in post(app.test_client(),'/',exam_id=eid,sid='00000').data
    with app.app_context():
        state=exam_state(app,eid);later=(datetime.fromisoformat(state['starts_at'])+timedelta(hours=2)).isoformat()
        get_db().execute('UPDATE exams SET starts_at=? WHERE id=?',(later,eid))
    assert b'Seat confirmed' not in post(app.test_client(),'/',exam_id=eid,sid='00000').data
