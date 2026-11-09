#!/usr/bin/env bash
# Upload only the reviewed source manifest; never copy the working database/uploads.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
publish_dir="$(mktemp -d -t gphem-publish.XXXXXX)"
trap 'rm -rf -- "$publish_dir"' EXIT
if [[ "${1:-}" == "--check" ]]; then
  mkdir -p "$publish_dir/repo"
elif [[ $# -eq 0 ]]; then
  git clone --single-branch --branch main https://github.com/EklavyPatel/GPHEM.git "$publish_dir/repo"
else
  echo 'Usage: bash scripts/upload-gphem.sh [--check]' >&2
  exit 2
fi
python3 - "$project_dir" "$publish_dir/repo" <<'PY'
from pathlib import Path,PurePosixPath
import re,sys
source=Path(sys.argv[1]);target=Path(sys.argv[2])
paths=(source/'UPLOAD_FILES.txt').read_text().splitlines()
if not paths or len(paths)!=len(set(paths)):raise SystemExit('Invalid upload manifest.')
for name in paths:
    relative=PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or not name:
        raise SystemExit('Unsafe upload path: '+name)
    if relative.suffix.lower() in ('.pdf','.db','.sqlite','.sqlite3','.zip','.pem','.key') or '.sqlite' in name:
        raise SystemExit('Private/generated data cannot be uploaded: '+name)
    if relative.parts[0]=='instance' and name!='instance/.gitkeep':raise SystemExit('Database data excluded.')
    if any(x in relative.parts for x in ('.env','.venv','.git','.aws','.codex','.agents','audit','.playwright-mcp','__pycache__')):
        raise SystemExit('Private configuration excluded: '+name)
    original=source/name
    if original.is_symlink() or not original.is_file():raise SystemExit('Missing/unsafe source file: '+name)
    data=original.read_bytes()
    if name=='BUG_REPORT.md':
        data=re.sub(r'\[([^\]]+)\]\(audit/[^)]+\)',r'\1 (local audit artifact; not distributed)',data.decode()).encode()
    destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
print(f'Prepared {len(paths)} reviewed source files; database, backups and student PDFs excluded.')
PY
if [[ "${1:-}" == "--check" ]]; then
  echo 'Source manifest check passed. No GitHub connection or write was attempted.'
  exit 0
fi
mapfile -t upload_paths < "$project_dir/UPLOAD_FILES.txt"
git -C "$publish_dir/repo" add -- "${upload_paths[@]}"
if git -C "$publish_dir/repo" diff --cached --quiet; then
  echo 'GPHEM/main already matches these source files.'
  exit 0
fi
# Set identity only in the temporary clone; do not change global Git settings.
git -C "$publish_dir/repo" config user.name 'Eklavy Patel'
git -C "$publish_dir/repo" config user.email '300158803+EklavyPatel@users.noreply.github.com'
git -C "$publish_dir/repo" commit -m 'Publish GPHEM application and deployment configuration'
# Keep repository history and reject concurrent changes; never force-push.
git -C "$publish_dir/repo" push origin HEAD:main
echo 'Uploaded to https://github.com/EklavyPatel/GPHEM'
