# 设备管理平台 - 简化部署镜像
# 包含 Django后端 + Vue前端 + Nginx

FROM docker:24.0.7-cli AS docker-cli
FROM python:3.10-slim AS backend-builder

WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 前端构建阶段
FROM node:22-alpine AS frontend-builder

WORKDIR /app
COPY frontend/package*.json ./
RUN sed -i 's|https://registry.npmmirror.com/|https://registry.npmjs.org/|g' package-lock.json && npm ci
COPY frontend/ .
RUN npm run build

# 最终镜像
FROM python:3.10-slim

ARG DMP_VERSION=dev
ENV DMP_VERSION=${DMP_VERSION}
LABEL org.opencontainers.image.version=${DMP_VERSION}

LABEL maintainer="Yanxicoder"
LABEL description="Device Management Platform - All-in-One"

RUN sed -i 's|http://deb.debian.org/|https://deb.debian.org/|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=20 update && apt-get install -y --no-install-recommends \
    nginx \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制Python依赖
COPY --from=backend-builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

# 复制后端代码
COPY server/ /app/

# 复制 device-agent 脚本（供下载）
COPY device-agent/ /app/device-agent/

# 复制前端构建产物
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# 复制Nginx配置
COPY deployment/deploy-simple/nginx.conf /etc/nginx/nginx.conf

# 创建数据目录
RUN mkdir -p /app/data /app/media /app/staticfiles

# 复制启动脚本
COPY deployment/deploy-simple/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# 暴露端口
EXPOSE 8081

# 启动
CMD ["/entrypoint.sh"]

