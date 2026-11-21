#!/usr/bin/env bash
# 仅生成本平台的 TLS 文件，不修改防火墙、Compose 配置或运行中的容器。
set -euo pipefail
umask 077

host="${1:-}"
tls_dir="${DMP_SSH_TLS_DIR:-/etc/device-platform/ssh-management-tls}"
if [[ $# -ne 1 || ! "$host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ || "$tls_dir" != /* ]]; then
    echo '用法: bash setup-ssh-management-tls.sh <设备可访问的IPv4地址或DNS名称>' >&2
    exit 2
fi
if [[ -L "$tls_dir" || -L "$tls_dir/server" ]]; then
    echo '证书目录不能是符号链接' >&2
    exit 1
fi

install -d -m 0700 "$tls_dir" "$tls_dir/server"
exec 9>"$tls_dir/.lock"
flock -x 9
ca_key="$tls_dir/ca.key"
ca_cert="$tls_dir/ca.crt"
server_cert="$tls_dir/server/server.crt"
server_key="$tls_dir/server/server.key"
for file in "$ca_key" "$ca_cert" "$server_cert" "$server_key"; do
    if [[ -L "$file" ]]; then
        echo '证书文件不能是符号链接' >&2
        exit 1
    fi
done

if [[ -e "$ca_key" || -e "$ca_cert" ]]; then
    if [[ ! -s "$ca_key" || ! -s "$ca_cert" ]] ||
        ! cmp -s <(openssl pkey -in "$ca_key" -pubout) <(openssl x509 -in "$ca_cert" -pubkey -noout); then
        echo '已有 CA 不完整或密钥不一致，拒绝自动重建' >&2
        exit 1
    fi
else
    openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
        -keyout "$ca_key" -out "$ca_cert" -subj '/CN=DeviceManagementPlatform SSH CA' \
        -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
        -addext 'keyUsage=critical,keyCertSign,cRLSign'
fi

case "$host" in
    *[!0-9.]* ) san="DNS:$host"; verify_host=-verify_hostname ;;
    * ) san="IP:$host"; verify_host=-verify_ip ;;
esac
if [[ "$host" != 127.0.0.1 ]]; then
    san="$san,IP:127.0.0.1"
fi

if [[ -s "$server_key" && -s "$server_cert" ]] &&
    openssl x509 -checkend 2592000 -noout -in "$server_cert" >/dev/null &&
    openssl verify -CAfile "$ca_cert" -purpose sslserver "$verify_host" "$host" "$server_cert" >/dev/null &&
    openssl verify -CAfile "$ca_cert" -verify_ip 127.0.0.1 "$server_cert" >/dev/null &&
    cmp -s <(openssl pkey -in "$server_key" -pubout) <(openssl x509 -in "$server_cert" -pubkey -noout); then
    echo '现有 TLS 服务证书有效，未更换'
else
    tmp="$(mktemp -d "$tls_dir/.issue-XXXXXX")"
    trap 'rm -f -- "$tmp/server.key" "$tmp/server.csr" "$tmp/server.crt" "$tmp/server.ext"; rmdir -- "$tmp"' EXIT
    openssl req -new -newkey rsa:2048 -nodes -sha256 \
        -keyout "$tmp/server.key" -out "$tmp/server.csr" -subj "/CN=$host"
    printf '%s\n' 'basicConstraints=critical,CA:FALSE' 'keyUsage=critical,digitalSignature,keyEncipherment' \
        'extendedKeyUsage=serverAuth' "subjectAltName=$san" > "$tmp/server.ext"
    openssl x509 -req -sha256 -days 397 -in "$tmp/server.csr" -CA "$ca_cert" -CAkey "$ca_key" \
        -out "$tmp/server.crt" -extfile "$tmp/server.ext"
    openssl verify -CAfile "$ca_cert" -purpose sslserver "$verify_host" "$host" "$tmp/server.crt"
    mv -- "$tmp/server.key" "$server_key"
    mv -- "$tmp/server.crt" "$server_cert"
    echo 'TLS 服务证书已生成；已有 Nginx 需在验证配置后重新加载'
fi
printf '公开 CA: %s\n' "$ca_cert"
openssl x509 -in "$ca_cert" -noout -fingerprint -sha256
