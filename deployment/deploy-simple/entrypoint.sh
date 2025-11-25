#!/bin/bash
set -e

echo "=========================================="
echo "设备管理平台启动中..."
echo "=========================================="

# 使用SQLite，数据存储在/app/data
export DATABASE_URL="sqlite:////app/data/db.sqlite3"

cd /app

# 数据库迁移
echo "[1/4] 数据库迁移..."
python manage.py migrate --noinput

# 收集静态文件
echo "[2/4] 收集静态文件..."
python manage.py collectstatic --noinput

# 创建超级用户（如果不存在）
echo "[3/4] 检查管理员账户..."
python manage.py shell -c "
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('创建管理员账户: admin / admin123')
else:
    print('管理员账户已存在')
"

# 启动服务
echo "[4/4] 启动服务..."
echo ""
echo "=========================================="
echo "平台启动成功!"
echo "访问地址: http://服务器IP:8081"
echo "管理后台: http://服务器IP:8081/admin/"
echo "默认账户: admin / admin123"
echo "=========================================="
echo ""

# 启动Nginx（后台）
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

