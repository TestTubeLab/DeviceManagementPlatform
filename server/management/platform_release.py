"""GitHub Release metadata shared by the API and the host updater."""

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen


VERSION = re.compile(r"v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")
REPOSITORY = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+")
DIGEST_LINE = re.compile(r"^<!-- dmp-image: (sha256:[0-9a-f]{64}) -->$", re.MULTILINE)
DEFAULT_REPOSITORY = "TestTubeLab/DeviceManagementPlatform"


class ReleaseError(Exception):
    """The configured release source could not provide usable metadata."""


def version_key(tag):
    match = VERSION.fullmatch(tag) if isinstance(tag, str) else None
    return tuple(map(int, match.groups())) if match else None


@dataclass(frozen=True)
class PlatformRelease:
    version: str
    digest: str
    notes: str
    published_at: str
    url: str

    def image(self, repository):
        return f"ghcr.io/{repository.lower()}@{self.digest}"

    def public(self):
        return {key: value for key, value in vars(self).items() if key != "digest"}


def latest_release(repository=DEFAULT_REPOSITORY):
    """Read the latest published stable Release from a fixed GitHub repository."""
    if not REPOSITORY.fullmatch(repository):
        raise ReleaseError("Invalid release repository")
    request = Request(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "DeviceManagementPlatform-Updater"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            content = response.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ReleaseError("GitHub release metadata exceeds size limit")
            payload = json.loads(content)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise ReleaseError("GitHub release check failed") from exc
    except (OSError, ValueError) as exc:
        raise ReleaseError("GitHub release check failed") from exc
    if not isinstance(payload, dict):
        raise ReleaseError("Invalid GitHub release metadata")
    tag = payload.get("tag_name")
    notes = payload.get("body")
    if payload.get("draft") or payload.get("prerelease") or not version_key(tag) or not isinstance(notes, str):
        raise ReleaseError("Invalid stable release metadata")
    notes = notes.replace("\r\n", "\n")
    digests = DIGEST_LINE.findall(notes)
    if len(digests) != 1:
        raise ReleaseError("The latest release is missing a unique image digest")
    return PlatformRelease(
        tag,
        digests[0],
        DIGEST_LINE.sub("", notes).strip()[:16000],
        str(payload.get("published_at") or "")[:40],
        f"https://github.com/{repository}/releases/tag/{tag}",
    )
