# 🚀 快速启动指南

## 📋 概览

这是一个**零接触部署**的IoT设备管理平台，让你能在办公室轻松管理现场所有边缘设备。

**核心功能**：
- ✅ 新设备通电→自动注册→Web点击部署
- ✅ 代码更新→自动构建→批量推送到所有设备
- ✅ 实时监控所有设备状态、日志、性能

---

## 🎯 5分钟部署服务器

### 前置条件
- 腾讯云服务器（4C8G，Ubuntu 20.04）
- 已安装Docker和Docker Compose

### 一键部署

```bash
# 1. 克隆项目
git clone https://github.com/your-org/DeviceManagementPlatform.git
cd DeviceManagementPlatform

# 2. 创建conda环境
conda env create -f environment.yml
conda activate device-mgmt

# 3. 配置环境变量
cd deployment
cp .env.example .env

# 修改配置（必须修改！）
vim .env
# DB_PASSWORD=生成一个强密码
# SECRET_KEY=生成Django密钥
# ALLOWED_HOSTS=your-cloud-ip

# 4. 启动服务
docker-compose up -d

# 5. 初始化数据库
docker exec -it device-mgmt-web bash
python manage.py migrate
python manage.py createsuperuser
exit

# 6. 访问管理后台
# http://your-cloud-ip/admin/
```

**就这么简单！🎉**

---

## 📱 设备端部署（3种方式）

### 方式1：一键安装（最简单）

在新设备上执行一条命令：

```bash
export CLOUD_SERVER=http://your-cloud.com/api
curl -fsSL http://your-cloud.com/install.sh | bash
```

设备会：
1. 自动安装Docker
2. 注册到云端
3. 等待你在Web界面点击[部署]

---

### 方式2：Web界面部署（推荐）

**步骤**：
1. 打开管理后台: `http://your-cloud.com/admin/`
2. 看到新设备（状态：等待部署）
3. 点击设备 → 点击[部署] → 填写配置 → 确认
4. 等待3-5分钟，完成！

**配置示例**：
```
目标版本: v1.0.0
反向Socket主机: 192.168.31.29
反向Socket端口: 9088
```

---

### 方式3：预制系统镜像（最省心）

**准备黄金镜像**：
1. 在一台设备上完成方式1的安装
2. 制作系统镜像：
   ```bash
   dd if=/dev/mmcblk0 of=golden-system.img bs=4M status=progress
   ```

**批量部署**：
- 烧录镜像到新SD卡
- 插卡、通电
- 在Web界面点击[部署]
- 完成！

**适用场景**：批量部署10台以上设备

---

## 🔄 日常运维操作

### 查看所有设备状态

访问管理后台：
```
http://your-cloud.com/admin/management/device/
```

可以看到：
- 在线/离线状态
- CPU/内存/磁盘使用率
- 当前版本
- 最后心跳时间

### 推送更新到所有设备

1. 本地开发完成新功能
2. 构建并推送镜像：
   ```bash
   cd /path/to/MiddlewareServer
   docker build -t middleware:v1.0.4 .
   docker tag middleware:v1.0.4 your-cloud.com:5000/middleware:v1.0.4
   docker push your-cloud.com:5000/middleware:v1.0.4
   ```

3. 在Web界面批量更新：
   - 进入 **更新管理**
   - 选择设备（可全选）
   - 输入版本：`v1.0.4`
   - 点击 **批量更新**

4. 设备自动下载、安装、重启（全程无需人工干预）

### 查看设备日志

在设备详情页点击 **实时日志**，查看最新100条日志（自动刷新）。

---

## 🎨 典型使用场景

### 场景1：新项目现场安装

**传统方式**：
1. 带着笔记本到现场
2. SSH登录设备
3. 配置网络
4. 安装Docker
5. Clone代码
6. 修改配置文件
7. 启动服务
8. 调试问题...（半天过去了）

**使用本平台**：
1. 插电、联网（1分钟）
2. 在办公室Web界面点击[部署]（5分钟）
3. ☕喝杯咖啡，完成！

---

### 场景2：紧急Bug修复

**传统方式**：
1. 修复代码
2. 通知现场人员
3. 现场人员SSH登录设备
4. Git pull
5. 重启服务
6. 检查是否生效
7. 重复N台设备...（1-2小时）

**使用本平台**：
1. 修复代码并推送镜像（5分钟）
2. Web界面批量更新（1分钟）
3. 所有设备自动更新（5分钟）
4. 完成！（总耗时：11分钟）

---

### 场景3：监控设备健康

**传统方式**：
- 不知道设备是否在线
- 不知道磁盘快满了
- 不知道服务挂了
- 等客户打电话投诉...

**使用本平台**：
- 实时查看所有设备状态
- CPU/内存/磁盘告警
- 服务异常自动通知
- 提前发现问题，主动处理

---

## 📊 架构示意图

```
┌─────────────────────────────────────────┐
│      腾讯云服务器 (4C8G12M)              │
│  ┌────────────────────────────────────┐ │
│  │  Django管理后台                     │ │
│  │  - Web界面（设备列表、部署、更新）   │ │
│  │  - API接口（设备心跳、任务下发）     │ │
│  └────────────────────────────────────┘ │
│  ┌────────────────────────────────────┐ │
│  │  Docker Registry                   │ │
│  │  - 存储所有版本的镜像               │ │
│  └────────────────────────────────────┘ │
└─────────────────┬───────────────────────┘
                  │ 互联网
      ┌───────────┼───────────┐
      │           │           │
  ┌───▼──┐    ┌──▼───┐   ┌──▼───┐
  │设备A │    │设备B  │   │设备C  │
  │Agent │    │Agent │   │Agent │
  └──────┘    └──────┘   └──────┘
  北京工厂     上海工厂    深圳工厂
```

---

## 🔧 故障排查

### 问题1：设备注册失败

```bash
# 检查网络连通性
ping your-cloud.com

# 查看agent日志
journalctl -u bootstrap-agent -f

# 检查配置
cat /opt/bootstrap/.env
```

### 问题2：部署卡在"下载中"

**原因**：网速慢或Registry无法访问

**解决**：
```bash
# 在设备上手动测试
docker pull your-cloud.com:5000/middleware:v1.0.0

# 如果失败，检查Registry服务
docker ps | grep registry
```

### 问题3：更新后服务无法启动

**原因**：新版本配置不兼容

**解决**：
```bash
# 查看容器日志
docker logs middleware

# 回滚到旧版本（在Web界面创建更新任务，指定旧版本）
```

---

## 📚 更多文档

- [完整安装指南](docs/INSTALL.md)
- [详细使用手册](docs/USAGE.md)
- [API参考文档](docs/API.md)

---

## 💡 小贴士

### 安全建议
- 生产环境务必修改 `SECRET_KEY` 和 `DB_PASSWORD`
- 配置HTTPS（使用Let's Encrypt）
- 限制API访问（IP白名单或VPN）

### 性能优化
- 定期清理旧镜像（Registry会占用大量空间）
- 配置CDN加速镜像下载
- 多地部署可使用多个Registry节点

### 备份策略
- 每天自动备份PostgreSQL数据库
- 定期导出设备配置
- 保留至少3个历史版本的镜像

---

## 🆘 需要帮助？

- 📧 Email: tech@yms.com
- 💬 GitHub Issues: https://github.com/your-org/DeviceManagementPlatform/issues
- 📱 微信群：扫描README中的二维码

---

**祝你使用愉快！🎉**

