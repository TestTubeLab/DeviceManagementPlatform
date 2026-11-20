#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
port="${1:-8081}"
project="${COMPOSE_PROJECT_NAME:-deploy-simple}"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null; then
    echo "Docker and Docker Compose v2 are required." >&2
    exit 1
fi
if ! [[ "$port" =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then
    echo "Invalid port: $port" >&2
    exit 2
fi

if [[ ! -f .env ]]; then
    public_address="$(curl -fsS --max-time 5 https://api.ipify.org || true)"
    (umask 077; set -o noclobber; printf 'PORT=%s\nSECRET_KEY=%s\nSERVER_URL=%s\n' "$port" \
        "$(openssl rand -hex 32)" "${SERVER_URL:-http://${public_address:-localhost}:$port}" > .env)
fi

if [[ "${DMP_SOURCE_BUILD:-0}" == 1 ]]; then
    docker compose -p "$project" up -d --build
else
    sudo bash ../updater/install.sh "$PWD" "$project"
    sudo python3 /opt/device-platform-updater/apply.py /var/lib/device-platform-updater --initialize
fi
docker compose -p "$project" ps

