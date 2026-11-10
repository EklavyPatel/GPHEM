# PostgreSQL migration implementation

Current deployment decision: start fresh in Supabase, with no SQLite data import.
See [RENDER_FREE_SETUP.md](RENDER_FREE_SETUP.md) for the current no-shell setup,
private administrator bootstrap and restricted runtime login. Backup/import
steps below are historical/optional tooling, not prerequisites for this fresh deployment.

Target: Supabase project `gphem` (`utlinkzhwzkkdtfyofuk`), private schema
`gphem`. Work belongs on `migration/supabase-postgresql`; Render continues
to deploy `main`. Do not merge, deploy, change Render variables, or import
production data without separate authorization.

## Database and application behavior

`migrations/001_postgresql.sql` creates a **new** schema, all 21 application
tables, their keys/checks/unique index, and one internal `schema_migrations`
table. An existing namespace causes the transaction to fail before any
existing table is touched. It inserts only the default singleton GTU settings.
No accounts, sessions, student records, or PDFs are seeded. Supabase-managed
schemas are left alone. Application tables have RLS enabled, with no browser
policies; schema/table/sequence access is revoked from PUBLIC and Supabase's
`anon` and `authenticated` roles. Do not expose this schema through the Data API.

The adapter retains exact text SIDs/JSON strings, integer flags, binary PDF
bytes, UTC timestamp strings and double-precision expiry values. Integer IDs
use bigint identities; `RETURNING id` supplies the legacy cursor contract.
Rows retain both positional and named access. Replacement inserts use explicit
conflict updates rather than delete/reinsert semantics. JSON publication checks
convert the `show_names` value to an integer before comparison.

Transactions take a transaction-scoped advisory write lock before reading
mutable state, retaining SQLite's write serialization for cooperating GPHEM
processes. Nested units use savepoints. Out-of-band SQL writers must observe
the same lock (`1196443717`); direct database administration is not serialized
by application code. Session expiry/revocation, CSRF and shared rate limits
retain the existing behavior. Session saving reuses the request connection to avoid exhausting the pool when all workers are busy. Request/session connections use a bounded pool
(default four), ten-second connection/checkout timeouts, and thirty-second
lock timeouts. Prepared statements are disabled for pooler compatibility.

Startup verifies the migration version, SHA-256 checksum, and complete table
inventory; it never performs PostgreSQL DDL or silently falls back to SQLite.
`DATABASE_URL` takes precedence over an explicitly configured legacy
`SEATING_DATABASE`. Without either setting, startup fails. Tests may explicitly
pass a temporary SQLite path to the application factory.

## Configuration for a later approved deployment

Install `requirements.txt`. Set `DATABASE_URL` through the host's secret
environment storage and `DATABASE_SCHEMA=gphem`. Do not commit a real URL.
Supabase OAuth/MCP access is not a PostgreSQL password. Obtain the actual
database or session-pooler connection string from the project's Connect dialog;
verify connectivity from Render before cutover. Remote connections require TLS;
use `sslmode=verify-full` and a trusted CA when supported, at minimum `require`.
Do not set these variables on production during preparation.

The schema owner can use these RLS-enabled tables. Before production, provision
a restricted backend login with schema usage, table/sequence privileges and
RLS policies limited to that role, then verify its access. Do not use a browser
key as a database password or grant browser roles access. A separate migration
credential is needed for schema provisioning/import sequence resets.

Provision a new namespace with `python -m scripts.migrate_postgresql`.
This command requires `DATABASE_URL` and optionally `DATABASE_SCHEMA`; it
refuses to reuse an existing schema. The confirmed Supabase namespace has
already been provisioned through MCP; do not run this against it again.

## Backup, approved import and rollback

The authenticated backup route exports all 21 tables from one read-only,
repeatable-read PostgreSQL snapshot into the existing SQLite v5 backup format.
It verifies SQLite integrity and foreign keys before returning the file. This
preserves the download contract and portable data restore tooling; it does
not back up PostgreSQL roles, policies, or server settings. Keep the versioned
SQL alongside backups. Backups include private records and password hashes;
store and transfer them privately. The exporter currently buffers data and the
download in memory, as the existing backup route did; size/load testing is
needed against the approved production snapshot.

No production data import has been executed. Only after the owner provides and
approves a verified production SQLite backup, record its SHA-256 and run:

```sh
python -m scripts.import_sqlite /private/approved.sqlite --approved-backup-sha256 APPROVED_SHA256
```

The importer reads a private copy, validates checksum, v5 schema, all 21 tables,
SQLite integrity and foreign keys, and refuses a nonempty PostgreSQL target or
changed default settings. It locks application tables, imports in dependency
order, compares every value, and resets identity sequences transactionally.
Any failure rolls back the PostgreSQL changes. It never changes the input
SQLite file. Local workspace records are not an approved production source.

Before cutover: stop production writes through an explicitly approved process,
take the final consistent SQLite backup, approve its checksum, verify import
and full application acceptance with the intended backend credentials, then
approve a separate deployment. Preserve the original SQLite database and its
backups. A rollback must account for any PostgreSQL writes after cutover;
simply restoring an older SQLite file would lose those later changes.

## Validation

Local legacy regression: 198 tests and 5 subtests passed; eight real PostgreSQL
integration tests skipped because the local driver could not be installed.
Local DNS cannot resolve GitHub/PyPI, so GitHub MCP is used for commits.
All 25 templates rendered successfully.

In Supabase PostgreSQL 17.11, an isolated `gphem_migration_test` namespace
successfully compiled 131 translated application SQL statements. Synthetic
tests exercised all 21 tables, unique/FK/check constraints, JSON publication
comparisons, conflict updates, Unicode/leading-zero identifiers, PDF bytea and
rollback. Synthetic records were rolled back. The test namespace remains
separate from `gphem`; only identity sequence values there advanced.

The GitHub Actions PostgreSQL job installs the driver, starts PostgreSQL 17 and
runs the entire application suite against a new unpredictable test schema for
each database fixture. It also tests concurrent rate limits, nested rollback,
generated IDs, saturated connection pools, portable backup/import roundtrip, exact data preservation,
sequence reset, startup checks and migration refusal on an existing schema.
At commit `a72387942b0f261a5472eb0bdf23c46f6b887867`, the PostgreSQL job passed 208 tests with two skips and five subtests. The two skips require private original PDF fixtures. The driver and pool packages installed successfully in CI. A subsequent pool saturation regression test validates that saving sessions reuses the request connection. See the latest Actions run for the final branch outcome.

Remaining production dependencies: approved production backup; securely
provisioned PostgreSQL credentials; restricted backend role/policies;
Render-to-Supabase TLS/reachability verification; production-size backup/import
timing; explicit cutover/deployment approval. No production environment settings
have been changed.
