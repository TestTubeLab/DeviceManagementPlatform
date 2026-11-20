"""Audit persistence, redaction and bounded retention for platform events."""
import hashlib
import logging
import re
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import DeviceLogTask, SystemLog

logger = logging.getLogger(__name__)
_cleanup_lock = threading.Lock()
_last_cleanup = float('-inf')
SENSITIVE_KEY = re.compile(r'password|passwd|secret|token|authorization|api[_-]?key|private[_-]?key', re.I)


def redact_text(value, secrets=()):
    """Remove credential values without retaining request bodies or local variables."""
    text = str(value or '')
    configured = [getattr(settings, 'SECRET_KEY', ''), getattr(settings, 'FRP_CONFIG', {}).get('token', '')]
    for secret in [*configured, *secrets]:
        if isinstance(secret, str) and secret:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(?i)\b(Bearer|Token)\s+[\w.\-]+', r'\1 [REDACTED]', text)
    text = re.sub(
        r'''(?ix)(["']?(?:password|passwd|secret|token|authorization|api[_-]?key)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''',
        r'\1[REDACTED]', text,
    )
    return re.sub(r'(://[^\s:/]+:)[^\s@]+@', r'\1[REDACTED]@', text)


def request_secrets(data):
    """Extract only credential values for redaction; never persist input payloads."""
    if not isinstance(data, dict):
        return []
    result = []
    for key, value in data.items():
        if SENSITIVE_KEY.search(str(key)) and isinstance(value, str):
            result.append(value)
        elif isinstance(value, dict):
            result.extend(request_secrets(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result.extend(request_secrets(item))
    return result


def cleanup_logs():
    """At most hourly per worker, with bounded batches and no background daemon."""
    global _last_cleanup
    if time.monotonic() - _last_cleanup < 3600 or not _cleanup_lock.acquire(blocking=False):
        return
    try:
        days = max(1, int(getattr(settings, 'SYSTEM_LOG_RETENTION_DAYS', 90)))
        queries = [
            SystemLog.objects.filter(timestamp__lt=timezone.now() - timedelta(days=days)),
            DeviceLogTask.objects.filter(status__in=['completed', 'failed'], created_at__lt=timezone.now() - timedelta(days=7)),
        ]
        for query in queries:
            for _ in range(5):
                ids = list(query.order_by('pk').values_list('pk', flat=True)[:1000])
                if not ids:
                    break
                query.model.objects.filter(pk__in=ids).delete()
        _last_cleanup = time.monotonic()
    finally:
        _cleanup_lock.release()


def record_system_log(secrets=(), **event):
    """Best-effort observability must never change a successful business result."""
    try:
        limits = {'actor': 150, 'target': 300, 'message': 2000, 'detail': 16000, 'device_id': 100, 'task_id': 100}
        for key, limit in limits.items():
            if key in event:
                event[key] = redact_text(event[key], secrets)[:limit]
        # A savepoint prevents audit failures from breaking an outer transaction.
        with transaction.atomic():
            if event.get('event_key'):
                key = event.pop('event_key')
                if len(key) > 200:
                    key = hashlib.sha256(key.encode('utf-8')).hexdigest()
                SystemLog.objects.get_or_create(event_key=key, defaults=event)
            else:
                SystemLog.objects.create(**event)
    except Exception:
        logger.error('System log persistence failed; audit event unavailable')
        return
    try:
        cleanup_logs()
    except Exception:
        logger.error('System log retention cleanup failed')
