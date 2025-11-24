FROM python:3.10-slim

LABEL maintainer="YMS Tech <tech@yms.com>"
LABEL description="Device Management Platform - Django Backend"

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY ../requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 收集静态文件
RUN python manage.py collectstatic --noinput

# 暴露端口
EXPOSE 8000

# 启动命令（由docker-compose覆盖）
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000"]

