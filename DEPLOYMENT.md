# Deploy GPHEM

This repository contains a Python/Flask server. GitHub stores the source; **GitHub Pages cannot run this application**, because Pages serves static HTML/CSS/JavaScript. Use a Python application host or a college server with persistent writable storage and HTTPS. The repository upload alone does not deploy a live website.

## Hosting settings

| Setting | Value |
| --- | --- |
| Runtime | Python 3.12 or newer (3.12 is selected in `.python-version`) |
| Build command | `python -m pip install -r requirements.txt` |
| Start command | `python serve.py` |
| WSGI server | Waitress (included in runtime dependencies) |
| Port | Host-provided `PORT`; defaults to 8000 |
| Bind address | `BIND_HOST`; defaults to `0.0.0.0` |
| Health check | `/health` |
| System packages | `poppler-utils` and `ghostscript` |
| Database | SQLite file on a persistent local disk |

`Procfile` supplies the start command for hosts that recognize that format. `system-packages.txt` lists required OS packages; it is a deployment reference, not a promise that every host installs them automatically. Configure your provider's package-install step or provision them on the server. No Docker, cloud database or Node/npm build is required.

PDF imports need `pdftotext` and `pdfinfo` from Poppler. Original-PDF room-number filling also needs Ghostscript (`gs`). Excel imports/exports and allocation use the Python requirements. A Linux server administrator can install the PDF tools with:

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils ghostscript
```

## Persistent data and environment

Create/attach a persistent local disk and set the database path to a file **inside that mount**, for example:

```text
SEATING_DATABASE=/var/data/gphem/seating.sqlite
COOKIE_SECURE=1
TRUSTED_HOSTS=exam.example.edu
COLLEGE_NAME=GOVERNMENT POLYTECHNIC HIMMATNAGAR
WEB_THREADS=4
```

Replace the example mount/hostname with the ones supplied by your host. The application creates a missing database directory and initializes the schema. `TRUSTED_HOSTS` accepts comma-separated hostnames without `https://` or paths; include any hostnames used by health checks if your provider requires them. `COOKIE_SECURE=1` requires HTTPS: use `0` only for local HTTP testing. Environment variables are configured in the hosting dashboard or process manager, **not committed into GitHub**. The application does not automatically load `.env` files.

Keep one application instance connected to the local SQLite database. Do not place SQLite on a disposable deployment filesystem or run several replicas against separate files; otherwise users can lose data or see inconsistent sessions. This database includes accounts, student records, original uploaded PDFs, revisions and publication state. Do not create/reset it at every build. Its pre-migration backups are saved beside it, so provision disk space for those too.

Waitress is the production entry point, behind your host's HTTPS termination/reverse proxy. Client-supplied proxy headers are not blindly trusted. If you add a trusted-proxy configuration later, restrict it to the real proxy topology; shared-IP rate ceilings and campus release traffic still need checking for the deployment.

## First administrator

Open a shell/SSH session on the host using the **same persistent database environment** as the web process:

```bash
flask --app app create-admin
```

Enter your username and a unique password when prompted. There are no default production credentials. Do not put the password in a GitHub file, public build log or command-line argument. Choose hosting with an authenticated shell/one-off interactive process for this step. Password recovery is `flask --app app reset-password`; it revokes browser sessions.

A fresh deployment starts with an empty database. Import the required college data through the private administrator UI. To migrate an existing installation, use an authenticated private transfer of a consistent SQLite backup while the destination server is stopped; **never upload that backup to the repository**. See README's backup/restore instructions.

## Verify deployment

1. Confirm `/health` returns `{"status":"ok"}` over HTTPS.
2. Sign in at `/admin`; confirm logout, secure cookies and CSRF protection work.
3. Check `pdftotext -v`, `pdfinfo -v` and `gs --version` in the host shell.
4. Import a synthetic PDF/Excel roster, generate, inspect the visual arrangement, approve and test a controlled publication/SID lookup.
5. Restart/redeploy the web process and confirm the same accounts and test exam still exist on the persistent disk.
6. Download a database backup and verify recovery before using real examination data. Remove the synthetic test session afterward.

GitHub Actions runs the automated suite on pushes and pull requests. It uses generated sample records and temporary databases. Tests requiring the private, original college PDF skip when that file is absent; it is deliberately excluded from GitHub. Run locally with:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Official references

- [Flask deployment with Waitress](https://flask.palletsprojects.com/en/stable/deploying/waitress/)
- [GitHub Pages is static hosting](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
