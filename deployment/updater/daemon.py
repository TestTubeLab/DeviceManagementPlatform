"""Small host service that survives replacement of the platform container."""
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from apply import read, save, write_file
from platform_release import DEFAULT_REPOSITORY, ReleaseError, latest_release

ROOT = Path(os.environ.get("DMP_UPDATE_ROOT", "/var/lib/device-platform-updater"))
SHARED = ROOT / "shared"
APPLY = Path("/opt/device-platform-updater/apply.py")
DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
MANAGED_COMMENT = re.compile(r"^dmp-frp-(public|private)-([A-Za-z0-9][A-Za-z0-9_.-]{0,99})-([1-9][0-9]{0,4})$")
FIREWALLS = ("iptables", "ip6tables")


class FirewallError(Exception):
    """The host firewall could not safely apply the requested FRP policy."""


def validate_firewall_policy(policy):
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise FirewallError("Invalid FRP firewall policy schema")
    revision = policy.get("revision")
    start, end = policy.get("port_pool_start"), policy.get("port_pool_end")
    if (type(revision) is not int or revision < 1 or type(start) is not int or type(end) is not int
            or not 1 <= start <= end <= 65535):
        raise FirewallError("Invalid FRP firewall revision or port range")
    devices = policy.get("devices")
    if not isinstance(devices, list) or len(devices) > 1000:
        raise FirewallError("Invalid FRP firewall device list")

    ports = set()
    device_ids = set()
    normalized = []
    for device in devices:
        if not isinstance(device, dict):
            raise FirewallError("Invalid FRP firewall device entry")
        device_id = device.get("device_id")
        ssh_port, web_port = device.get("ssh_port"), device.get("web_port")
        public_access = device.get("public_access")
        if (not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id) or device_id in device_ids
                or type(ssh_port) is not int or type(web_port) is not int or type(public_access) is not bool
                or web_port != ssh_port + 1 or not start <= ssh_port < web_port <= end
                or ssh_port in ports or web_port in ports):
            raise FirewallError("Invalid or conflicting FRP firewall port assignment")
        device_ids.add(device_id)
        ports.update((ssh_port, web_port))
        normalized.append((device_id, (ssh_port, web_port), public_access))
    return revision, normalized


def firewall_rule_spec(device_id, port, public_access):
    mode = "public" if public_access else "private"
    action = "ACCEPT" if public_access else "DROP"
    comment = f"dmp-frp-{mode}-{device_id}-{port}"
    return comment, [
        "!", "-i", "lo", "-p", "tcp", "--dport", str(port),
        "-m", "comment", "--comment", comment, "-j", action,
    ]


def ensure_firewall_rule(binary, device_id, port, public_access):
    comment, spec = firewall_rule_spec(device_id, port, public_access)
    checked = subprocess.run(
        [binary, "-C", "INPUT", *spec], check=False, capture_output=True, text=True, timeout=10,
    )
    if checked.returncode == 0:
        return comment, None
    if checked.returncode != 1:
        raise FirewallError(f"{binary} could not check the FRP rule: {checked.stderr.strip()[-500:]}")
    inserted = subprocess.run(
        [binary, "-I", "INPUT", "1", *spec], check=False, capture_output=True, text=True, timeout=10,
    )
    if inserted.returncode:
        raise FirewallError(f"{binary} could not install the FRP rule: {inserted.stderr.strip()[-500:]}")
    return comment, spec


def remove_stale_firewall_rules(binary, wanted_comments, removed_rules):
    listed = subprocess.run(
        [binary, "-S", "INPUT"], check=False, capture_output=True, text=True, timeout=10,
    )
    if listed.returncode:
        raise FirewallError(f"{binary} could not inspect INPUT rules: {listed.stderr.strip()[-500:]}")
    for line in listed.stdout.splitlines():
        try:
            tokens = shlex.split(line)
        except ValueError:
            continue
        if len(tokens) < 3 or tokens[:2] != ["-A", "INPUT"]:
            continue
        try:
            comment_index = tokens.index("--comment")
            comment = tokens[comment_index + 1]
        except (ValueError, IndexError):
            continue
        match = MANAGED_COMMENT.fullmatch(comment)
        if not match or comment in wanted_comments:
            continue
        mode, device_id, port_text = match.groups()
        expected_comment, expected_spec = firewall_rule_spec(device_id, int(port_text), mode == "public")
        if comment != expected_comment or tokens[2:] != expected_spec:
            continue
        removed = subprocess.run(
            [binary, "-D", "INPUT", *expected_spec], check=False, capture_output=True, text=True, timeout=10,
        )
        if removed.returncode:
            error = FirewallError(f"{binary} could not remove an obsolete FRP rule: {removed.stderr.strip()[-500:]}")
            error.removed_rules = removed_rules
            raise error
        removed_rules.append((binary, expected_spec))


