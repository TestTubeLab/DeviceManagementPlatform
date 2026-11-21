#!/usr/bin/env bash
# 使用空数据卷和无外网容器验证发行镜像的 TLS 管理入口。
set -euo pipefail

image="${1:?指定待验证的本地镜像}"
name="dmp-ssh-tls-qa-$$"
volume="$name-certs"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MSYS_NO_PATHCONV=1

cleanup() {
    local status=$?
    if ((status != 0)); then
        docker logs --tail 30 "$name" 2>/dev/null || true
    fi
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "$volume" >/dev/null
docker run --rm -i --network none -v "$volume:/fixture" -e DMP_SSH_TLS_DIR=/fixture \
    --entrypoint bash "$image" -s -- 127.0.0.1 < "$here/setup-ssh-management-tls.sh"
docker run --rm -i --network none -v "$volume:/fixture" -e DMP_SSH_TLS_DIR=/fixture \
    --entrypoint bash "$image" -s -- 127.0.0.1 < "$here/setup-ssh-management-tls.sh"
docker run -d --network none --name "$name" --tmpfs /app/data \
    --mount "type=volume,source=$volume,target=/etc/nginx/ssh-management-tls,volume-subpath=server,readonly" \
    -v "$volume:/fixture:ro" \
    -e DEVICE_SSH_BUILTIN_TLS=1 -e DEVICE_SSH_MANAGEMENT_ENABLED=1 -e DEVICE_SSH_TRUST_HTTPS_PROXY=1 \
    -e DEVICE_SSH_PUBLIC_URL=https://127.0.0.1:8443/api "$image" >/dev/null

docker exec -i "$name" python - <<'PY'
import json
from pathlib import Path
import subprocess
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

http = 'http://127.0.0.1:8081'
https = 'https://127.0.0.1:8443'
trusted = ssl.create_default_context(cafile='/fixture/ca.crt')


def status(url, *, payload=None, headers=None, context=None):
    request = Request(url, headers=headers or {}, data=payload)
    try:
        with urlopen(request, timeout=2, context=context) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


for attempt in range(25):
    try:
        code, data = status(https + '/health', context=trusted)
        if code == 200 and json.loads(data)['status'] == 'ok':
            break
    except URLError:
        pass
    time.sleep(0.5)
else:
    raise AssertionError('TLS health check did not become ready')

assert status(http + '/health')[0] == 200
assert status(http + '/login')[0] == 403
assert status(https + '/login', context=trusted)[0] == 200
try:
    status(https + '/health')
except URLError as exc:
    assert isinstance(exc.reason, ssl.SSLCertVerificationError)
else:
    raise AssertionError('Untrusted CA was accepted')
fake_agent = {'Authorization': 'Bearer ' + 'a' * 43, 'Content-Type': 'application/json'}
poll = '/api/agent/ssh-management/DEV-qa/poll/'
assert status(http + poll, payload=b'{}', headers={**fake_agent, 'X-Forwarded-Proto': 'https'})[0] == 403
assert status(https + poll, payload=b'{}', headers=fake_agent, context=trusted)[0] == 403
sandbox_user = 'dmp-ssh-fixture'
subprocess.run(['useradd', '-M', '-s', '/bin/sh', sandbox_user], check=True)
subprocess.run(['python', 'manage.py', 'shell', '-c', (
    'from django.contrib.auth import get_user_model; from management.models import Device; '
    'get_user_model().objects.create_superuser("qa", password="disposable-fixture-password"); '
    'Device.objects.create(device_id="DEV-qa")'
)], check=True, capture_output=True)

def json_post(url, payload, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Token ' + token
    return status(url, payload=json.dumps(payload).encode(), headers=headers, context=trusted)


login = https + '/api/auth/login/'
code, data = json_post(login, {'username': 'qa', 'password': 'disposable-fixture-password'})
assert code == 200, code
token = json.loads(data)['token']
device_api = https + '/api/devices/DEV-qa/ssh-management/'
code, data = json_post(device_api + 'enrollment/', {'account': sandbox_user, 'independent_recovery_verified': False}, token)
assert code == 201, code
Path('/etc/device-id').write_text('DEV-qa\n')
subprocess.run(
    ['python', '/app/device-agent/ssh_management.py', 'enroll', '/fixture/ca.crt'],
    input=data, check=True, capture_output=True,
)
sys.path.insert(0, '/app/device-agent')
from ssh_management import SshManagement

agent = SshManagement('DEV-qa')
agent.poll()
code, data = status(device_api, headers={'Authorization': 'Token ' + token}, context=trusted)
assert code == 200 and json.loads(data)['online']
public_key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHp6enp6enp6enp6enp6enp6enp6enp6enp6enp6enp6 fixture'
code, data = json_post(device_api + 'tasks/', {'operation': 'add_key', 'public_key': public_key}, token)
assert code == 201, code
task_id = json.loads(data)['id']
agent.poll()
agent.poll()
_, data = status(device_api, headers={'Authorization': 'Token ' + token}, context=trusted)
assert any(task['id'] == task_id and task['status'] == 'completed' for task in json.loads(data)['tasks'])
assert public_key in agent.managed_keys().values()
print('PASS: HTTPS administration, Agent enrollment and heartbeat, public key installed and acknowledged')

requests = [
    status(login, payload=b'{}', headers={'Content-Type': 'application/json'}, context=trusted)[0]
    for _ in range(9)
]
assert 400 in requests and 429 in requests, requests
print('PASS: private CA, operator HTTPS, legacy health, forged protocol rejection and login rate limit')
PY
