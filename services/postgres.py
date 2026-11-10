"""PostgreSQL DB-API boundary for the application's existing SQL contract.

Only the static json_extract expressions and qmark parameters used by GPHEM
are translated. Values always use driver binding, never SQL interpolation.
"""
import hashlib
import re
from pathlib import Path

IDENTITY_TABLES = frozenset(('admins', 'rooms', 'exams', 'revisions', 'presets',
                             'audit', 'generation_errors'))
SCHEMA_NAME = re.compile(r'^[a-z][a-z0-9_]{0,62}$')
MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '001_postgresql.sql'
LOCK_ID = 1196443717
WRITE_LOCK_SQL = 'SELECT pg_advisory_xact_lock(?)'


def validate_schema(name):
    if not SCHEMA_NAME.fullmatch(name) or name in {'public', 'auth', 'storage', 'extensions', 'realtime', 'vault'} or name.startswith('pg_'):
        raise ValueError('Use a dedicated private application schema.')
    return name


def translate(query):
    def json_expression(match):
        column, key = match.groups()
        value = f"({column}::jsonb ->> '{key}')"
        # SQLite extracts JSON numbers as numbers; PostgreSQL ->> returns text.
        return f'({value})::bigint' if key == 'show_names' else value
    query = re.sub(r"json_extract\(([a-z_][a-z0-9_.]*),'\$\.([a-z_]+)'\)", json_expression, query, flags=re.I)
    result, i, quote = [], 0, None
    while i < len(query):
        ch = query[i]
        if quote:
            result.append(ch)
            if ch == quote:
                if i + 1 < len(query) and query[i + 1] == quote:
                    result.append(query[i + 1]); i += 1
                else:
                    quote = None
        elif ch in "'\"":
            quote = ch; result.append(ch)
        elif ch == '?':
            result.append('%s')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


class Row(tuple):
    """Like sqlite3.Row: positional iteration plus named and mapping access."""
    def __new__(cls, names, values):
        row = super().__new__(cls, values)
        row._names = names
        return row

    def keys(self):
        return self._names

    def __getitem__(self, key):
        return super().__getitem__(self._names.index(key) if isinstance(key, str) else key)


def row_factory(cursor):
    names = tuple(column.name for column in cursor.description) if cursor.description else ()
    return lambda values: Row(names, values)


class Cursor:
    def __init__(self, cursor, generated=False):
        self._cursor = cursor
        self.lastrowid = cursor.fetchone()[0] if generated and cursor.rowcount else None

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)


class Connection:
    dialect = 'postgresql'

    def __init__(self, raw, pool=None):
        self.raw, self.pool = raw, pool
        self.closed = False

    @property
    def in_transaction(self):
        from psycopg.pq import TransactionStatus
        return self.raw.info.transaction_status != TransactionStatus.IDLE

    def execute(self, query, parameters=()):
        # Escape literal percent signs only when psycopg parameter binding is used.
        query = translate(query.replace('%', '%%') if parameters else query)
        match = re.match(r'\s*INSERT\s+INTO\s+([a-z_]+)\b', query, re.I)
        generated = bool(match and match[1].lower() in IDENTITY_TABLES and not re.search(r'\bRETURNING\b', query, re.I))
        if generated:
            query = query.rstrip().rstrip(';') + ' RETURNING id'
        return Cursor(self.raw.execute(query, parameters or None), generated)

    def executemany(self, query, parameters):
        cursor = self.raw.cursor()
        cursor.executemany(translate(query.replace('%', '%%')), parameters)
        return Cursor(cursor)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.in_transaction:
            self.raw.rollback()
        if self.pool:
            self.pool.putconn(self.raw)
        else:
            self.raw.close()


def configure(raw, schema):
    validate_schema(schema)
    raw.execute("SELECT set_config('search_path', %s, false)", (schema + ',pg_catalog',))
    raw.execute("SET TIME ZONE 'UTC'")
    raw.execute("SET lock_timeout = '30s'")
    raw.execute("SET statement_timeout = '120s'")


def connection_options(url):
    from psycopg.conninfo import conninfo_to_dict
    if not url.startswith(('postgresql://', 'postgres://')):
        raise ValueError('DATABASE_URL must be a PostgreSQL connection URL.')
    options = conninfo_to_dict(url)
    # Local PostgreSQL CI can explicitly disable TLS; remote targets require it.
    if options.get('host') not in ('localhost', '127.0.0.1', '::1'):
        if options.get('sslmode', 'require') not in ('require', 'verify-ca', 'verify-full'):
            raise ValueError('Remote PostgreSQL connections require TLS.')
        options.setdefault('sslmode', 'require')
    options.update(autocommit=True, row_factory=row_factory, connect_timeout=10,
                   prepare_threshold=None, application_name='gphem')
    return options


def direct_connect(url, schema='gphem'):
    import psycopg
    raw = psycopg.connect(**connection_options(url))
    try:
        configure(raw, schema)
    except BaseException:
        raw.close()
        raise
    return Connection(raw)


def initialize(app):
    """Check a pre-provisioned schema. Startup never applies PostgreSQL DDL."""
    from psycopg_pool import ConnectionPool
    schema = validate_schema(app.config['DATABASE_SCHEMA'])
    maximum = int(app.config['DATABASE_POOL_SIZE'])
    if not 2 <= maximum <= 20:
        raise ValueError('DATABASE_POOL_SIZE must be between 2 and 20.')
    pool = ConnectionPool(kwargs=connection_options(app.config['DATABASE']),
                          min_size=1, max_size=maximum, timeout=10, max_waiting=20,
                          configure=lambda raw: configure(raw, schema),
                          check=ConnectionPool.check_connection, open=False)
    try:
        pool.open(wait=True, timeout=15)
        with pool.connection() as raw:
            row = raw.execute('SELECT version, checksum FROM schema_migrations ORDER BY version DESC LIMIT 1').fetchone()
            expected = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
            if not row or row['version'] != 1 or row['checksum'] != expected:
                raise RuntimeError('PostgreSQL schema version/checksum mismatch. Apply the reviewed migration before startup.')
            actual = {r[0] for r in raw.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s', (schema,))}
            if actual != set(application_tables()) | {'schema_migrations'}:
                raise RuntimeError('PostgreSQL application table inventory mismatch.')
    except BaseException:
        pool.close()
        raise
    app.extensions['postgres_pool'] = pool


def application_tables():
    from .db import SCHEMA
    return re.findall(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)', SCHEMA)


def backup_to_sqlite(db, destination):
    """Export all application tables from one PostgreSQL MVCC snapshot.

    The portable SQLite artifact retains the existing download/restore contract;
    it is a data backup, not a backup of PostgreSQL roles or database settings.
    """
    import sqlite3
    from .db import SCHEMA
    target = sqlite3.connect(destination)
    try:
        target.executescript(SCHEMA)
        db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            for table in application_tables():
                cursor = db.execute(f'SELECT * FROM {table}')
                for row in cursor:
                    target.execute(f'INSERT INTO {table} VALUES({",".join("?" for _ in row)})', tuple(row))
            target.execute('PRAGMA user_version=5')
            target.commit()
        finally:
            db.rollback()
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or target.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Backup failed integrity validation.')
    finally:
        target.close()
