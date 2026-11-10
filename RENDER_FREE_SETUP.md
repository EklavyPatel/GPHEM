# Fresh Supabase deployment on Render Free

This path starts with an empty GPHEM database. Do not import any SQLite backup.
Target: project `gphem` / `utlinkzhwzkkdtfyofuk`, application schema `gphem`.
The 21 application tables and migration metadata have already been created;
there are no administrators. Do not run the schema-creation migration again.

## One permanent administrator, no Render Shell

The runtime entry point is `python serve.py`. Before starting Waitress, it
opens a PostgreSQL write transaction and checks whether any administrator exists.
On an empty database it requires `ADMIN_USERNAME` and `ADMIN_PASSWORD` from
the private process environment, hashes the password with scrypt, and inserts
one administrator plus a credential-free audit event. A failed bootstrap stops
the server before it accepts HTTP requests. There is no fallback account.

Username: 1–100 characters, no leading/trailing whitespace or control characters.
Password: 12–1024 characters; use a unique password from your password manager.
The actual values belong only in Render's Environment settings, never GitHub.
Only the password hash enters the application database. Passwords are not
recorded in sessions, audit details, or bootstrap output.

The account has no expiry. Its row and sessions live in Supabase, so replacing
the Render container does not replace the account. Competing starts serialize
on the application's transaction lock. If any administrator already exists,
startup does nothing to accounts, even when environment credentials differ or
have been removed. Changing `ADMIN_PASSWORD` later is **not** a password reset.
Do not run a reset, seed, migration, or create-admin command in the build/start
command. No Render Shell, disk, one-off job, or paid pre-deploy command is used.

## Set up a restricted database login first

1. In the confirmed Supabase project's SQL Editor, run
   [`deployment/runtime_role.sql`](deployment/runtime_role.sql) as the database
   owner. It creates the new `gphem_app` database login and explicitly grants
   app-table DML, sequence usage and schema-version reads. RLS policies apply
   only to that backend role. The script refuses to reuse an existing role.
   It does not create an application administrator and contains no password.
2. Set a separate, strong **database login password** privately in Supabase SQL
   Editor: `ALTER ROLE gphem_app PASSWORD 'YOUR_PRIVATE_DATABASE_PASSWORD';`.
   Never commit a filled-in copy. This is different from `ADMIN_PASSWORD`.
3. In Supabase, open **Connect → Session pooler** and copy the actual host and
   port. Use `gphem_app.utlinkzhwzkkdtfyofuk` as the pooled username and the
   password from step 2. URL-encode reserved password characters. Use database
   `postgres` and `sslmode=require` (or verified TLS with an appropriate CA).

The resulting shape is:

```text
postgresql://gphem_app.utlinkzhwzkkdtfyofuk:URL_ENCODED_DATABASE_PASSWORD@ACTUAL_SESSION_POOLER_HOST:5432/postgres?sslmode=require
```

Take the pooler hostname from Connect; it cannot safely be inferred from the
project's region. Do not use a Supabase API key or OAuth token as the password.
Use **session** mode on port 5432: GPHEM sets persistent search_path/timezone
settings on its pooled connections. Transaction mode on 6543 is not the
supported deployment configuration. Direct connections require working IPv6
or Supabase's IPv4 option; session pooling provides the IPv4 alternative.
If network restrictions are enabled in Supabase, allow the Render service's
documented outbound addresses before deploying.

The runtime login is not a database owner, superuser, role administrator, or RLS
bypass role. It cannot create/alter/drop/truncate application tables or edit
migration metadata. `anon`/`authenticated` retain no access to the private
application schema; do not expose it through the Data API. All end-user
authorization continues to run in Flask, over this trusted backend connection.
Inherited database-wide PUBLIC grants are a Supabase/project concern; this
setup grants no access to unrelated objects and changes no other roles.

## Prepare Render without starting a deployment

First disable automatic deployment on the existing service **when you approve
that configuration change**, because merging to its linked `main` branch can
otherwise deploy immediately. No agent has changed that setting. Do not merge
until you are ready to approve deployment, or until auto-deploy is safely off.

