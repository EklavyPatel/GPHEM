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


def main():
    from app import app
    from waitress import serve
    serve(app,**server_options(),max_request_body_size=app.config['MAX_CONTENT_LENGTH'])


if __name__=='__main__':
    main()
