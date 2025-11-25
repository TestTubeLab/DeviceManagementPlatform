# 设备管理平台 - 简化部署镜像
# 包含 Django后端 + Vue前端 + Nginx

FROM python:3.10-slim AS backend-builder

WORKDIR /app
COPY server/requirements.txt .
# 使用阿里云PyPI镜像加速
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

# 前端构建阶段
FROM node:18-alpine AS frontend-builder

WORKDIR /app
# 使用淘宝npm镜像加速
RUN npm config set registry https://registry.npmmirror.com
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# 最终镜像
FROM python:3.10-slim

LABEL maintainer="Yanxicoder"
LABEL description="Device Management Platform - All-in-One"

# 使用阿里云Debian镜像加速，安装必要工具
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    apt-get update && apt-get install -y \
    nginx \
    curl \
    ca-certificates \
    gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制Python依赖
COPY --from=backend-builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# 复制后端代码
COPY server/ /app/

# 复制前端构建产物
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# 复制Nginx配置
COPY deployment/deploy-simple/nginx.conf /etc/nginx/nginx.conf

# 创建数据目录
RUN mkdir -p /app/data /app/media /app/staticfiles

# 复制启动脚本
COPY deployment/deploy-simple/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 暴露端口
EXPOSE 8081

# 启动
CMD ["/entrypoint.sh"]

