"""Run one queued platform release from the host, independently of the web service."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from platform_release import ARCHIVE_NAME, DEFAULT_REPOSITORY, ReleaseError, latest_release, version_key

UPDATE_BACKUP_RETENTION = 1
UPDATE_BACKUP_ID = re.compile(r"^[a-f0-9]{32}$")
ROLLBACK_TAG = re.compile(r"^device-platform-rollback:[a-f0-9]{32}$")
UPDATER_IMAGE_DIR = "/opt/device-platform-updater-release"
UPDATER_INSTALL_DIR = Path("/opt/device-platform-updater")
UPDATER_FILES = ("platform_release.py", "apply.py", "daemon.py", "VERSION")


class UpdateError(Exception):
    """An update step failed. Tool output stays in the host journal."""


def write_file(path, content, mode=0o600):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as source:
        temporary = Path(source.name)
        try:
            source.write(content.encode("utf-8"))
            os.fchmod(source.fileno(), mode)
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
        self.updater_install_dir = UPDATER_INSTALL_DIR
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

    def status(self, job, stage, message="", **details):
        now = int(time.time())
        status_path = self.shared / "status.json"
        previous = read(status_path) if status_path.exists() else {}
        phase = details.get("phase")
        same_phase = (
            previous.get("id") == job.get("id")
            and previous.get("status") == stage
            and previous.get("phase") == phase
        )
        save(status_path, {
            **job,
            "status": stage,
            "message": message,
            "updated_at": now,
            "phase": phase,
            "phase_started_at": previous.get("phase_started_at", now) if same_phase else now,
            **details,
        })

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
        updater_backup = transaction.get("updater_backup")
        updater_restore_error = None
        if updater_backup:
            try:
                self.restore_updater_files(Path(updater_backup))
            except (OSError, ValueError, UpdateError) as exc:
                updater_restore_error = exc
                print(f"Platform rollback succeeded but updater source restore failed: {exc}", flush=True)
        save(self.journal, {**transaction, "phase": "restored"})
        message = "新版未通过，已恢复旧版和切换前数据库。"
        if updater_restore_error:
            message += "更新器代码恢复失败，备份仍保留，请检查宿主机更新服务日志。"
        self.finish(
            transaction, "rolled_back", message,
            keep_updater_backup=bool(updater_restore_error),
        )

    def finish(self, transaction, stage, message="", *, keep_updater_backup=False):
        self.gate.unlink(missing_ok=True)
        self.status(transaction["job"], stage, message)
        self.journal.unlink(missing_ok=True)
        if stage in {"succeeded", "rolled_back"}:
            updater_backup = transaction.get("updater_backup")
            if updater_backup and not keep_updater_backup:
                backup = Path(updater_backup)
                if (backup.parent == self.root
                        and re.fullmatch(r"updater-before-[a-f0-9]{32}", backup.name)):
                    shutil.rmtree(backup, ignore_errors=True)
            try:
                self.cleanup_history()
            except (OSError, ValueError, KeyError, UpdateError, subprocess.SubprocessError) as exc:
                print(f"Update completed, but old history cleanup failed: {exc}", flush=True)

    def cleanup_image_tag(self, tag, active_image_id, *, dry_run=False):
        """Remove one updater-owned tag only when no container depends on its image."""
        inspected = subprocess.run(
            ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
            check=False, capture_output=True, text=True, timeout=30,
        )
        if inspected.returncode != 0:
            return
        image_id = inspected.stdout.strip()
        if not image_id or image_id == active_image_id:
            return

        containers = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"ancestor={image_id}"],
            check=False, capture_output=True, text=True, timeout=30,
        )
        if containers.returncode != 0 or containers.stdout.strip():
            return

        if dry_run:
            print(f"Would remove expired updater image tag {tag}", flush=True)
            return

        removed = subprocess.run(
            ["docker", "image", "rm", tag],
            check=False, capture_output=True, text=True, timeout=60,
        )
        if removed.returncode != 0:
            print(f"Could not remove expired updater image tag {tag}: {removed.stderr[-1000:]}", flush=True)
        else:
            print(f"Removed expired updater image tag {tag}", flush=True)

    def cleanup_history(self, *, dry_run=False):
        """Retain one verified rollback snapshot and only its rollback image tag."""
        backup_root = self.root / "backups"
        if not backup_root.is_dir() or backup_root.is_symlink():
            return

        entries = []
        orphaned = []
        allowed = {"transaction.json", "before.sqlite3", "writing.sqlite3", "preflight"}
        for path in backup_root.iterdir():
            if (not UPDATE_BACKUP_ID.fullmatch(path.name) or path.is_symlink()
                    or not path.is_dir()):
                continue
            children = list(path.iterdir())
            if any(child.is_symlink() for child in children) or not {child.name for child in children} <= allowed:
                continue

            transaction_path = path / "transaction.json"
            if not transaction_path.is_file():
                if {child.name for child in children} <= {"preflight"}:
                    orphaned.append(path)
                continue
            try:
                transaction = read(transaction_path)
                job = transaction["job"]
                valid = (
                    job["id"] == path.name
                    and transaction["backup"] == str(path)
                    and transaction["previous_image"] == f"device-platform-rollback:{path.name}"
                    and (path / "before.sqlite3").is_file()
                    and not (path / "before.sqlite3").is_symlink()
                )
                created_at = job["created_at"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if valid and isinstance(created_at, (int, float)):
                entries.append((created_at, path, transaction))

        entries.sort(key=lambda entry: (entry[0], entry[1].name), reverse=True)
        retained = entries[:UPDATE_BACKUP_RETENTION]
        retained_tags = {entry[2]["previous_image"] for entry in retained}
        retained_versions = {
            entry[2].get("previous_version") for entry in retained
            if version_key(entry[2].get("previous_version") or "")
        }

        for _, path, transaction in entries[UPDATE_BACKUP_RETENTION:]:
            if dry_run:
                print(f"Would remove expired update backup {path.name}", flush=True)
                continue
            try:
                shutil.rmtree(path)
                print(f"Removed expired update backup {path.name}", flush=True)
            except OSError as exc:
                print(f"Could not remove expired update backup {path}: {exc}", flush=True)
                retained_tags.add(transaction["previous_image"])
                previous_version = transaction.get("previous_version")
                if version_key(previous_version or ""):
                    retained_versions.add(previous_version)
        for path in orphaned:
            if dry_run:
                print(f"Would remove incomplete update backup {path.name}", flush=True)
                continue
            try:
                shutil.rmtree(path)
                print(f"Removed incomplete update backup {path.name}", flush=True)
            except OSError as exc:
                print(f"Could not remove incomplete update backup {path}: {exc}", flush=True)

        try:
            active = self.inspect(self.app_id())
            active_image_id = active.get("Image", "")
            active_version = (active.get("Config", {}).get("Labels") or {}).get(
                "org.opencontainers.image.version", "",
            )
        except (KeyError, IndexError, UpdateError, subprocess.SubprocessError, OSError) as exc:
            print(f"Could not inspect the active platform image; skipping image cleanup: {exc}", flush=True)
            return

        listed = subprocess.run(
            ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
            check=False, capture_output=True, text=True, timeout=30,
        )
        if listed.returncode != 0:
            print(f"Could not list updater image tags: {listed.stderr[-1000:]}", flush=True)
            return

        repository_prefix = f"ghcr.io/{self.repository.lower()}:"
        for tag in set(listed.stdout.splitlines()):
            if ROLLBACK_TAG.fullmatch(tag):
                if tag not in retained_tags:
                    self.cleanup_image_tag(tag, active_image_id, dry_run=dry_run)
                continue

            if not tag.startswith(repository_prefix):
                continue
            version = tag.removeprefix(repository_prefix)
            if (version_key(version) and version not in retained_versions
                    and version != active_version):
                self.cleanup_image_tag(tag, active_image_id, dry_run=dry_run)

    def stage_updater_from_image(self, image, version, destination):
        """Extract and validate the updater bundled in the verified application image."""
        destination.mkdir(mode=0o700)
        container = ""
        try:
            container = command(
                "docker", "create", "--network", "none", "--entrypoint", "/bin/true", image,
            ).strip()
            if not re.fullmatch(r"[0-9a-f]{12,64}", container):
                raise UpdateError("Docker returned an invalid updater staging container ID")
            for name in UPDATER_FILES:
                command("docker", "cp", f"{container}:{UPDATER_IMAGE_DIR}/{name}", str(destination / name))
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        finally:
            if container:
                removed = subprocess.run(
                    ["docker", "rm", container], check=False, capture_output=True, text=True, timeout=30,
                )
                if removed.returncode:
                    print(f"Could not remove updater staging container {container}: {removed.stderr[-1000:]}", flush=True)

        if {path.name for path in destination.iterdir()} != set(UPDATER_FILES):
            shutil.rmtree(destination, ignore_errors=True)
            raise UpdateError("Release image contains an incomplete updater package")
        for name in UPDATER_FILES:
            path = destination / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                shutil.rmtree(destination, ignore_errors=True)
                raise UpdateError(f"Invalid updater package file: {name}")
        if (destination / "VERSION").read_text(encoding="utf-8").strip() != version:
            shutil.rmtree(destination, ignore_errors=True)
            raise UpdateError("Updater package version does not match the release")
        for name in UPDATER_FILES[:-1]:
            path = destination / name
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except SyntaxError as exc:
                shutil.rmtree(destination, ignore_errors=True)
                raise UpdateError(f"Release updater source is invalid: {name}") from exc
        return destination

    def backup_updater_files(self, job_id):
        """Keep the installed updater files so application rollback can restore them."""
        if not UPDATE_BACKUP_ID.fullmatch(job_id):
            raise UpdateError("Invalid update ID for updater backup")
        if self.updater_install_dir.is_symlink() or not self.updater_install_dir.is_dir():
            raise UpdateError("Host updater install directory is missing or unsafe")
        backup = self.root / f"updater-before-{job_id}"
        backup.mkdir(mode=0o700)
        present = []
        try:
            for name in UPDATER_FILES:
                source = self.updater_install_dir / name
                if source.is_symlink():
                    raise UpdateError(f"Installed updater file is not a regular file: {name}")
                if source.exists():
                    if not source.is_file():
                        raise UpdateError(f"Installed updater file is not a regular file: {name}")
                    shutil.copy2(source, backup / name)
                    present.append(name)
            if not set(UPDATER_FILES[:-1]) <= set(present):
                raise UpdateError("Required host updater files are missing")
            save(backup / "manifest.json", {"files": present})
        except Exception:
            shutil.rmtree(backup, ignore_errors=True)
            raise
        return backup

    def restore_updater_files(self, backup, *, reload_daemon=True):
        """Restore the previous updater package from its transaction backup."""
        if (backup.parent != self.root
                or not re.fullmatch(r"updater-before-[a-f0-9]{32}", backup.name)):
            raise UpdateError("Updater backup path is outside the update state directory")
        if backup.is_symlink() or not backup.is_dir():
            raise UpdateError("Updater backup directory is missing or unsafe")
        if self.updater_install_dir.is_symlink() or not self.updater_install_dir.is_dir():
            raise UpdateError("Host updater install directory is missing or unsafe")
        manifest_path = backup / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise UpdateError("Updater backup manifest is missing or unsafe")
        present = read(manifest_path).get("files")
        if (not isinstance(present, list) or not all(isinstance(name, str) for name in present)
                or len(present) != len(set(present)) or not set(present) <= set(UPDATER_FILES)):
            raise UpdateError("Updater backup manifest is invalid")
        if {path.name for path in backup.iterdir()} != set(present) | {"manifest.json"}:
            raise UpdateError("Updater backup contains unexpected files")
        marker = self.root / "updater-reload"
        if reload_daemon:
            marker.unlink(missing_ok=True)
        for name in UPDATER_FILES:
            destination = self.updater_install_dir / name
            if destination.is_symlink():
                raise UpdateError(f"Refusing to replace updater symlink: {name}")
            if name in present:
                source = backup / name
                if source.is_symlink() or not source.is_file():
                    raise UpdateError(f"Updater backup file is missing: {name}")
                write_file(destination, source.read_text(encoding="utf-8"), mode=source.stat().st_mode & 0o777)
            else:
                destination.unlink(missing_ok=True)
        if reload_daemon:
            write_file(marker, "restored\n")

    def install_updater_files(self, staged, backup, version):
        """Install the image-verified updater and revert it if a file replacement fails."""
        try:
            for name in UPDATER_FILES:
                destination = self.updater_install_dir / name
                if destination.is_symlink():
                    raise UpdateError(f"Refusing to replace updater symlink: {name}")
                write_file(destination, (staged / name).read_text(encoding="utf-8"), mode=0o644)
            write_file(self.root / "updater-reload", f"{version}\n")
        except Exception as install_error:
            try:
                self.restore_updater_files(backup, reload_daemon=False)
            except Exception as restore_error:
                raise UpdateError("Updater install failed and its previous files could not be restored") from restore_error
            raise UpdateError("Updater install failed; previous files were restored") from install_error

    def pull_release(self, release, job=None):
        if release.archive_digest:
            image = f"ghcr.io/{self.repository.lower()}:{release.version}"
            # Skip transfer when the exact published image is already in the local daemon.
            local = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                check=False, capture_output=True, text=True, timeout=15,
            )
            if local.returncode != 0 or local.stdout.strip() != release.digest:
                image = self.load_release_archive(release, job)
            elif job:
                self.status(
                    job,
                    "preparing",
                    "本机已存在摘要匹配的发布镜像，跳过归档下载。",
                    phase="cached_image",
                )
        else:
            if job:
                self.status(
                    job,
                    "preparing",
                    "发布未提供可校验的镜像归档，正在从镜像仓库拉取；此路径暂不提供字节级进度。",
                    phase="registry_pull",
                )
            image = release.image(self.repository)
            command("docker", "pull", image, timeout=600)
        if job:
            self.status(
                job,
                "preparing",
                "正在核对镜像版本标签。",
                phase="verify_image",
            )
        label = command("docker", "image", "inspect", image, "--format",
                        '{{index .Config.Labels "org.opencontainers.image.version"}}').strip()
        if label != release.version:
            raise UpdateError("Release does not match the image version label")
        return image

    def _download_release_archive(self, arguments, target, release, job):
        """下载归档时按实际文件增长量发布进度，避免猜测传输百分比。"""

        initial_size = min(target.stat().st_size, release.archive_size)
        last_progress_at = int(time.time())
        self.status(
            job,
            "preparing",
            "正在从 GitHub Release 下载发布镜像归档。",
            phase="download",
            downloaded_bytes=initial_size,
            total_bytes=release.archive_size,
            download_percent=round(initial_size * 100 / release.archive_size, 1),
            download_speed_bytes_per_second=0,
            download_last_progress_at=last_progress_at,
        )
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        started = time.monotonic()
        deadline = started + 14410
        last_sample_size = initial_size
        samples = [(started, initial_size)]

        try:
            while process.poll() is None:
                now = time.monotonic()
                downloaded = min(target.stat().st_size, release.archive_size)
                if downloaded > last_sample_size:
                    last_progress_at = int(time.time())

                samples.append((now, downloaded))
                while len(samples) > 2 and now - samples[0][0] > 5:
                    samples.pop(0)
                sample_duration = samples[-1][0] - samples[0][0]
                speed = (
                    max(0, samples[-1][1] - samples[0][1]) / sample_duration
                    if sample_duration > 0
                    else 0
                )
                self.status(
                    job,
                    "preparing",
                    "正在从 GitHub Release 下载发布镜像归档。",
                    phase="download",
                    downloaded_bytes=downloaded,
                    total_bytes=release.archive_size,
                    download_percent=round(downloaded * 100 / release.archive_size, 1),
                    download_speed_bytes_per_second=round(speed),
                    download_last_progress_at=last_progress_at,
                )
                last_sample_size = downloaded
                if now >= deadline:
                    raise subprocess.TimeoutExpired(arguments, 14410)
                time.sleep(min(1, max(0, deadline - now)))

            _, stderr = process.communicate()
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.communicate()
            raise

        if process.returncode:
            if stderr:
                print(stderr[-3000:], flush=True)
            raise UpdateError("curl --fail failed")

    def load_release_archive(self, release, job=None):
        """Load a checked GitHub Release asset without private registry credentials."""
        with tempfile.TemporaryDirectory(prefix="download-", dir=self.root) as directory:
            target = Path(directory) / ARCHIVE_NAME
            target.touch(mode=0o600)
            curl_args = (
                "curl", "--fail", "--silent", "--show-error", "--location", "--http1.1",
                "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "15", "--max-time", "14400",
                "--retry", "8", "--retry-all-errors", "--retry-delay", "3", "--retry-max-time", "14400",
                "--continue-at", "-",
                "--header", "Accept: application/octet-stream",
                "--max-filesize", str(release.archive_size), "--output", str(target),
                f"https://api.github.com/repos/{self.repository}/releases/assets/{release.archive_id}"
                f"?download={int(time.time())}",
            )
            if job:
                self._download_release_archive(curl_args, target, release, job)
                self.status(
                    job,
                    "preparing",
                    "归档下载完成，正在校验文件大小和 SHA-256。",
                    phase="verify_archive",
                    downloaded_bytes=target.stat().st_size,
                    total_bytes=release.archive_size,
                    download_percent=100.0,
                    download_speed_bytes_per_second=0,
                )
            else:
                command(*curl_args, timeout=14410)
            digest = hashlib.sha256()
            with target.open("rb") as archive:
                for chunk in iter(lambda: archive.read(1024 * 1024), b""):
                    digest.update(chunk)
            if target.stat().st_size != release.archive_size or f"sha256:{digest.hexdigest()}" != release.archive_digest:
                raise UpdateError("Downloaded release archive does not match its SHA-256")
            repository = f"ghcr.io/{self.repository.lower()}"
            tag = f"{repository}:{release.version}"
            if job:
                self.status(
                    job,
                    "preparing",
                    "归档校验通过，正在载入 Docker 镜像。",
                    phase="load_image",
                    downloaded_bytes=target.stat().st_size,
                    total_bytes=release.archive_size,
                    download_percent=100.0,
                    download_speed_bytes_per_second=0,
                )
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
        self.status(job, "preparing", "正在读取并验证目标发布。", phase="release_metadata")
        release = latest_release(self.repository)
        if not release or release.version != job["version"]:
            raise UpdateError("GitHub latest release changed")
        self.status(job, "preparing", "正在检查当前平台容器。", phase="inspect_current")
        current = self.inspect(self.app_id())
        old_version = (current["Config"].get("Labels") or {}).get("org.opencontainers.image.version")
        if version_key(old_version):
            if version_key(release.version) <= version_key(old_version):
                raise UpdateError("Release is not newer than the currently running version")
        elif not bootstrap:
            raise UpdateError("Existing platform requires a one-time bootstrap")
        self.status(job, "preparing", "正在核对现有 Compose 配置和数据卷。", phase="check_layout")
        database = self.check_layout(current)
        image = self.pull_release(release, job)

        self.status(job, "preparing", "正在复制数据库并预检迁移。", phase="preflight_snapshot")
        backup = self.root / "backups" / job["id"]
        backup.mkdir(mode=0o700)
        smoke = backup / "preflight"
        smoke.mkdir(mode=0o700)
        try:
            snapshot(database, smoke / "db.sqlite3")
            self.status(job, "preparing", "正在隔离的数据库副本上运行迁移预检。", phase="preflight_migrations")
            command("docker", "run", "--rm", "--network", "none",
                    "--mount", f"type=bind,src={smoke},dst=/app/data",
                    "-e", "DATABASE_URL=sqlite:////app/data/db.sqlite3",
                    "--entrypoint", "python", image, "manage.py", "platform_update_preflight", timeout=240)
        finally:
            # The snapshot is disposable. The cutover backup below is kept for recovery.
            for item in smoke.iterdir():
                item.unlink()
            smoke.rmdir()
        updater_staging = self.root / f"updater-stage-{job['id']}"
        updater_backup = None
        try:
            self.status(job, "preparing", "正在校验发布镜像内的宿主更新器文件。", phase="stage_updater")
            self.stage_updater_from_image(image, release.version, updater_staging)
            updater_backup = self.backup_updater_files(job["id"])
            previous = f"device-platform-rollback:{job['id']}"
            command("docker", "image", "tag", current["Image"], previous)
            transaction = {"job": job, "backup": str(backup), "database": str(database),
                           "previous_version": old_version if version_key(old_version or "") else None,
                           "previous_image": previous, "previous_override": read(self.override),
                           "updater_backup": str(updater_backup), "phase": "switching"}
            save(backup / "transaction.json", transaction)
            save(self.journal, transaction)
            self.status(job, "switching", "正在启用维护门并停止旧应用。", phase="stop_old_app")
            self.gate.touch(mode=0o644, exist_ok=True)
            self.gate.chmod(0o644)
            self.compose("stop", "-t", "25", "app")
            snapshot(database, backup / "writing.sqlite3")
            os.replace(backup / "writing.sqlite3", backup / "before.sqlite3")
            self.status(job, "switching", "数据库切换备份完成，正在启动新版本应用。", phase="start_new_app")
            self.select_image(image)
            self.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "app")
            self.status(job, "switching", "新版本容器已启动，正在等待健康检查。", phase="health_check")
            self.wait_ready(release.version)
            self.status(job, "switching", "新版本健康检查通过，正在安装随版本发布的更新器。", phase="install_updater")
            self.install_updater_files(updater_staging, updater_backup, release.version)
            # Commit before traffic resumes. Crash recovery must never restore after that point.
            save(self.journal, {**transaction, "phase": "committed"})
            self.finish(transaction, "succeeded")
        finally:
            shutil.rmtree(updater_staging, ignore_errors=True)
            if updater_backup and not self.journal.exists():
                shutil.rmtree(updater_backup, ignore_errors=True)

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
