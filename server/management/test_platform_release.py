import io
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from .platform_release import ARCHIVE_NAME, PlatformRelease, ReleaseError, latest_release, version_key
from .platform_updates import enqueue_update, update_job


class ReleaseMetadataTests(SimpleTestCase):
    @patch("management.platform_release.urlopen")
    def test_stable_release_requires_a_unique_digest(self, urlopen):
        digest = "sha256:" + "a" * 64
        marker = f"<!-- dmp-image: {digest} -->"
        payload = {"tag_name": "v2.10.0", "body": f"Notes\n{marker}"}
        urlopen.side_effect = lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode())
        release = latest_release()
        self.assertGreater(version_key(release.version), version_key("v2.9.0"))
        self.assertEqual(release.notes, "Notes")
        self.assertNotIn("digest", release.public())
        self.assertEqual(release.image("Org/Repo"), f"ghcr.io/org/repo@{digest}")
        for change in ({"body": "no digest"}, {"body": f"{marker}\n{marker}"}, {"prerelease": True}):
            with patch.dict(payload, change), self.assertRaises(ReleaseError):
                latest_release()
        asset = {"name": ARCHIVE_NAME, "id": 123, "size": 1234, "digest": "sha256:" + "b" * 64}
        with patch.dict(payload, {"assets": [asset]}):
            self.assertEqual(latest_release().archive_digest, asset["digest"])
            asset["size"] = -1
            with self.assertRaises(ReleaseError):
                latest_release()


class PlatformUpdateApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.shared = Path(self.directory.name)
        self.staff = get_user_model().objects.create_user(username="operator", is_staff=True)
        self.viewer = get_user_model().objects.create_user(username="viewer")
        self.release = PlatformRelease("v1.8.0", "sha256:" + "b" * 64, "notes", "", "https://github.com/example/repo/releases")
        context = patch.dict(os.environ, {"DMP_VERSION": "v1.7.3", "DMP_UPDATE_DIR": str(self.shared)})
        context.start()
        self.addCleanup(context.stop)

    @patch("management.platform_updates.latest_release")
    def test_only_staff_can_queue_the_exact_latest_version(self, latest):
        latest.return_value = self.release
        (self.shared / "worker.json").write_text(json.dumps({"checked_at": int(time.time())}))
        for user, version, code in (
            (self.viewer, "v1.8.0", 403),
            (self.staff, "v1.7.9", 409),
            (self.staff, "v1.8.0", 202),
            (self.staff, "v1.8.0", 409),
        ):
            with self.subTest(user=user, version=version, code=code):
                self.client.force_authenticate(user)
                res = self.client.post("/api/platform/updates/", {"version": version}, format="json")
                self.assertEqual(res.status_code, code)
        job = update_job(self.shared)
        self.assertEqual((job["version"], job["status"]), ("v1.8.0", "queued"))
        self.client.force_authenticate(self.viewer)
        response = self.client.get("/api/platform/release/")
        self.assertTrue(response.data["update_available"])
        self.assertIsNone(response.data["job"])

    def test_unavailable_updater_rejects_request_without_network_call(self):
        self.client.force_authenticate(self.staff)
        with patch("management.platform_updates.latest_release") as latest:
            response = self.client.post("/api/platform/updates/", {"version": "v1.8.0"}, format="json")
        self.assertEqual(response.status_code, 503)
        latest.assert_not_called()

    def test_atomic_publication_cannot_overwrite_a_pending_request(self):
        request = enqueue_update(self.shared, "v1.8.0", "operator")
        with self.assertRaises(FileExistsError):
            enqueue_update(self.shared, "v1.8.1", "operator")
        self.assertEqual(update_job(self.shared)["id"], request["id"])

    def test_readiness_checks_django_and_returns_running_version(self):
        response = self.client.get("/api/platform/health/")
        self.assertEqual(response.json(), {"status": "ok", "version": "v1.7.3"})
