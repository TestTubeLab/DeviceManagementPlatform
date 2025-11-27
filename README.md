# 设备管理平台 (Device Management Platform)

> 远程设备管理与自动化部署平台 - 专为边缘计算/IoT设备设计

## 🎯 项目简介

轻量级的远程设备管理平台，实现开发板/边缘设备的集中管理与自动化部署：

- ✅ **一键安装**：设备执行一条命令即可自动注册到平台
- ✅ **项目管理**：管理Docker镜像、代码包、配置，一键部署到设备
- ✅ **远程部署**：Web界面选择设备，批量推送项目
- ✅ **实时监控**：设备在线状态、心跳监测
- ✅ **配置管理**：远程修改项目配置，自动同步到设备

## 📦 项目结构

```
DeviceManagementPlatform/
├── frontend/               # Vue3 前端
│   └── src/
│       ├── views/          # 页面（设备管理、项目管理、部署中心等）
│       ├── api/            # API接口
│       └── components/     # 组件
│
├── server/                 # Django 后端
│   ├── management/         # 核心应用（models, views, serializers）
│   ├── core/               # Django配置
│   └── media/              # 上传文件存储
│
├── device-agent/           # 设备端Agent
│   ├── device-agent.py     # 主Agent（心跳、任务轮询、部署执行）
│   ├── bootstrap-agent.py  # 引导脚本
│   └── install.sh          # 本地安装脚本
│
├── deployment/             # 部署配置
│   ├── deploy-simple/      # 简化Docker部署（推荐）
│   ├── docker-compose.yml  # 完整部署配置
│   └── nginx.conf          # Nginx配置
│
└── docs/                   # 文档
```

## 🚀 快速开始

### 1. 服务器部署（云服务器/本地服务器）

```bash
# 克隆项目
git clone https://github.com/your-org/DeviceManagementPlatform.git
cd DeviceManagementPlatform

# 一键Docker部署
cd deployment/deploy-simple
chmod +x deploy.sh entrypoint.sh
./deploy.sh 8081    # 端口可自定义

# 访问管理界面
# http://服务器IP:8081
# 默认账号: admin / admin123
```

### 2. 设备端安装（开发板/边缘设备）

在设备上执行一条命令：
```bash
curl -fsSL http://服务器IP:8081/api/install.sh | sudo bash
```

设备会自动：
1. 安装依赖（Python3、Docker）
2. 下载Agent脚本
3. 配置开机自启
4. 注册到管理平台

### 3. 开始使用

1. 打开Web管理界面，在「设备管理」查看已注册的设备
2. 在「镜像仓库」上传Docker镜像
3. 在「项目管理」创建项目，关联镜像和配置
4. 选择设备，一键部署项目

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Element Plus + Vite |
| 后端 | Django 5 + Django REST Framework |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 部署 | Docker + Nginx |
| 设备端 | Python 3 + Docker |

## 📊 系统架构

```
┌─────────────────────────────────────────┐
│         云服务器 / 管理中心               │
│  ┌─────────────┐  ┌─────────────────┐   │
│  │  Vue前端    │  │  Django后端      │   │
│  │  - 设备管理  │  │  - REST API     │   │
│  │  - 项目管理  │  │  - 任务调度      │   │
│  │  - 部署中心  │  │  - 文件存储      │   │
│  └─────────────┘  └─────────────────┘   │
└────────────────────┬────────────────────┘
                     │ HTTP (心跳/任务轮询)
        ┌────────────┼────────────┐
        │            │            │
   ┌────▼────┐  ┌────▼────┐  ┌────▼────┐
   │ 设备A    │  │ 设备B    │  │ 设备C    │
   │ Agent   │  │ Agent   │  │ Agent   │
   │ Docker  │  │ Docker  │  │ Docker  │
   └─────────┘  └─────────┘  └─────────┘
```

## 💡 核心功能

### 设备管理
- 设备自动注册与发现
- 实时在线状态监控
- 设备分组与标签
- 自动部署项目配置

### 项目管理
- Docker镜像上传与管理
- 代码包上传（环境镜像+代码分离）
- 项目配置管理（环境变量、端口映射等）
- 容器高级配置（runtime、network、privileged等）

### 部署中心
- 选择设备批量部署
- 部署进度实时显示
- 部署历史记录

## 📖 文档

- [云部署指南](CLOUD_DEPLOY_GUIDE.md) - 服务器部署步骤
- [API文档](docs/API.md) - RESTful API参考
- [安装指南](docs/INSTALL.md) - 详细安装说明
- [使用手册](docs/USAGE.md) - 功能操作指南

## 📄 许可证

MIT License

## 👥 作者

- Yanxicodes

