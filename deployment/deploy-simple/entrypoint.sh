#!/bin/bash
set -euo pipefail

echo "=========================================="
echo "设备管理平台启动中..."
echo "=========================================="

# 使用SQLite，数据存储在/app/data
export DATABASE_URL="sqlite:////app/data/db.sqlite3"

cd /app

# A partial schema must never be reported as a healthy application.
echo "[1/4] 数据库迁移..."
python manage.py migrate --noinput

echo "[2/5] 同步 FRP 防火墙端口策略..."
python manage.py sync_frp_firewall_policy

# 收集静态文件
echo "[3/5] 收集静态文件..."
python manage.py collectstatic --noinput

# 创建超级用户（如果不存在）
echo "[4/5] 检查管理员账户..."
if [[ "${DEVICE_SSH_BUILTIN_TLS:-0}" == 1 ]]; then
    # 开启管理入口前，确认没有沿用旧版的已知默认管理员密码。
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
for user in User.objects.filter(is_active=True, is_staff=True):
    if user.check_password('admin123'):
        raise SystemExit('启用内置 TLS 前必须修改已知默认管理员密码')
if not User.objects.filter(is_active=True, is_superuser=True).exists():
    print('尚未创建管理员；启动后请从可信控制台运行 manage.py createsuperuser')
"
else
python manage.py shell -c "
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('创建管理员账户: admin / admin123')
else:
    print('管理员账户已存在')
"
fi

# 启动服务
echo "[5/5] 启动服务..."
echo ""
echo "=========================================="
echo "平台启动成功!"
if [[ "${DEVICE_SSH_BUILTIN_TLS:-0}" == 1 ]]; then
    echo "管理入口: HTTPS 8443"
    echo "旧设备接口: HTTP 8081"
else
    echo "访问地址: http://服务器IP:8081"
    echo "管理后台: http://服务器IP:8081/admin/"
fi
echo "=========================================="
echo ""

# 可选平台内置 TLS。缺少所需文件时报错，不把敏感请求回退到 HTTP。
if [[ "${DEVICE_SSH_BUILTIN_TLS:-0}" == 1 ]]; then
    tls_dir=/etc/nginx/ssh-management-tls
    if ! grep -Fq 'include /run/device-platform-nginx/*.conf;' /etc/nginx/nginx.conf ||
        ! grep -Fq 'limit_req zone=dmp_login' /etc/nginx/nginx.conf; then
        echo '内置 TLS 需要发行镜像的 Nginx 配置，请检查是否挂载了旧版配置' >&2
        exit 1
    fi
    if [[ ! -s "$tls_dir/server.crt" || ! -s "$tls_dir/server.key" ]]; then
        echo '内置 TLS 已启用，但缺少服务器证书或私钥' >&2
        exit 1
    fi
    mkdir -p /run/device-platform-nginx
    cat > /run/device-platform-nginx/ssh-tls.conf <<'NGINX'
listen 8443 ssl;
ssl_certificate /etc/nginx/ssh-management-tls/server.crt;
ssl_certificate_key /etc/nginx/ssh-management-tls/server.key;
ssl_protocols TLSv1.2 TLSv1.3;
NGINX
    cat > /run/device-platform-nginx/ssh-tls.location <<'NGINX'
if ($scheme = http) { return 403 "Use the trusted HTTPS management endpoint.\n"; }
NGINX
fi

# 启动Nginx（后台）
nginx -t
nginx

# 启动Django（前台，使用gunicorn）
exec gunicorn core.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 2 \
    --threads 4 \
    --timeout 600 \
    --graceful-timeout 600 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -

