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

# 步骤1：安装Docker（如果未安装）
echo ""
echo "[1/5] 检查Docker..."
if ! command -v docker &> /dev/null; then
    echo "正在安装Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "✓ Docker安装完成"
else
    echo "✓ Docker已安装"
fi

# 步骤2：安装Python3（如果未安装）
echo ""
echo "[2/5] 检查Python3..."
if ! command -v python3 &> /dev/null; then
    apt-get update
    apt-get install -y python3 python3-pip
    echo "✓ Python3安装完成"
else
    echo "✓ Python3已安装"
fi

# 安装依赖库
pip3 install requests -q

# 步骤3：创建工作目录
echo ""
echo "[3/5] 创建工作目录..."
mkdir -p /opt/bootstrap
mkdir -p /work/config
mkdir -p /work/localstore

# 步骤4：下载Bootstrap Agent
echo ""
echo "[4/5] 下载Bootstrap Agent..."
curl -fsSL ${CLOUD_SERVER%/api}/static/bootstrap-agent.py -o /opt/bootstrap/agent.py
chmod +x /opt/bootstrap/agent.py

# 写入环境变量
cat > /opt/bootstrap/.env <<EOF
CLOUD_SERVER=$CLOUD_SERVER
EOF

# 步骤5：创建systemd服务
echo ""
echo "[5/5] 配置自启动服务..."
cat > /etc/systemd/system/bootstrap-agent.service <<EOF
[Unit]
Description=Bootstrap Agent - Zero-Touch Provisioning
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bootstrap
EnvironmentFile=/opt/bootstrap/.env
ExecStart=/usr/bin/python3 /opt/bootstrap/agent.py
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
echo ""
echo "查看日志："
echo "  sudo journalctl -u bootstrap-agent -f"
echo ""
echo "停止服务："
echo "  sudo systemctl stop bootstrap-agent"
echo ""


