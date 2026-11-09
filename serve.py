"""Production entry point: python serve.py (Waitress, using the host's PORT)."""
import os


def server_options(environ=None):
    environ=os.environ if environ is None else environ
    try:
        port=int(environ.get('PORT','8000'))
        threads=int(environ.get('WEB_THREADS','4'))
    except ValueError as exc:
        raise ValueError('PORT and WEB_THREADS must be integers.') from exc
    if not 1<=port<=65535:
        raise ValueError('PORT must be between 1 and 65535.')
    if not 1<=threads<=32:
        raise ValueError('WEB_THREADS must be between 1 and 32.')
    host=environ.get('BIND_HOST','0.0.0.0').strip()
    if not host:raise ValueError('BIND_HOST must not be empty.')
    return {'host':host,'port':port,'threads':threads}


DEFAULT_ADMIN_USERNAME = "naresh patel"
DEFAULT_ADMIN_PASSWORD_HASH = 'scrypt:32768:8:1$1AKMyMJBaZILfFIU$40abb7c09a53a4bbea531798be7095a8ca5848adca13b085eb763096d161b2c454b6968b4479e6f31a732a5862352697c98d3348130e00b0acb45f1be68a133c'


def bootstrap_admin(app, environ=None):
    """Create the first administrator from hosting configuration or project defaults."""
    environ = os.environ if environ is None else environ
    username = environ.get('ADMIN_USERNAME', '')
    password = environ.get('ADMIN_PASSWORD', '')
    use_defaults = not username and not password
    if use_defaults:
        username = DEFAULT_ADMIN_USERNAME
    from services.db import transaction
    from werkzeug.security import generate_password_hash
    with app.app_context(), transaction() as db:
        if db.execute('SELECT 1 FROM admins LIMIT 1').fetchone():
            return
        if not username.strip() or len(username) > 100 or (not use_defaults and not 12 <= len(password) <= 1024):
            raise ValueError('Set ADMIN_USERNAME (1–100 characters) and ADMIN_PASSWORD (12–1024 characters) in the hosting environment.')
        uid = db.execute(
            'INSERT INTO admins(username,password_hash) VALUES(?,?)',
            (username.strip(), DEFAULT_ADMIN_PASSWORD_HASH if use_defaults else generate_password_hash(password)),
        ).lastrowid
        db.execute(
            'INSERT INTO audit(admin_id,action,detail) VALUES(?,?,?)',
            (uid, 'create_admin', 'Hosting environment setup'),
        )


def main():
    from app import app
    from waitress import serve
    bootstrap_admin(app)
    serve(app,**server_options(),max_request_body_size=app.config['MAX_CONTENT_LENGTH'])


if __name__=='__main__':
    main()
