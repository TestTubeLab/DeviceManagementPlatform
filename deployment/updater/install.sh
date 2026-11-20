#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: install.sh <compose-project-directory> [project-name]" >&2
  exit 2
fi

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$1" && pwd)"
project_name="${2:-deploy-simple}"
compose_file="$project_dir/docker-compose.yml"
if [[ ! -f "$compose_file" ]]; then
  echo "Compose file not found: $compose_file" >&2
  exit 1
fi

mkdir -p /opt/device-platform-updater /var/lib/device-platform-updater/shared /var/lib/device-platform-updater/backups
chmod 700 /var/lib/device-platform-updater /var/lib/device-platform-updater/backups
chmod 755 /var/lib/device-platform-updater/shared
compose_files=("$compose_file")
if [[ -f "$project_dir/docker-compose.override.yml" ]]; then
  compose_files+=("$project_dir/docker-compose.override.yml")
fi
if [[ -f "$project_dir/docker-compose.override.yaml" ]]; then
  compose_files+=("$project_dir/docker-compose.override.yaml")
fi

python3 - "$project_dir" "$project_name" "${compose_files[@]}" <<'PY'
import json
import os
import sys
from pathlib import Path

project, name, *files = sys.argv[1:]
target = Path("/var/lib/device-platform-updater/config.json")
if target.exists():
    old = json.loads(target.read_text())
    if (old.get("project_directory"), old.get("project")) != (str(Path(project).resolve()), name):
        raise SystemExit("Updater already belongs to a different Compose project; inspect its config before changing it.")
config = {
    "project_directory": str(Path(project).resolve()),
    "project": name,
    "compose_files": [str(Path(path).resolve()) for path in files],
    "repository": os.environ.get("DMP_RELEASE_REPO", "TestTubeLab/DeviceManagementPlatform"),
}
temporary = target.with_suffix(".tmp")
temporary.write_text(json.dumps(config), encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, target)
PY

install -m 0644 "$source_dir/apply.py" "$source_dir/daemon.py" /opt/device-platform-updater/
install -m 0644 "$source_dir/../../server/management/platform_release.py" /opt/device-platform-updater/platform_release.py
install -m 0644 "$source_dir/device-platform-updater.service" /etc/systemd/system/device-platform-updater.service
systemctl daemon-reload
systemctl enable --now device-platform-updater.service
systemctl is-active device-platform-updater.service
