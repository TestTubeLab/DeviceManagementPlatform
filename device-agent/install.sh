#!/bin/bash
#
# 一键安装脚本 - 在新设备上运行
# 用法：curl -fsSL http://your-cloud.com/install.sh | bash
#

set -e

echo "=========================================="
echo " 设备管理平台 - 自动安装"
echo "=========================================="

# 检查root权限
if [ "$EUID" -ne 0 ]; then 
    echo "请使用root权限运行此脚本"
    exit 1
fi

# 配置参数
CLOUD_SERVER="${CLOUD_SERVER:-http://your-cloud.com/api}"
FRP_VERSION="0.51.3"
PYTHON_BIN="/usr/bin/python3"

# 步骤1：安装Docker（如果未安装）
echo ""
echo "[1/6] 检查Docker..."
if ! command -v docker &> /dev/null; then
    echo "正在安装Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "✓ Docker安装完成"
else
    echo "✓ Docker已安装"
fi

# 步骤2：安装Python3和Agent运行依赖
echo ""
echo "[2/6] 检查Python3..."
if [ ! -x "$PYTHON_BIN" ]; then
    apt-get update
    apt-get install -y python3
    echo "✓ Python3安装完成"
else
    echo "✓ Python3已安装"
fi

echo "检查 Agent 运行依赖..."
if ! "$PYTHON_BIN" -c "import requests, psutil, yaml" >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3-requests python3-psutil python3-yaml
    echo "✓ Agent 依赖安装完成"
else
    echo "✓ Agent 依赖已安装"
fi

# 步骤3：创建工作目录
echo ""
echo "[3/6] 创建工作目录..."
mkdir -p /opt/bootstrap
mkdir -p /opt/device-agent
mkdir -p /etc/frp
mkdir -p /work/config
mkdir -p /work/localstore

# 步骤4：下载 frpc 二进制
echo ""
echo "[4/6] 安装 frpc 内网穿透客户端..."
if [ -f /usr/local/bin/frpc ]; then
    echo "✓ frpc 已存在"
else
    # 检测架构
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        FRP_ARCH="arm64"
    elif [ "$ARCH" = "x86_64" ]; then
        FRP_ARCH="amd64"
    else
        echo "⚠ 不支持的架构: $ARCH，跳过 frpc 安装"
        FRP_ARCH=""
    fi
    
    if [ -n "$FRP_ARCH" ]; then
        FRP_URL="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${FRP_ARCH}.tar.gz"
        echo "下载 frpc: $FRP_URL"
        
        cd /tmp
        curl -fsSL "$FRP_URL" -o frp.tar.gz
        tar -xzf frp.tar.gz
        cp frp_${FRP_VERSION}_linux_${FRP_ARCH}/frpc /usr/local/bin/frpc
        chmod +x /usr/local/bin/frpc
        rm -rf frp.tar.gz frp_${FRP_VERSION}_linux_${FRP_ARCH}
        cd -
        
        echo "✓ frpc 安装完成"
    fi
fi

# 步骤5：下载Bootstrap Agent
echo ""
echo "[5/6] 下载Bootstrap Agent..."
curl -fsSL ${CLOUD_SERVER%/api}/static/bootstrap-agent.py -o /opt/bootstrap/agent.py
chmod +x /opt/bootstrap/agent.py

# 写入环境变量
cat > /opt/bootstrap/.env <<EOF
CLOUD_SERVER=$CLOUD_SERVER
EOF

# 步骤6：创建systemd服务
echo ""
echo "[6/6] 配置自启动服务..."
cat > /etc/systemd/system/bootstrap-agent.service <<EOF
[Unit]
Description=Bootstrap Agent - Zero-Touch Provisioning
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bootstrap
EnvironmentFile=/opt/bootstrap/.env
ExecStart=$PYTHON_BIN /opt/bootstrap/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 重载systemd并启动服务
systemctl daemon-reload
systemctl enable bootstrap-agent
systemctl start bootstrap-agent

echo ""
echo "=========================================="
echo "✓ 安装完成！"
echo "=========================================="
echo ""
echo "设备已注册到云端，等待管理员部署..."
echo "FRP 内网穿透将在设备注册时自动配置"
echo ""
echo "查看日志："
echo "  sudo journalctl -u bootstrap-agent -f"
echo ""
echo "停止服务："
echo "  sudo systemctl stop bootstrap-agent"
echo ""
