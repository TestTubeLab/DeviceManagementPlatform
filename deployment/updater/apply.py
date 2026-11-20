"""Run one queued platform release from the host, independently of the web service."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from platform_release import ARCHIVE_NAME, DEFAULT_REPOSITORY, ReleaseError, latest_release, version_key


class UpdateError(Exception):
    """An update step failed. Tool output stays in the host journal."""


def write_file(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as source:
        temporary = Path(source.name)
        try:
            source.write(content.encode("utf-8"))
            source.flush()
            os.fsync(source.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)


def save(path, value):
    write_file(path, json.dumps(value))


def read(path):
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def command(*args, timeout=180):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if result.returncode:
        print(result.stderr[-3000:], flush=True)
        raise UpdateError(f"{args[0]} {args[1]} failed")
    return result.stdout


def snapshot(source, target):
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as origin:
        with closing(sqlite3.connect(target)) as copy:
            origin.backup(copy)
            if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise UpdateError("SQLite backup failed integrity check")
    target.chmod(0o600)
    with target.open("rb") as backup:
        os.fsync(backup.fileno())


class Updater:
    def __init__(self, root):
        self.root = root
        self.shared = root / "shared"
        self.override = root / "release-compose.json"
        self.journal = root / "transaction.json"
        self.gate = self.shared / "maintenance"
        self.config = read(root / "config.json")
        self.repository = self.config.get("repository", DEFAULT_REPOSITORY)
        self.compose_args = ["docker", "compose", "--project-directory", self.config["project_directory"],
                             "--project-name", self.config["project"]]
        for config_file in self.config["compose_files"]:
            self.compose_args.extend(["-f", config_file])
        self.compose_args.extend(["-f", str(self.override)])
        if not self.override.exists():
            save(self.override, {"services": {}})

    def compose(self, *args, timeout=180):
        return command(*self.compose_args, *args, timeout=timeout)

    def status(self, job, stage, message=""):
        save(self.shared / "status.json", {**job, "status": stage, "message": message,
                                            "updated_at": int(time.time())})

    def select_image(self, image):
        save(self.override, {"services": {"app": {
            "image": image,
            "pull_policy": "never",
            "environment": {
                "DMP_UPDATE_DIR": "/run/platform-updates",
                "DMP_RELEASE_REPO": self.repository,
            },
            "volumes": [{"type": "bind", "source": str(self.shared), "target": "/run/platform-updates"}],
        }}})

    def app_id(self):
        ids = self.compose("ps", "-a", "-q", "app").split()
        if len(ids) != 1:
            raise UpdateError("Expected exactly one platform app container")
        return ids[0]

    def inspect(self, container):
        return json.loads(command("docker", "inspect", container))[0]

    def check_layout(self, container):
        """Use the current Compose project and confirm it reuses the live data mounts."""
        cfg = json.loads(self.compose("config", "--format", "json"))
        service = cfg["services"]["app"]
        live = {mount["Destination"]: mount for mount in container["Mounts"]}
        expected = {mount["target"]: mount for mount in service["volumes"]}
        for path in ("/app/data", "/app/media"):
            name = cfg["volumes"][expected[path]["source"]]["name"]
            if live[path]["Type"] != "volume" or name != live[path]["Name"]:
                raise UpdateError("Compose volume names differ from the running platform")
        if not live["/app/data"]["RW"] or not live["/app/media"]["RW"]:
            raise UpdateError("Platform data mounts must be writable")
        if "/app" in live or "/app" in expected:
            raise UpdateError("A source-code bind mount would shadow the new image")
        if not container["State"]["Running"] or not container["HostConfig"]["PortBindings"].get("8081/tcp"):
            raise UpdateError("Unsupported platform container layout")
        return Path(live["/app/data"]["Source"]) / "db.sqlite3"

    def wait_ready(self, version=None):
        stop = time.monotonic() + 75
        while time.monotonic() < stop:
            try:
                container = self.app_id()
                if version:
                    body = command("docker", "exec", container, "curl", "-fsS", "--max-time", "3",
                                   "http://127.0.0.1:8081/health", timeout=7)
                    if json.loads(body) == {"status": "ok", "version": version}:
                        return
                else:
                    expected = command("docker", "exec", container, "curl", "-sS", "--max-time", "3",
                                       "-o", "/dev/null", "-w", "%{http_code}",
                                       "http://127.0.0.1:8000/api/auth/user/", timeout=7)
                    nginx = command("docker", "exec", container, "curl", "-fsS", "--max-time", "3",
                                    "http://127.0.0.1:8081/health", timeout=7)
                    if expected == "401" and nginx:
                        return
            except (UpdateError, ValueError, subprocess.TimeoutExpired):
                pass
            time.sleep(2)
        raise UpdateError("Platform health check timed out")

    def restore(self, transaction):
        job = transaction["job"]
        self.status(job, "rolling_back")
        self.gate.touch(mode=0o644, exist_ok=True)
        self.compose("stop", "-t", "25", "app")
        old_db = Path(transaction["backup"]) / "before.sqlite3"
        if old_db.exists():
            database = Path(transaction["database"])
            temp = database.with_name(".dmp-restore.sqlite3")
            snapshot(old_db, temp)
            info = database.stat()
            os.chown(temp, info.st_uid, info.st_gid)
            temp.chmod(info.st_mode & 0o777)
            for ending in ("-wal", "-shm", "-journal"):
                Path(str(database) + ending).unlink(missing_ok=True)
            os.replace(temp, database)
        # Use the retained image even if the original tag was changed externally.
        restored_override = transaction["previous_override"]
        restored_override.setdefault("services", {}).setdefault("app", {}).update(
            image=transaction["previous_image"], pull_policy="never",
        )
        save(self.override, restored_override)
        self.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "app")
        self.wait_ready(transaction.get("previous_version"))
        save(self.journal, {**transaction, "phase": "restored"})
        self.finish(transaction, "rolled_back", "新版未通过，已恢复旧版和切换前数据库。")

    def finish(self, transaction, stage, message=""):
        self.gate.unlink(missing_ok=True)
        self.status(transaction["job"], stage, message)
        self.journal.unlink(missing_ok=True)

    def pull_release(self, release):
        if release.archive_digest:
            image = f"ghcr.io/{self.repository.lower()}:{release.version}"
            # Skip transfer when the exact published image is already in the local daemon.
            local = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                check=False, capture_output=True, text=True, timeout=15,
            )
            if local.returncode != 0 or local.stdout.strip() != release.digest:
                image = self.load_release_archive(release)
        else:
            image = release.image(self.repository)
            command("docker", "pull", image, timeout=600)
        label = command("docker", "image", "inspect", image, "--format",
                        '{{index .Config.Labels "org.opencontainers.image.version"}}').strip()
        if label != release.version:
            raise UpdateError("Release does not match the image version label")
        return image

    def load_release_archive(self, release):
        """Load a checked GitHub Release asset without private registry credentials."""
        with tempfile.TemporaryDirectory(prefix="download-", dir=self.root) as directory:
            target = Path(directory) / ARCHIVE_NAME
            command("curl", "--fail", "--silent", "--show-error", "--location",
                    "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "15", "--max-time", "14400",
                    "--header", "Accept: application/octet-stream",
                    "--max-filesize", str(release.archive_size), "--output", str(target),
                    f"https://api.github.com/repos/{self.repository}/releases/assets/{release.archive_id}"
                    f"?download={int(time.time())}", timeout=14410)
            digest = hashlib.sha256()
            with target.open("rb") as archive:
                for chunk in iter(lambda: archive.read(1024 * 1024), b""):
                    digest.update(chunk)
            if target.stat().st_size != release.archive_size or f"sha256:{digest.hexdigest()}" != release.archive_digest:
                raise UpdateError("Downloaded release archive does not match its SHA-256")
            repository = f"ghcr.io/{self.repository.lower()}"
            tag = f"{repository}:{release.version}"
            loaded = command("docker", "load", "--input", str(target), timeout=180)
            if f"Loaded image: {tag}" not in loaded.splitlines():
                raise UpdateError("Release archive did not load the expected platform image")
            image_id = command("docker", "image", "inspect", tag, "--format", "{{.Id}}").strip()
            if image_id != release.digest:
                raise UpdateError("Loaded image ID does not match the release")
            return tag

    def initialize(self):
        if self.compose("ps", "-a", "-q", "app").strip():
            raise UpdateError("Existing platform detected; use --bootstrap or the web updater")
        release = latest_release(self.repository)
        if not release:
            raise UpdateError("No stable platform release available")
        self.select_image(self.pull_release(release))
        self.compose("up", "-d", "--no-build", "registry")
        self.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "app")
        self.wait_ready(release.version)
        print(f"Platform {release.version} is running.", flush=True)

    def execute(self, job, bootstrap=False):
        self.status(job, "preparing")
        release = latest_release(self.repository)
        if not release or release.version != job["version"]:
            raise UpdateError("GitHub latest release changed")
        current = self.inspect(self.app_id())
        old_version = (current["Config"].get("Labels") or {}).get("org.opencontainers.image.version")
        if version_key(old_version):
            if version_key(release.version) <= version_key(old_version):
                raise UpdateError("Release is not newer than the currently running version")
        elif not bootstrap:
            raise UpdateError("Existing platform requires a one-time bootstrap")
        database = self.check_layout(current)
        image = self.pull_release(release)

        backup = self.root / "backups" / job["id"]
        backup.mkdir(mode=0o700)
        smoke = backup / "preflight"
        smoke.mkdir(mode=0o700)
        try:
            snapshot(database, smoke / "db.sqlite3")
            command("docker", "run", "--rm", "--network", "none",
                    "--mount", f"type=bind,src={smoke},dst=/app/data",
                    "-e", "DATABASE_URL=sqlite:////app/data/db.sqlite3",
                    "--entrypoint", "python", image, "manage.py", "platform_update_preflight", timeout=240)
        finally:
            # The snapshot is disposable. The cutover backup below is kept for recovery.
            for item in smoke.iterdir():
                item.unlink()
            smoke.rmdir()
        previous = f"device-platform-rollback:{job['id']}"
        command("docker", "image", "tag", current["Image"], previous)
        transaction = {"job": job, "backup": str(backup), "database": str(database),
                       "previous_version": old_version if version_key(old_version or "") else None,
                       "previous_image": previous, "previous_override": read(self.override), "phase": "switching"}
        save(backup / "transaction.json", transaction)
        save(self.journal, transaction)
        self.status(job, "switching")
        self.gate.touch(mode=0o644, exist_ok=True)
        self.gate.chmod(0o644)
        self.compose("stop", "-t", "25", "app")
        snapshot(database, backup / "writing.sqlite3")
        os.replace(backup / "writing.sqlite3", backup / "before.sqlite3")
        self.select_image(image)
        self.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "app")
        self.wait_ready(release.version)
        # Commit before traffic resumes. Crash recovery must never restore after that point.
        save(self.journal, {**transaction, "phase": "committed"})
        self.finish(transaction, "succeeded")

    def recover(self):
        transaction = read(self.journal)
        phase = transaction["phase"]
        if phase == "committed":
            self.finish(transaction, "succeeded")
        elif phase == "restored":
            self.finish(transaction, "rolled_back", "已恢复上一版本。")
        else:
            try:
                self.restore(transaction)
            except (OSError, ValueError, KeyError, UpdateError, sqlite3.Error, subprocess.SubprocessError) as exc:
                print(str(exc), flush=True)
                self.status(transaction["job"], "recovery_required", "请在宿主机检查更新服务日志。")
                raise

    def run(self, bootstrap_version=None, retry=False):
        save(self.shared / "worker.json", {"checked_at": int(time.time())})
        if self.journal.exists():
            if retry or read(self.shared / "status.json").get("status") != "recovery_required":
                self.recover()
            return
        request = self.shared / "request.json"
        if bootstrap_version:
            if request.exists():
                raise UpdateError("A platform update is already queued")
            job = {"id": uuid4().hex, "version": bootstrap_version, "actor": "host-bootstrap", "created_at": int(time.time())}
        elif request.exists():
            try:
                job = read(request)
                if not re.fullmatch(r"[a-f0-9]{32}", job["id"]) or not version_key(job["version"]):
                    raise ValueError("Invalid queued job")
                job = {k: job[k] for k in ("id", "version", "actor", "created_at")}
            except (ValueError, KeyError, TypeError) as exc:
                request.unlink(missing_ok=True)
                raise UpdateError("Invalid queued job") from exc
        else:
            previous = self.shared / "status.json"
            if previous.exists():
                interrupted = read(previous)
                if interrupted.get("status") == "preparing":
                    self.status(interrupted, "failed", "更新预检被中断，请重新提交。")
            return
        self.status(job, "preparing")
        request.unlink(missing_ok=True)
        try:
            self.execute(job, bootstrap=bool(bootstrap_version))
        except (OSError, ValueError, KeyError, ReleaseError, UpdateError, sqlite3.Error, subprocess.SubprocessError) as exc:
            print(str(exc), flush=True)
            if self.journal.exists():
                self.recover()
            else:
                self.status(job, "failed", "升级预检失败，当前版本仍在运行。请查看宿主机更新服务日志。")
            if bootstrap_version:
                raise SystemExit(1)
        finally:
            save(self.shared / "worker.json", {"checked_at": int(time.time())})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("state_dir", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--bootstrap", metavar="VERSION")
    action.add_argument("--initialize", action="store_true")
    action.add_argument("--retry-recovery", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    with (args.state_dir / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(1 if args.bootstrap or args.initialize or args.retry_recovery else 0)
        updater = Updater(args.state_dir)
        if args.initialize:
            updater.initialize()
        else:
            updater.run(args.bootstrap, args.retry_recovery)
