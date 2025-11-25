# 设备管理平台 - 腾讯云部署指南

## 快速开始（3分钟部署）

### 第一步：上传代码到服务器

**方式A：使用Git（推荐）**
```bash
# 在云服务器上执行
cd ~
git clone https://github.com/你的用户名/DeviceManagementPlatform.git
cd DeviceManagementPlatform
```

**方式B：手动打包上传**
```bash
# 在本地Windows上执行（PowerShell）
cd D:\yms\DeviceManagementPlatform

# 打包项目（排除不需要的文件）
tar --exclude='node_modules' --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='db.sqlite3' -czvf device-platform.tar.gz *

# 使用scp上传（替换为你的服务器信息）
scp device-platform.tar.gz root@你的服务器IP:~/
```

```bash
# 在云服务器上解压
cd ~
mkdir -p DeviceManagementPlatform
cd DeviceManagementPlatform
tar -xzvf ../device-platform.tar.gz
```

### 第二步：一键部署

```bash
# 进入部署目录
cd ~/DeviceManagementPlatform/deployment/deploy-simple

# 添加执行权限并运行
chmod +x deploy.sh
./deploy.sh 8081    # 端口可自定义，避免与朋友的服务冲突
```

### 第三步：验证部署

```bash
# 检查容器状态
docker ps

# 查看日志
docker logs device-platform

# 测试API
curl http://localhost:8081/api/devices/
```

---

## 完成后的使用流程

### 1. 访问管理界面
打开浏览器访问: `http://你的服务器IP:8081`
- 默认管理员: `admin / admin123`

### 2. 开发板安装Agent
在开发板上执行一条命令：
```bash
curl -fsSL http://你的服务器IP:8081/api/install.sh | sudo bash
```

### 3. 开始管理
- 开发板自动注册到平台
- 在Web界面创建项目、上传镜像/代码
- 一键部署到所有设备

---

## 常用运维命令

### 查看日志
```bash
docker logs -f device-platform
```

### 重启服务
```bash
cd ~/DeviceManagementPlatform/deployment/deploy-simple
docker compose restart
```

### 停止服务
```bash
docker compose down
```

### 更新部署
```bash
# 拉取最新代码
cd ~/DeviceManagementPlatform
git pull

# 重新构建并部署
cd deployment/deploy-simple
docker compose down
docker compose build --no-cache
docker compose up -d
```

### 备份数据
```bash
# 数据存储在Docker volume中
docker cp device-platform:/app/data ./backup_data
docker cp device-platform:/app/media ./backup_media
```

### 恢复数据
```bash
docker cp ./backup_data device-platform:/app/
docker cp ./backup_media device-platform:/app/
docker compose restart
```

---

## 端口冲突解决

如果8081端口被占用：
```bash
# 查看端口占用
netstat -tlnp | grep 8081

# 使用其他端口部署
./deploy.sh 9000
```

---

## 防火墙配置

### 腾讯云安全组
1. 登录腾讯云控制台
2. 找到你的云服务器 → 安全组
3. 添加入站规则：
   - 协议: TCP
   - 端口: 8081（或你选择的端口）
   - 来源: 0.0.0.0/0

### 服务器防火墙（如果启用了）
```bash
# Ubuntu/Debian
sudo ufw allow 8081/tcp

# CentOS
sudo firewall-cmd --add-port=8081/tcp --permanent
sudo firewall-cmd --reload
```

---

## 故障排查

### 容器无法启动
```bash
# 查看详细日志
docker compose logs

# 检查端口占用
netstat -tlnp | grep 8081
```

### 前端页面空白
```bash
# 进入容器检查
docker exec -it device-platform bash

# 检查前端文件是否存在
ls -la /usr/share/nginx/html/
```

### 数据库错误
```bash
# 重置数据库（会丢失数据）
docker compose down -v
docker compose up -d
```

---

## 资源需求

- CPU: 1核以上
- 内存: 1GB以上
- 磁盘: 10GB以上（根据镜像存储需求调整）
- 带宽: 无特殊要求

你的4h8g配置完全够用。

---

## 下一步

部署成功后，参考 [项目管理测试指南](./项目管理测试指南.md) 开始使用：
1. 创建项目
2. 上传Docker镜像或代码包
3. 部署到设备

