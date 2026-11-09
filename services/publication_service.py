"""The student release window is enforced on the server for every revision."""
from datetime import datetime,timedelta,timezone
from flask import current_app


def now_utc():
    clock=current_app.config.get('NOW_UTC')
    return clock() if clock else datetime.now(timezone.utc)


def release_at(starts_at):
    instant=datetime.fromisoformat(starts_at)
    if instant.tzinfo is None:
        raise ValueError('Examination start time must include its time zone.')
    return (instant.astimezone(timezone.utc)-timedelta(hours=24)).isoformat()


def configured_release(exam):
    from .db import get_db
    row=get_db().execute('SELECT release_at FROM publication_overrides WHERE exam_id=?',(exam['id'],)).fetchone()
    return row['release_at'] if row else release_at(exam['starts_at'])
