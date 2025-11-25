# 安装指南

## 一、服务器端部署（腾讯云）

### 1.1 环境要求

- **操作系统**: Ubuntu 20.04 LTS 或更高
- **配置**: 4核8G12M（最低）
- **端口**: 80, 443, 5000（Docker Registry）

### 1.2 安装步骤

#### 步骤1：克隆项目

```bash
cd /opt
git clone https://github.com/your-org/DeviceManagementPlatform.git
cd DeviceManagementPlatform
```

#### 步骤2：配置环境变量

```bash
cd deployment
cp .env.example .env

# 编辑配置文件
vim .env
```

**必须修改的配置项**：
```bash
# 生成强密码
DB_PASSWORD=$(openssl rand -base64 32)

# 生成Django密钥
SECRET_KEY=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')

# 设置域名或IP
ALLOWED_HOSTS=your-cloud.com,123.123.123.123
CLOUD_SERVER_URL=http://your-cloud.com/api
```

#### 步骤3：启动服务

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

#### 步骤4：初始化数据库

```bash
# 进入Django容器
docker exec -it device-mgmt-web bash

# 运行数据库迁移
python manage.py migrate

# 创建管理员账户
python manage.py createsuperuser

# 退出容器
exit
```

#### 步骤5：准备静态文件（设备安装脚本）

```bash
# 复制安装脚本到Nginx目录
docker exec device-mgmt-nginx mkdir -p /usr/share/nginx/html/static
docker cp device-agent/install.sh device-mgmt-nginx:/usr/share/nginx/html/static/
docker cp device-agent/bootstrap-agent.py device-mgmt-nginx:/usr/share/nginx/html/static/
```

#### 步骤6：验证安装

访问以下URL验证：

- 管理后台: `http://your-cloud.com/admin/`
- API健康检查: `http://your-cloud.com/health`
- 设备列表API: `http://your-cloud.com/api/devices/`

---

## 二、设备端部署

### 方式A：使用一键安装脚本（推荐）

在新设备上执行：

```bash
# 设置云端服务器地址
export CLOUD_SERVER=http://your-cloud.com/api

# 运行安装脚本
curl -fsSL http://your-cloud.com/install.sh | bash
```

**安装过程**：
1. 自动安装Docker
2. 安装Python3和依赖
3. 下载Bootstrap Agent
4. 配置systemd自启动服务
5. 设备自动注册到云端

**查看状态**：
```bash
# 查看服务状态
sudo systemctl status bootstrap-agent

# 查看实时日志
sudo journalctl -u bootstrap-agent -f
```

### 方式B：手动安装

#### 步骤1：安装Docker

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
```

#### 步骤2：下载并配置Agent

```bash
# 创建目录
mkdir -p /opt/bootstrap
mkdir -p /work/config

# 下载agent
curl -o /opt/bootstrap/agent.py http://your-cloud.com/static/bootstrap-agent.py
chmod +x /opt/bootstrap/agent.py

# 配置环境变量
cat > /opt/bootstrap/.env <<EOF
CLOUD_SERVER=http://your-cloud.com/api
EOF
```

#### 步骤3：配置systemd服务

```bash
cat > /etc/systemd/system/bootstrap-agent.service <<EOF
[Unit]
Description=Bootstrap Agent
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

# 启动服务
systemctl daemon-reload
systemctl enable bootstrap-agent
systemctl start bootstrap-agent
```

---

## 三、部署主应用到设备

### 3.1 在Web管理界面操作

1. 打开管理后台: `http://your-cloud.com/admin/`
2. 进入 **设备列表**
3. 找到状态为 "等待部署" 的设备
4. 点击设备，选择 **部署项目**
5. 填写配置：
   ```
   目标版本: v1.0.0
   反向Socket主机: 192.168.31.29
   反向Socket端口: 9088
   ```
6. 点击 **开始部署**

### 3.2 部署流程

系统会自动执行以下步骤：
1. ✅ 拉取Docker镜像
2. ✅ 生成配置文件
3. ✅ 创建数据目录
4. ✅ 启动服务容器
5. ✅ 健康检查

部署完成后，设备状态变为 "在线"。

---

## 四、故障排查

### 4.1 服务器端

**问题：无法访问管理后台**

```bash
# 检查容器状态
docker ps

# 查看日志
docker logs device-mgmt-web
docker logs device-mgmt-nginx

# 检查端口
netstat -tuln | grep 80
```

**问题：数据库连接失败**

```bash
# 检查数据库容器
docker logs device-mgmt-db

# 测试连接
docker exec device-mgmt-db psql -U admin -d device_management -c "SELECT 1;"
```

### 4.2 设备端

**问题：设备未注册**

```bash
# 检查网络连接
ping your-cloud.com

# 查看agent日志
journalctl -u bootstrap-agent -n 100

# 检查云端服务器地址
cat /opt/bootstrap/.env
```

**问题：部署失败**

```bash
# 查看详细日志
journalctl -u bootstrap-agent -f

# 检查Docker
docker ps -a
docker logs middleware

# 检查磁盘空间
df -h
```

---

## 五、卸载

### 服务器端

```bash
cd /opt/DeviceManagementPlatform/deployment
docker-compose down -v
rm -rf /opt/DeviceManagementPlatform
```

### 设备端

```bash
# 停止服务
systemctl stop bootstrap-agent
systemctl disable bootstrap-agent

# 删除文件
rm -rf /opt/bootstrap
rm /etc/systemd/system/bootstrap-agent.service
systemctl daemon-reload

# 删除容器
docker stop middleware
docker rm middleware
```

---

## 六、更新

### 服务器端更新

```bash
cd /opt/DeviceManagementPlatform
git pull
cd deployment
docker-compose up -d --build
```

### 设备端OTA更新

在Web管理界面：
1. 进入 **更新管理**
2. 选择要更新的设备
3. 填写目标版本
4. 点击 **批量更新**

系统会自动推送更新到所有选中的设备。


