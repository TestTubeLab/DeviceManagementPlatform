"""Regression tests for reliable, verified release-archive downloads."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apply import UpdateError, Updater


class UpdaterDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.updater = object.__new__(Updater)
        self.updater.root = Path(self.temporary.name)
        self.updater.repository = "TestTubeLab/DeviceManagementPlatform"
        self.archive = b"verified test release archive"
        self.release = SimpleNamespace(
            archive_digest="sha256:" + hashlib.sha256(self.archive).hexdigest(),
            archive_size=len(self.archive),
            archive_id=123,
            version="v1.8.8",
            digest="sha256:" + "a" * 64,
        )

    def test_download_uses_http1_resume_and_bounded_retries_before_loading(self):
        curl_args = None

        def run_command(*args, timeout=180):
            nonlocal curl_args
            if args[0] == "curl":
                curl_args = args
                target = Path(args[args.index("--output") + 1])
                target.write_bytes(self.archive)
                return ""
            if args[:2] == ("docker", "load"):
                return f"Loaded image: ghcr.io/{self.updater.repository.lower()}:{self.release.version}\n"
            if args[:4] == ("docker", "image", "inspect", f"ghcr.io/{self.updater.repository.lower()}:{self.release.version}"):
                return self.release.digest
            self.fail(f"Unexpected command: {args}")

        with patch("apply.command", side_effect=run_command):
            image = self.updater.load_release_archive(self.release)

        self.assertEqual(image, f"ghcr.io/{self.updater.repository.lower()}:{self.release.version}")
        self.assertIn("--http1.1", curl_args)
        self.assertIn("--retry-all-errors", curl_args)
        self.assertIn("--continue-at", curl_args)
        self.assertEqual(curl_args[curl_args.index("--continue-at") + 1], "-")
        self.assertEqual(curl_args[curl_args.index("--retry") + 1], "8")
        self.assertEqual(curl_args[curl_args.index("--max-filesize") + 1], str(self.release.archive_size))

    def test_update_download_reports_actual_bytes_percent_speed_and_phase(self):
        self.updater.shared = self.updater.root / "shared"
        self.updater.shared.mkdir()
        job = {
            "id": "a" * 32,
            "version": self.release.version,
            "actor": "operator",
            "created_at": 123,
        }
        progress = []
        write_status = self.updater.status
        chunks = [self.archive[:8], self.archive[8:19], self.archive[19:]]

        class FakeCurl:
            def __init__(self, arguments):
                self.target = Path(arguments[arguments.index("--output") + 1])
                self.returncode = None

            def poll(self):
                if chunks:
                    with self.target.open("ab") as output:
                        output.write(chunks.pop(0))
                    return None
                self.returncode = 0
                return self.returncode

            def communicate(self):
                return "", ""

            def kill(self):
                self.returncode = -9

        def record_status(*args, **kwargs):
            if kwargs.get("phase") == "download":
                progress.append(dict(kwargs))
            return write_status(*args, **kwargs)

        def run_command(*args, timeout=180):
            if args[:2] == ("docker", "load"):
                return f"Loaded image: ghcr.io/{self.updater.repository.lower()}:{self.release.version}\n"
            if args[:4] == (
                "docker",
                "image",
                "inspect",
                f"ghcr.io/{self.updater.repository.lower()}:{self.release.version}",
            ):
                return self.release.digest
            self.fail(f"Unexpected command: {args}")

        with (
            patch("apply.subprocess.Popen", side_effect=lambda args, **_: FakeCurl(args)),
            patch("apply.command", side_effect=run_command),
            patch("apply.time.sleep"),
            patch.object(self.updater, "status", side_effect=record_status),
        ):
            image = self.updater.load_release_archive(self.release, job)

        self.assertEqual(image, f"ghcr.io/{self.updater.repository.lower()}:{self.release.version}")
        self.assertGreaterEqual(len(progress), 3)
        downloaded = [item["downloaded_bytes"] for item in progress]
        self.assertEqual(downloaded, sorted(downloaded))
        self.assertEqual(progress[-1]["downloaded_bytes"], len(self.archive))
        self.assertEqual(progress[-1]["total_bytes"], len(self.archive))
        self.assertEqual(progress[-1]["download_percent"], 100.0)
        self.assertGreaterEqual(progress[-1]["download_speed_bytes_per_second"], 0)
        self.assertTrue(progress[-1]["download_last_progress_at"])
        self.assertEqual(
            json.loads((self.updater.shared / "status.json").read_text())["phase"],
            "load_image",
        )

    def test_invalid_archive_digest_prevents_docker_load(self):
        self.release.archive_digest = "sha256:" + "b" * 64

        def download_only(*args, timeout=180):
            if args[0] == "curl":
                Path(args[args.index("--output") + 1]).write_bytes(self.archive)
                return ""
            self.fail("An archive with a bad digest must not be loaded")

        with patch("apply.command", side_effect=download_only):
            with self.assertRaisesRegex(UpdateError, "SHA-256"):
                self.updater.load_release_archive(self.release)


if __name__ == "__main__":
    unittest.main()
