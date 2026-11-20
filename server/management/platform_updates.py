"""Administrative release checks and the host updater request boundary."""
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from django.core.cache import cache
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.utils.cache import add_never_cache_headers
from rest_framework import serializers
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .platform_release import DEFAULT_REPOSITORY, ReleaseError, latest_release, version_key


ACTIVE = {"queued", "preparing", "switching", "rolling_back"}


def running_version():
    return os.environ.get("DMP_VERSION", "dev")


def update_directory():
    path = os.environ.get("DMP_UPDATE_DIR")
    return Path(path) if path and Path(path).is_absolute() else None


def read_state(directory, name):
    if directory:
        try:
            with (directory / name).open(encoding="utf-8") as source:
                value = json.load(source)
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            pass
    return {}


def update_job(directory):
    status = read_state(directory, "status.json")
    pending = read_state(directory, "request.json")
    if pending and pending.get("id") != status.get("id"):
        return {**pending, "status": "queued"}
    return status or None


def update_metadata(force=False):
    repo = os.environ.get("DMP_RELEASE_REPO", DEFAULT_REPOSITORY)
    key = f"dmp-release:{repo}"
    if not force:
        host = read_state(update_directory(), "release.json")
        if host and host.get("repository") == repo and time.time() - host.get("attempted_at", 0) < 660:
            local = cache.get(key)
            if local is None or (local["checked_at"] or 0) <= (host["checked_at"] or 0):
                return {field: host[field] for field in ("latest", "checked_at", "check_failed")}
        snapshot = cache.get(key)
        if snapshot is not None:
            return snapshot
    try:
        release = latest_release(repo)
        snapshot = {"latest": release.public() if release else None, "checked_at": int(time.time()), "check_failed": False}
        cache.set(key, snapshot, timeout=900)
    except ReleaseError:
        snapshot = {**(cache.get(key + ":last") or {"latest": None, "checked_at": None}), "check_failed": True}
        cache.set(key, snapshot, timeout=30)
    else:
        cache.set(key + ":last", snapshot, timeout=86400)
    return snapshot


def available_version(snapshot):
    current = version_key(running_version())
    newest = version_key((snapshot["latest"] or {}).get("version"))
    return current is not None and newest is not None and newest > current


def host_ready(directory):
    heartbeat = read_state(directory, "worker.json").get("checked_at")
    return isinstance(heartbeat, (int, float)) and 0 <= time.time() - heartbeat < 90


def enqueue_update(directory, version, actor):
    """Publish a complete request without overwriting another operator's request."""
    job = {
        "id": uuid4().hex, "version": version, "actor": actor, "created_at": int(time.time()),
    }
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, encoding="utf-8", delete=False) as stream:
        temp = Path(stream.name)
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(job, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, directory / "request.json")
    finally:
        temp.unlink(missing_ok=True)
    return {**job, "status": "queued"}


class PlatformReleaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        snapshot = update_metadata(force=request.query_params.get("refresh") == "true")
        directory = update_directory()
        return Response({
            **snapshot,
            "current_version": running_version(),
            "update_available": available_version(snapshot),
            "updater_ready": host_ready(directory),
            "job": update_job(directory) if request.user.is_staff else None,
        }, headers={"Cache-Control": "no-store"})


class PlatformUpdateRequest(serializers.Serializer):
    version = serializers.RegexField(r"^v(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z")


class PlatformUpdateView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = PlatformUpdateRequest(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = serializer.validated_data["version"]
        directory = update_directory()
        job = update_job(directory)
        if job and job.get("status") in ACTIVE | {"recovery_required"}:
            return Response({"detail": "已有平台更新正在处理。"}, status=409)
        if not host_ready(directory):
            return Response({"detail": "宿主机更新服务尚未就绪。"}, status=503)
        snapshot = update_metadata(force=True)
        if snapshot["check_failed"]:
            return Response({"detail": "无法验证 GitHub 发布，请稍后重试。"}, status=503)
        if not available_version(snapshot) or snapshot["latest"]["version"] != target:
            return Response({"detail": "目标版本已变化，请重新检查更新。"}, status=409)
        try:
            latest_job = update_job(directory)
            if latest_job and latest_job.get("status") in ACTIVE | {"recovery_required"}:
                return Response({"detail": "已有平台更新正在处理。"}, status=409)
            return Response(enqueue_update(directory, target, request.user.get_username()), status=202)
        except FileExistsError:
            return Response({"detail": "已有平台更新正在处理。"}, status=409)
        except OSError:
            return Response({"detail": "无法提交平台更新，请检查宿主机更新服务。"}, status=503)


def platform_health(request):
    """Report application and database readiness, including the running image version."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM django_migrations LIMIT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    response = JsonResponse({"status": "ok", "version": running_version()})
    add_never_cache_headers(response)
    return response
