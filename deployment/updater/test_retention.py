"""Regression tests for bounded updater backup and image retention."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from apply import Updater


class UpdaterRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "backups").mkdir()
        self.updater = object.__new__(Updater)
        self.updater.root = self.root
        self.updater.repository = "TestTubeLab/DeviceManagementPlatform"

    def add_backup(self, version, created_at):
        backup_id = uuid4().hex
        path = self.root / "backups" / backup_id
        path.mkdir()
        (path / "before.sqlite3").write_bytes(b"database snapshot")
        transaction = {
            "backup": str(path),
            "job": {"id": backup_id, "created_at": created_at},
            "previous_image": f"device-platform-rollback:{backup_id}",
            "previous_version": version,
        }
        (path / "transaction.json").write_text(json.dumps(transaction), encoding="utf-8")
        return path, transaction

    def test_cleanup_keeps_only_latest_database_rollback_and_its_image(self):
        expired_one, first = self.add_backup("v1.8.1", 100)
        expired_two, second = self.add_backup("v1.8.2", 200)
        retained, latest = self.add_backup("v1.8.3", 300)
        orphan = self.root / "backups" / uuid4().hex
        (orphan / "preflight").mkdir(parents=True)
        unknown = self.root / "backups" / uuid4().hex
        unknown.mkdir()
        (unknown / "before.sqlite3").write_bytes(b"unrecognized data")
        manual = self.root / "backups" / "ssh-management-backup"
        manual.mkdir()
        (manual / "operator-data").write_text("keep", encoding="utf-8")

        image_tags = "\n".join((
            first["previous_image"], second["previous_image"], latest["previous_image"],
            "ghcr.io/testtubelab/devicemanagementplatform:v1.8.1",
            "ghcr.io/testtubelab/devicemanagementplatform:v1.8.2",
            "ghcr.io/testtubelab/devicemanagementplatform:v1.8.3",
            "ghcr.io/testtubelab/devicemanagementplatform:v1.8.5",
            "other-project:latest",
        ))
        with (
            patch.object(self.updater, "app_id", return_value="platform-container"),
            patch.object(self.updater, "inspect", return_value={
                "Image": "sha256:active",
                "Config": {"Labels": {"org.opencontainers.image.version": "v1.8.5"}},
            }),
            patch.object(self.updater, "cleanup_image_tag") as remove_tag,
            patch("apply.subprocess.run", return_value=subprocess.CompletedProcess(
                ["docker", "image", "ls"], 0, image_tags, "",
            )),
        ):
            self.updater.cleanup_history()

        self.assertFalse(expired_one.exists())
        self.assertFalse(expired_two.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue(unknown.exists())
        self.assertTrue(retained.exists())
        self.assertTrue(manual.exists())
        removed = {call.args[0] for call in remove_tag.call_args_list}
        self.assertIn(first["previous_image"], removed)
        self.assertIn(second["previous_image"], removed)
        self.assertIn("ghcr.io/testtubelab/devicemanagementplatform:v1.8.1", removed)
        self.assertIn("ghcr.io/testtubelab/devicemanagementplatform:v1.8.2", removed)
        self.assertNotIn(latest["previous_image"], removed)
        self.assertNotIn("ghcr.io/testtubelab/devicemanagementplatform:v1.8.3", removed)
        self.assertNotIn("ghcr.io/testtubelab/devicemanagementplatform:v1.8.5", removed)
        self.assertNotIn("other-project:latest", removed)

    def test_snapshot_is_preserved_when_expired_backup_cannot_be_removed(self):
        expired, old = self.add_backup("v1.8.2", 200)
        retained, latest = self.add_backup("v1.8.3", 300)
        image_tags = "\n".join((old["previous_image"], latest["previous_image"]))
        with (
            patch.object(self.updater, "app_id", return_value="platform-container"),
            patch.object(self.updater, "inspect", return_value={
                "Image": "sha256:active",
                "Config": {"Labels": {"org.opencontainers.image.version": "v1.8.5"}},
            }),
            patch.object(self.updater, "cleanup_image_tag") as remove_tag,
            patch("apply.shutil.rmtree", side_effect=PermissionError("read-only")),
            patch("apply.subprocess.run", return_value=subprocess.CompletedProcess(
                ["docker", "image", "ls"], 0, image_tags, "",
            )),
        ):
            self.updater.cleanup_history()

        self.assertTrue(expired.exists())
        self.assertTrue(retained.exists())
        remove_tag.assert_not_called()

    def test_image_cleanup_checks_active_containers_and_only_removes_exact_tag(self):
        tag = "device-platform-rollback:" + uuid4().hex
        calls = [
            subprocess.CompletedProcess([], 0, "sha256:old", ""),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "Untagged: " + tag, ""),
        ]
        with patch("apply.subprocess.run", side_effect=calls) as run:
            self.updater.cleanup_image_tag(tag, "sha256:active")

        self.assertEqual(run.call_args_list[-1].args[0], ["docker", "image", "rm", tag])

    def test_image_cleanup_preserves_active_or_container_referenced_image(self):
        tag = "ghcr.io/testtubelab/devicemanagementplatform:v1.8.4"
        with patch("apply.subprocess.run", return_value=subprocess.CompletedProcess(
                [], 0, "sha256:active", "")) as run:
            self.updater.cleanup_image_tag(tag, "sha256:active")
            self.assertEqual(run.call_count, 1)

        with patch("apply.subprocess.run", side_effect=(
                subprocess.CompletedProcess([], 0, "sha256:old", ""),
                subprocess.CompletedProcess([], 0, "container-id\n", ""),
        )) as run:
            self.updater.cleanup_image_tag(tag, "sha256:active")
            self.assertEqual(run.call_count, 2)
