"""Opaque, revocable server-side sessions, CSRF, and shared SQLite rate limits."""
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from functools import wraps
from flask import abort, g, redirect, request, session, url_for
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
from .db import connect, get_db, transaction


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ServerSession(CallbackDict, SessionMixin):
    def __init__(self, data=None, token=None, is_new=True):
        super().__init__(data, lambda s: setattr(s, 'modified', True))
        self.token = token or secrets.token_urlsafe(32)
        self.modified = False
        self.is_new = is_new


class SQLiteSessions(SessionInterface):
    def open_session(self, app, req):
        token = req.cookies.get(self.get_cookie_name(app), '')
        if len(token) < 100 and token:
            db = connect(app.config['DATABASE'])
            try:
                row = db.execute('SELECT data FROM web_sessions WHERE token_hash=? AND expires>?',
                                 (digest(token), time.time())).fetchone()
            finally:
                db.close()
            if row:
                return ServerSession(json.loads(row['data']), token, is_new=False)
        return ServerSession()

    def save_session(self, app, sess, response):
        if not sess.modified:
            return
        db = connect(app.config['DATABASE'])
        try:
            with transaction(db):
                db.execute('DELETE FROM web_sessions WHERE expires<?', (time.time(),))
                if sess:
                    ttl = app.config['SESSION_TTL']
                    if sess.is_new:
                        db.execute('INSERT INTO web_sessions VALUES(?,?,?)',
                                   (digest(sess.token), json.dumps(dict(sess)), time.time() + ttl))
                    else:
                        updated = db.execute('UPDATE web_sessions SET data=?,expires=? WHERE token_hash=? AND expires>?',
                                             (json.dumps(dict(sess)), time.time()+ttl, digest(sess.token), time.time())).rowcount
                        if not updated:
                            # A concurrent logout or password reset revoked this session. Do not resurrect it.
                            response.delete_cookie(self.get_cookie_name(app))
                            return
                else:
                    db.execute('DELETE FROM web_sessions WHERE token_hash=?', (digest(sess.token),))
        finally:
            db.close()
        if sess:
            response.set_cookie(self.get_cookie_name(app), sess.token, httponly=True,
                                secure=app.config['SESSION_COOKIE_SECURE'], samesite='Lax',
                                expires=datetime.fromtimestamp(time.time()+app.config['SESSION_TTL'], timezone.utc))
        else:
            response.delete_cookie(self.get_cookie_name(app))
        response.vary.add('Cookie')


def rotate_session():
    get_db().execute('DELETE FROM web_sessions WHERE token_hash=?', (digest(session.token),))
    session.clear()
    session.token = secrets.token_urlsafe(32)
    session.is_new = True
    session['csrf'] = secrets.token_urlsafe(32)


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def csrf_protect():
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        supplied = request.form.get('csrf_token', '') or request.headers.get('X-CSRF-Token', '')
        expected = session.get('csrf', '')
        if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
            abort(400, 'The form expired or the security token is missing. Reload the page and try again.')


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        admin_id = session.get('admin_id')
        g.admin = get_db().execute('SELECT id,username FROM admins WHERE id=?', (admin_id,)).fetchone()
        if g.admin is None:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def rate_limit(namespace, maximum, seconds, identity=None):
    # Do not trust spoofable X-Forwarded-For headers. Configure a trusted proxy explicitly.
    key = digest(namespace + ':' + (identity or request.remote_addr or 'local'))
    now = time.time()
    with transaction() as db:
        db.execute('DELETE FROM rate_limits WHERE resets<?', (now,))
        row = db.execute('SELECT count,resets FROM rate_limits WHERE key=?', (key,)).fetchone()
        allowed = not row or row['count'] < maximum
        if allowed:
            db.execute('INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                       (key, now + seconds))
    if not allowed:
        abort(429, 'Too many attempts. Please wait before trying again.')
