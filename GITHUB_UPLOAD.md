# Upload GPHEM source to GitHub

Target: https://github.com/EklavyPatel/GPHEM, branch `main`.

The prepared upload contains only the reviewed relative paths in `UPLOAD_FILES.txt`. It excludes the working SQLite database, credentials, real student PDFs, backup files, ZIP exports, local browser/audit artifacts and the rejected logo cleanup draft. Example workbooks and test fixtures contain generated sample records. The actual logo is included.

## If upload permission is missing

The connected GitHub integration rejected both Git-data blob writes and a source-file creation with HTTP 403: **Resource not accessible by integration**. The repository remains unchanged. A read-only connection is insufficient to upload source files. Repository write access must be restored before the assistant can retry.

Alternatively, upload from your normal local terminal, outside an environment whose network access is restricted. Check your GitHub login:

```bash
gh auth status
```

If needed, authenticate through GitHub's own browser/device flow; do not paste a token into chat:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
```

Then run from this project directory:

```bash
bash scripts/upload-gphem.sh --check
bash scripts/upload-gphem.sh
```

The script clones the current `main`, copies only manifest-listed source files, makes a commit and performs a normal push. It preserves remote history and unrelated repository files and never force-pushes. Commit identity is set only in the temporary clone, using Eklavy Patel's GitHub no-reply address. Temporary files are removed afterward. The database in `instance/` is not copied.

The GitHub credential must permit contents writes to GPHEM. Updating `.github/workflows/tests.yml` can also require workflow permission. If GitHub specifically rejects that file for a missing `workflow` scope on a classic OAuth login, review/authorize the additional scope using `gh auth refresh --hostname github.com --scopes workflow`, then retry. Fine-grained credentials should be limited to this repository and the permissions required for its source/workflow files.

After uploading, follow [DEPLOYMENT.md](DEPLOYMENT.md). A repository upload is not itself a live Flask deployment; the host needs Python, the PDF system tools, HTTPS and persistent SQLite storage.
