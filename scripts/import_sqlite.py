"""Explicit, atomic import of an approved, verified SQLite v5 snapshot.

Not called by application startup, schema migration, CI, or deployment.
The required SHA-256 must identify the backup approved by the operator.
"""
import argparse
import hashlib
import os
from pathlib import Path
import sqlite3
from services.db import transaction
from services.postgres import application_tables, direct_connect, IDENTITY_TABLES


def import_backup(path, approved_sha256, target):
    # Copy bytes once so concurrent replacement of the source file cannot change
    # the data after the operator-approved checksum has been checked.
    import tempfile
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != approved_sha256.lower():
        raise ValueError('Backup SHA-256 does not match the approved snapshot.')
    with tempfile.TemporaryDirectory() as folder:
        snapshot = Path(folder) / 'approved.sqlite'
        snapshot.write_bytes(data)
        os.chmod(snapshot, 0o600)
        source = sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)
        try:
            if source.execute('PRAGMA user_version').fetchone()[0] != 5:
                raise ValueError('Only verified schema-v5 backups are supported.')
            if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or source.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Source snapshot failed integrity/foreign-key validation.')
            tables = application_tables()
            actual = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if actual != set(tables):
                raise ValueError('Snapshot must contain exactly the 21 application tables.')
            with transaction(target):
                # Block even non-cooperating SQL writers during emptiness checks
                # and import. The current implementation deliberately refuses to
                # merge any records into an already populated application schema.
                target.execute('LOCK TABLE ' + ','.join(tables) + ' IN EXCLUSIVE MODE')
                for table in tables:
                    if table != 'gtu_settings' and target.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:
                        raise ValueError('Target is not empty; import refused.')
                settings = source.execute('SELECT * FROM gtu_settings').fetchall()
                if len(settings) != 1 or settings[0][0] != 1:
                    raise ValueError('Snapshot must include the singleton GTU settings.')
                from services.gtu_engine import DEFAULT_CONFIG
                import json
                current = target.execute('SELECT * FROM gtu_settings').fetchall()
                if len(current) != 1 or current[0]['id'] != 1 or json.loads(current[0]['config']) != DEFAULT_CONFIG or current[0]['version'] != 1:
                    raise ValueError('Target GTU settings have changed; import refused.')
                counts = {}
                for table in tables:
                    columns = [r[1] for r in source.execute(f'PRAGMA table_info({table})')]
                    expected = [r[0] for r in target.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position', (table,))]
                    if columns != expected:
                        raise ValueError('Snapshot column contract mismatch: ' + table)
                    rows = source.execute(f'SELECT * FROM {table}').fetchall()
                    if table == 'gtu_settings':
                        target.execute('UPDATE gtu_settings SET config=?,version=? WHERE id=1', settings[0][1:])
                    elif rows:
                        target.executemany(f'INSERT INTO {table} VALUES({",".join("?" for _ in columns)})', rows)
                    # Compare every field (including hashes, JSON strings, text
                    # SIDs and PDF bytes), not just aggregate row counts.
                    saved = [tuple(row) for row in target.execute(f'SELECT * FROM {table}')]
                    if sorted(rows, key=repr) != sorted(saved, key=repr):
                        raise RuntimeError('Imported content verification failed: ' + table)
                    counts[table] = len(rows)
                for table in IDENTITY_TABLES:
                    # ALTER SEQUENCE RESTART is transactional; setval is not.
                    next_id = target.execute(f'SELECT COALESCE(MAX(id),0)+1 FROM {table}').fetchone()[0]
                    target.execute(f'ALTER TABLE {table} ALTER COLUMN id RESTART WITH {int(next_id)}')
                return counts
        finally:
            source.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup')
    parser.add_argument('--approved-backup-sha256', required=True)
    args = parser.parse_args()
    target = direct_connect(os.environ['DATABASE_URL'], os.environ.get('DATABASE_SCHEMA', 'gphem'))
    try:
        print(import_backup(args.backup, args.approved_backup_sha256, target))
    finally:
        target.close()
