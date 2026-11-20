"""Small host service that survives replacement of the platform container."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from apply import read, save
from platform_release import DEFAULT_REPOSITORY, ReleaseError, latest_release

ROOT = Path(os.environ.get("DMP_UPDATE_ROOT", "/var/lib/device-platform-updater"))
SHARED = ROOT / "shared"
APPLY = Path("/opt/device-platform-updater/apply.py")


def write_status():
    save(SHARED / "worker.json", {"checked_at": int(time.time())})


def check_release():
    repo = read(ROOT / "config.json").get("repository", DEFAULT_REPOSITORY)
    path = SHARED / "release.json"
    previous = read(path) if path.exists() else {}
    timestamp = int(time.time())
    try:
        release = latest_release(repo)
        result = {"latest": release.public() if release else None, "checked_at": timestamp, "check_failed": False}
    except ReleaseError as exc:
        print(str(exc), flush=True)
        result = {
            "latest": previous.get("latest") if previous.get("repository") == repo else None,
            "checked_at": previous.get("checked_at") if previous.get("repository") == repo else None,
            "check_failed": True,
        }
    save(path, {**result, "repository": repo, "attempted_at": timestamp})


def main():
    SHARED.mkdir(mode=0o700, parents=True, exist_ok=True)
    next_check = 0
    while True:
        try:
            write_status()
            status_path = SHARED / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            transaction_exists = (ROOT / "transaction.json").exists()
            if ((SHARED / "request.json").exists()
                    or status.get("status") in {"queued", "preparing", "switching", "rolling_back"}
                    or (transaction_exists and status.get("status") != "recovery_required")):
                result = subprocess.run(
                    [sys.executable, str(APPLY), str(ROOT)],
                    check=False,
                    timeout=1800,
                )
                if result.returncode:
                    print(f"updater task exited with code {result.returncode}", flush=True)
            if time.monotonic() >= next_check:
                check_release()
                next_check = time.monotonic() + 300
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"updater loop failed: {exc}", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