def apply_firewall_policy(policy):
    """Apply both address families without touching rules owned by other services."""
    revision, devices = validate_firewall_policy(policy)
    wanted = {binary: set() for binary in FIREWALLS}
    added = []
    removed = []
    try:
        for binary in FIREWALLS:
            for device_id, ports, public_access in devices:
                for port in ports:
                    comment, spec = ensure_firewall_rule(binary, device_id, port, public_access)
                    wanted[binary].add(comment)
                    if spec:
                        added.append((binary, spec))
        for binary in FIREWALLS:
            remove_stale_firewall_rules(binary, wanted[binary], removed)
    except (OSError, FirewallError, subprocess.SubprocessError) as exc:
        rollback_errors = []
        for binary, spec in reversed(removed):
            result = subprocess.run(
                [binary, "-I", "INPUT", "1", *spec], check=False,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode:
                rollback_errors.append(f"restore {binary}: {result.stderr.strip()[-300:]}")
        for binary, spec in reversed(added):
            result = subprocess.run(
                [binary, "-D", "INPUT", *spec], check=False,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode:
                rollback_errors.append(f"remove {binary}: {result.stderr.strip()[-300:]}")
        if rollback_errors:
            raise FirewallError(f"{exc}; firewall rollback incomplete: {'; '.join(rollback_errors)}") from exc
        if isinstance(exc, FirewallError):
            raise
        raise FirewallError(f"Firewall command failed: {exc}") from exc
    return {"revision": revision, "rule_count": sum(len(rules) for rules in wanted.values())}


def write_status():
    save(SHARED / "worker.json", {"checked_at": int(time.time())})


def reload_after_updater_sync():
    marker = ROOT / "updater-reload"
    if marker.is_symlink() or not marker.is_file():
        return
    version = marker.read_text(encoding="utf-8").strip()
    marker.unlink()
    print(f"Reloading host updater after syncing release {version}", flush=True)
    try:
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])
    except OSError as exc:
        write_file(marker, f"{version}\n")
        print(f"Could not reload host updater yet: {exc}", flush=True)


def check_release():
    repo = read(ROOT / "config.json").get("repository", DEFAULT_REPOSITORY)
    path = SHARED / "release.json"
    previous = read(path) if path.exists() else {}
    timestamp = int(time.time())
    try:
        release = latest_release(repo)
        result = {"latest": release.public() if release else None, "checked_at": timestamp, "check_failed": False}
    except ReleaseError as exc:
        print(str(exc), flush=True)
        result = {
            "latest": previous.get("latest") if previous.get("repository") == repo else None,
            "checked_at": previous.get("checked_at") if previous.get("repository") == repo else None,
            "check_failed": True,
        }
    save(path, {**result, "repository": repo, "attempted_at": timestamp})


def reconcile_frp_firewall():
    policy_path = SHARED / "frp-firewall-policy.json"
    status_path = SHARED / "frp-firewall-status.json"
    timestamp = int(time.time())
    try:
        status = read(status_path) if status_path.exists() else {}
    except (OSError, ValueError):
        status = {}
    if not isinstance(status, dict):
        status = {}
    result = {
        "controller_version": 1,
        "heartbeat_at": timestamp,
        "state": "ready",
        "requested_revision": None,
        "applied_revision": status.get("applied_revision"),
        "error": "",
    }
    try:
        if policy_path.exists():
            policy = read(policy_path)
            if not isinstance(policy, dict):
                raise FirewallError("Invalid FRP firewall policy document")
            result["requested_revision"] = policy.get("revision")
            last_reconciled = status.get("reconciled_at")
            if (status.get("state") == "applied"
                    and status.get("applied_revision") == policy.get("revision")
                    and isinstance(last_reconciled, (int, float))
                    and timestamp - last_reconciled < 30):
                result.update(
                    state="applied",
                    applied_revision=status["applied_revision"],
                    applied_rule_count=status.get("applied_rule_count", 0),
                    reconciled_at=status["reconciled_at"],
                )
            else:
                applied = apply_firewall_policy(policy)
                result.update(
                    state="applied",
                    applied_revision=applied["revision"],
                    applied_rule_count=applied["rule_count"],
                    reconciled_at=timestamp,
                )
    except (OSError, ValueError, FirewallError, subprocess.SubprocessError) as exc:
        result.update(state="error", error=str(exc)[:1000])
        print(f"FRP firewall policy failed: {exc}", flush=True)
    save(status_path, result)


def main():
    SHARED.mkdir(mode=0o700, parents=True, exist_ok=True)
    reload_after_updater_sync()
    next_check = 0
    while True:
        try:
            reload_after_updater_sync()
            write_status()
            reconcile_frp_firewall()
            status_path = SHARED / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            transaction_exists = (ROOT / "transaction.json").exists()
            if ((SHARED / "request.json").exists()
                    or status.get("status") in {"queued", "preparing", "switching", "rolling_back"}
                    or (transaction_exists and status.get("status") != "recovery_required")):
                result = subprocess.run(
                    [sys.executable, str(APPLY), str(ROOT)],
                    check=False,
                    timeout=15300,
                )
                if result.returncode:
                    print(f"updater task exited with code {result.returncode}", flush=True)
                reload_after_updater_sync()
            if time.monotonic() >= next_check:
                check_release()
                next_check = time.monotonic() + 300
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"updater loop failed: {exc}", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
