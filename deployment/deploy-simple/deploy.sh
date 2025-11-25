#!/bin/bash
# 设备管理平台 - 云服务器一键部署脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}"
echo "=========================================="
echo "  设备管理平台 - 云服务器部署"
echo "=========================================="
echo -e "${NC}"

# 检查Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: 未安装Docker${NC}"
    echo "请先安装Docker: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}错误: 未安装Docker Compose${NC}"
    exit 1
fi

# 获取部署端口（默认8081）
PORT=${1:-8081}

# 获取服务器公网IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s ip.sb 2>/dev/null || echo "YOUR_SERVER_IP")

echo -e "${YELLOW}部署配置:${NC}"
echo "  端口: $PORT"
echo "  服务器IP: $SERVER_IP"
echo ""

# 创建.env文件
cat > .env << EOF
PORT=$PORT
SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || echo "change-this-secret-key-in-production")
SERVER_URL=http://$SERVER_IP:$PORT
EOF

echo -e "${GREEN}[1/3] 构建Docker镜像...${NC}"
docker compose build --no-cache

echo -e "${GREEN}[2/3] 启动服务...${NC}"
docker compose up -d

echo -e "${GREEN}[3/3] 等待服务就绪...${NC}"
sleep 10

# 检查服务状态
if docker compose ps | grep -q "Up"; then
    echo -e "${GREEN}"
    echo "=========================================="
    echo "  部署成功!"
    echo "=========================================="
    echo -e "${NC}"
    echo ""
    echo -e "  ${YELLOW}Web管理界面:${NC} http://$SERVER_IP:$PORT"
    echo -e "  ${YELLOW}Django管理后台:${NC} http://$SERVER_IP:$PORT/admin/"
    echo ""
    echo -e "  ${YELLOW}默认管理员账户:${NC}"
    echo "    用户名: admin"
    echo "    密码: admin123"
    echo ""
    echo -e "  ${YELLOW}设备安装命令:${NC}"
    echo "    curl -fsSL http://$SERVER_IP:$PORT/api/install.sh | sudo bash"
    echo ""
    echo "=========================================="
else
    echo -e "${RED}部署失败，请查看日志:${NC}"
    docker compose logs
    exit 1
fi

