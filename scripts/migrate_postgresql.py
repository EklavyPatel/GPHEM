"""Apply the reviewed schema to a NEW namespace; never alters existing tables.

Run: python -m scripts.migrate_postgresql
DATABASE_URL is supplied through the environment, never a CLI argument.
"""
import hashlib
import os
from services.postgres import MIGRATION, direct_connect, validate_schema


def provision(raw, schema='gphem'):
    schema = validate_schema(schema)
    script = MIGRATION.read_text().replace('"gphem"', '"' + schema + '"')
    with raw.transaction():
        # CREATE SCHEMA intentionally has no IF NOT EXISTS. An existing namespace
        # aborts the entire transaction before any existing object can be touched.
        raw.execute(script, prepare=False)
        raw.execute('INSERT INTO schema_migrations(version,checksum) VALUES(1,%s)',
                    (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),))


if __name__ == '__main__':
    db = direct_connect(os.environ['DATABASE_URL'], os.environ.get('DATABASE_SCHEMA', 'gphem'))
    try:
        provision(db.raw, os.environ.get('DATABASE_SCHEMA', 'gphem'))
        print('Created 21 application tables and schema migration metadata in a new private schema.')
    finally:
        db.close()
