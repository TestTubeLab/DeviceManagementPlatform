"""Regression tests for syncing host updater code from a verified release image."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daemon
from apply import UPDATER_FILES, UpdateError, Updater


class UpdaterSelfSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "state"
        self.root.mkdir(mode=0o700)
        self.install = Path(self.temporary.name) / "installed"
        self.install.mkdir()
        self.updater = object.__new__(Updater)
        self.updater.root = self.root
        self.updater.updater_install_dir = self.install

    def package_files(self, version="v1.8.9"):
        return {
            "apply.py": "VALUE = 'release'\n",
            "daemon.py": "VALUE = 'release'\n",
            "platform_release.py": "VALUE = 'release'\n",
            "VERSION": version + "\n",
        }

    def stage_from_image(self, version="v1.8.9", package_version=None):
        files = self.package_files(package_version or version)
        container_id = "a" * 64
        destination = self.root / "staged"

        def run_command(*args, timeout=180):
            if args[:2] == ("docker", "create"):
                self.assertEqual(args[-1], "release-image")
                return container_id
            if args[:2] == ("docker", "cp"):
                source_name = args[-2].rsplit("/", 1)[-1]
                Path(args[-1]).write_text(files[source_name], encoding="utf-8")
                return ""
            self.fail(f"Unexpected command: {args}")

        with (
            patch("apply.command", side_effect=run_command),
            patch("apply.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run,
        ):
            staged = self.updater.stage_updater_from_image("release-image", version, destination)

        run.assert_called_once_with(
            ["docker", "rm", container_id], check=False, capture_output=True, text=True, timeout=30,
        )
        return staged

    def test_stages_only_compilable_files_matching_release_version(self):
        staged = self.stage_from_image()

        self.assertEqual({path.name for path in staged.iterdir()}, set(UPDATER_FILES))
        self.assertEqual((staged / "VERSION").read_text(encoding="utf-8").strip(), "v1.8.9")

    def test_rejects_version_mismatch_before_install(self):
        with self.assertRaisesRegex(UpdateError, "version does not match"):
            self.stage_from_image(package_version="v1.8.8")

        self.assertFalse((self.root / "staged").exists())

    def test_sync_and_transaction_restore_previous_files(self):
        for name in UPDATER_FILES[:-1]:
            (self.install / name).write_text("VALUE = 'previous'\n", encoding="utf-8")
        backup = self.updater.backup_updater_files("b" * 32)
        staged = self.stage_from_image()

        self.updater.install_updater_files(staged, backup, "v1.8.9")

        self.assertEqual((self.install / "apply.py").read_text(encoding="utf-8"), "VALUE = 'release'\n")
        self.assertEqual((self.install / "VERSION").read_text(encoding="utf-8").strip(), "v1.8.9")
        self.assertEqual((self.root / "updater-reload").read_text(encoding="utf-8").strip(), "v1.8.9")
        self.assertEqual((self.install / "apply.py").stat().st_mode & 0o777, 0o644)

        self.updater.restore_updater_files(backup)

        self.assertEqual((self.install / "apply.py").read_text(encoding="utf-8"), "VALUE = 'previous'\n")
        self.assertFalse((self.install / "VERSION").exists())
        self.assertEqual((self.root / "updater-reload").read_text(encoding="utf-8").strip(), "restored")

    def test_partial_install_failure_restores_previous_sources(self):
        for name in UPDATER_FILES[:-1]:
            (self.install / name).write_text("VALUE = 'previous'\n", encoding="utf-8")
        backup = self.updater.backup_updater_files("c" * 32)
        staged = self.stage_from_image()
        import apply

        write_file = apply.write_file
        calls = 0

        def fail_second_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated file replacement failure")
            return write_file(*args, **kwargs)

        with patch("apply.write_file", side_effect=fail_second_write):
            with self.assertRaisesRegex(UpdateError, "previous files were restored"):
                self.updater.install_updater_files(staged, backup, "v1.8.9")

        for name in UPDATER_FILES[:-1]:
            self.assertEqual((self.install / name).read_text(encoding="utf-8"), "VALUE = 'previous'\n")
        self.assertFalse((self.install / "VERSION").exists())
        self.assertFalse((self.root / "updater-reload").exists())

    def test_daemon_reloads_after_sync_and_retries_marker_if_exec_fails(self):
        marker = self.root / "updater-reload"
        marker.write_text("v1.8.9\n", encoding="utf-8")
        with patch.object(daemon, "ROOT", self.root), patch.object(daemon.os, "execv") as execv:
            daemon.reload_after_updater_sync()

        execv.assert_called_once_with(
            sys.executable,
            [sys.executable, str(Path(daemon.__file__).resolve())],
        )
        self.assertFalse(marker.exists())

        marker.write_text("v1.8.9\n", encoding="utf-8")
        with (
            patch.object(daemon, "ROOT", self.root),
            patch.object(daemon.os, "execv", side_effect=OSError("simulated exec failure")),
        ):
            daemon.reload_after_updater_sync()
        self.assertEqual(marker.read_text(encoding="utf-8").strip(), "v1.8.9")


if __name__ == "__main__":
    unittest.main()