Recommended no-shell runtime: the checked-in **Dockerfile**. It installs
Poppler, Ghostscript and Python dependencies at build time, runs as a non-root
user, and starts `python serve.py`. It does not connect to the database or
create accounts during the image build.

After deployment approval, create a **Free Docker Web Service** from the repo
with Dockerfile path `./Dockerfile`, context `.`, and no Docker Command override
(the image CMD starts Waitress). Native Python services do not automatically
switch to Docker when a Dockerfile is committed. Use a separate Docker service
if the existing runtime cannot be changed; retain the current service until the
replacement is verified. No existing service needs to be deleted for testing.

If retaining the current native Python service, build with
`python -m pip install -r requirements.txt` and start with `python serve.py`,
but full PDF functionality additionally requires `pdftotext`, `pdfinfo` and
`gs` in the runtime. `system-packages.txt` alone does not install them. Their
presence on the current native instance has not been verified; the container
build removes that uncertainty without needing Shell access.

## Exact environment variables

Enter these in Render's Environment settings. Values below marked private or
actual must be supplied by you, not copied literally. For an existing service,
choose **Save only** while preparing; the other save options can deploy.

| Key | Value |
| --- | --- |
| `DATABASE_URL` | Your private restricted-role **session-pooler** URL above |
| `DATABASE_SCHEMA` | `gphem` |
| `DATABASE_POOL_SIZE` | `4` |
| `ADMIN_USERNAME` | Your fixed private username |
| `ADMIN_PASSWORD` | Your fixed private password, 12–1024 characters |
| `COOKIE_SECURE` | `1` |
| `TRUSTED_HOSTS` | Actual service hostname only, e.g. `gphem.onrender.com`; comma-separate any custom domain |
| `WEB_THREADS` | `2` |

Optional: `COLLEGE_NAME=GOVERNMENT POLYTECHNIC HIMMATNAGAR`,
`BIND_HOST=0.0.0.0` (already the default). Render supplies `PORT`; do not set it
merely to match a hardcoded value. Remove legacy `SEATING_DATABASE` when you
approve production configuration, so the intended PostgreSQL setup is clear.
No Flask `SECRET_KEY` is needed by the opaque database-backed session system.
Actual secrets are supplied at runtime, never Docker build arguments.

Set the HTTP health-check path to `/health` when deployment is approved. The
app queries PostgreSQL there and returns `{"status":"ok"}` when connected.

## Merge, deploy, and verify only after approval

1. Confirm all migration-branch CI jobs are green, including restricted-login
   PostgreSQL tests and the container smoke test. Review/merge the branch only
   after explicit approval; auto-deploy on `main` must be accounted for.
2. Once the restricted login/password, session URL, service runtime and private
   environment values are ready, approve one deployment of the reviewed code.
   With Docker, leave build/start command overrides unset. With native Python,
   use the commands above and verify the PDF runtime dependency separately.
3. Wait for a live deployment and successful `/health`; check runtime logs for
   connection/bootstrap errors without publishing the environment values.
4. At `/admin/login`, verify your fixed credentials, rejection of a wrong
   password, logout, and rejection of a logged-out session. The database should
   contain one administrator with a `scrypt:` hash, never plaintext.
5. Approve a restart/redeploy and verify the same login and existing data still
   work. PostgreSQL integration tests simulate this by closing all application
   connections and constructing a fresh application instance against the same
   database. Live Render connectivity/restart verification remains a deployment
   acceptance step; it has not been claimed from CI alone.

The Free service can sleep and cold-start; persistent credentials do not imply
always-on hosting. Account durability depends on keeping the Supabase project
and database intact. No old SQLite data needs to be copied or deleted.

## References

- [Render Free limits](https://render.com/docs/free)
- [Render environment save options](https://render.com/docs/configure-environment-variables)
- [Render Docker deployment](https://render.com/docs/docker)
- [Render automatic deployments](https://render.com/docs/deploys)
- [Supabase connection methods, pooler usernames and TLS](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase database roles](https://supabase.com/docs/guides/database/postgres/roles)
