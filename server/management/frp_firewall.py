"""Publish the desired per-device FRP firewall policy to the root host updater."""
import json
import os
import tempfile
import time
from pathlib import Path

from .models import Device


CONTROLLER_VERSION = 1
STATUS_MAX_AGE_SECONDS = 15


def update_directory():
    path = os.environ.get('DMP_UPDATE_DIR')
    return Path(path) if path and Path(path).is_absolute() else None


def _read_json(path):
    try:
        with path.open(encoding='utf-8') as source:
            value = json.load(source)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def firewall_status(directory, revision):
    if not directory:
        return {
            'state': 'unavailable', 'controller_ready': False, 'policy_applied': False,
            'requested_revision': revision, 'applied_revision': None, 'heartbeat_at': None,
            'error': '宿主机更新目录未挂载',
        }

    status = _read_json(directory / 'frp-firewall-status.json')
    heartbeat = status.get('heartbeat_at')
    ready = (
        status.get('controller_version') == CONTROLLER_VERSION
        and isinstance(heartbeat, (int, float))
        and 0 <= time.time() - heartbeat <= STATUS_MAX_AGE_SECONDS
    )
    applied = ready and status.get('state') == 'applied' and status.get('applied_revision') == revision
    failed = ready and status.get('state') == 'error' and status.get('requested_revision') == revision
    state = 'applied' if applied else ('error' if failed else ('pending' if ready else 'unavailable'))
    return {
        'state': state,
        'controller_ready': ready,
        'policy_applied': applied,
        'requested_revision': revision,
        'applied_revision': status.get('applied_revision'),
        'heartbeat_at': heartbeat,
        'error': status.get('error', '') if state == 'error' else ('' if ready else '宿主机防火墙控制器未就绪'),
    }


def reassignable_after_stop(device):
    requested_at = device.frp_stop_requested_at
    return (
        requested_at is not None
        and not device.frp_enabled
        and device.frp_status == 'disconnected'
        and device.frp_last_check is not None
        and device.frp_last_check >= requested_at
    )


def publish_frp_firewall_policy(frp_config):
    """Atomically publish the current reserved ports and each device's access mode."""
    directory = update_directory()
    if not directory or not directory.is_dir():
        return firewall_status(directory, frp_config.firewall_revision)

    try:
        entries = []
        occupied = set()
        devices = Device.objects.order_by('id')
        for device in devices:
            ssh_port, web_port = device.frp_ssh_port, device.frp_web_port
            if ssh_port is None and web_port is None:
                continue
            if (ssh_port is None or web_port is None or web_port != ssh_port + 1
                    or ssh_port < frp_config.port_pool_start
                    or web_port > frp_config.port_pool_end or ssh_port in occupied or web_port in occupied):
                raise ValueError(f'设备 {device.device_id} 的 FRP 端口分配无效或冲突')
            occupied.update((ssh_port, web_port))
            entries.append({
                'device_id': device.device_id,
                'ssh_port': ssh_port,
                'web_port': web_port,
                'public_access': bool(frp_config.is_active and device.frp_enabled and device.frp_public_access),
            })

        payload = {
            'schema_version': CONTROLLER_VERSION,
            'revision': frp_config.firewall_revision,
            'port_pool_start': frp_config.port_pool_start,
            'port_pool_end': frp_config.port_pool_end,
            'devices': entries,
        }
        target = directory / 'frp-firewall-policy.json'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=directory, prefix='.frp-firewall-', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, separators=(',', ':'))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        state = firewall_status(directory, frp_config.firewall_revision)
        state.update(state='error', policy_applied=False, error=str(exc)[:1000])
        return state

    return firewall_status(directory, frp_config.firewall_revision)
