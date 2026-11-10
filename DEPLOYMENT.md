# Deploy GPHEM

For the current fresh Supabase PostgreSQL deployment on Render Free, follow
[RENDER_FREE_SETUP.md](RENDER_FREE_SETUP.md). It covers the one-time restricted
SQL login setup, private ADMIN_USERNAME / ADMIN_PASSWORD bootstrap, exact
Render variables, the Docker option with PDF tools, and approval boundaries.

Start command: `python serve.py` (the Dockerfile supplies this automatically).
An empty administrator table requires valid private bootstrap credentials.
Only a scrypt password hash is stored. Existing administrators are preserved.
No shared fallback credentials are provided.

The application schema is already provisioned in the confirmed Supabase
project. Startup verifies its version/checksum and does not run DDL. Do not add
schema reset/import/seed commands to a build or start command. This fresh path
requires no SQLite import or Render Shell access.

For data backup/import implementation details and historical migration work,
see [POSTGRESQL_MIGRATION.md](POSTGRESQL_MIGRATION.md). Local legacy SQLite use
requires an explicit SEATING_DATABASE path; never rely on a local SQLite file
for persistence on Render Free.
