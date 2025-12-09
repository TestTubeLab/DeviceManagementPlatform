#!/bin/bash

echo "=========================================="
echo "设备管理平台启动中..."
echo "=========================================="

# 使用SQLite，数据存储在/app/data
export DATABASE_URL="sqlite:////app/data/db.sqlite3"

cd /app

# 数据库迁移（允许失败，手动处理复杂迁移）
echo "[1/4] 数据库迁移..."
python manage.py migrate --noinput || {
    echo "警告: 迁移可能有错误，尝试修复..."
    # 如果迁移失败，尝试手动创建缺失的表
    python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()
from django.db import connection
cursor = connection.cursor()
# 创建 DeviceConfigHistory 表（如果不存在）
cursor.execute('''
CREATE TABLE IF NOT EXISTS management_deviceconfighistory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_data TEXT NOT NULL,
    applied_by VARCHAR(100) NOT NULL,
    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT 0,
    device_id INTEGER NOT NULL REFERENCES management_device(id) ON DELETE CASCADE
)
''')
connection.commit()
print('DeviceConfigHistory 表已确保存在')
" || echo "表创建跳过"
    echo "继续启动..."
}

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

