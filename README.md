# 设备管理平台 (Device Management Platform)

> 医疗自动化流水线视觉检测系统 - 远程设备管理与部署平台

## 🎯 项目简介

这是一个轻量级的IoT设备远程管理平台，专为边缘计算设备设计，实现：

- ✅ **零接触部署**：新设备通电即可自动注册，Web界面一键部署
- ✅ **OTA远程更新**：代码push自动构建，批量推送更新到所有设备
- ✅ **集中监控**：实时查看所有设备状态、日志、性能指标
- ✅ **配置管理**：远程修改配置，无需现场操作
- ✅ **故障诊断**：远程日志查看、SSH调试

## 📦 项目结构

```
DeviceManagementPlatform/
├── server/                 # 管理后台（Django）
│   ├── management/         # 设备管理核心应用
│   ├── config/             # 配置文件
│   └── requirements.txt    # Python依赖
│
├── device-agent/           # 设备端代理
│   ├── bootstrap-agent.py  # 开机自启动代理（等待部署）
│   ├── device-agent.py     # 监控和更新代理（运行态）
│   └── install.sh          # 一键安装脚本
│
├── deployment/             # 部署配置
│   ├── docker-compose.yml  # 服务器端Docker配置
│   ├── nginx.conf          # 反向代理配置
│   └── .github/            # CI/CD配置
│
└── docs/                   # 文档
    ├── INSTALL.md          # 安装指南
    ├── USAGE.md            # 使用手册
    └── API.md              # API文档
```

## 🚀 快速开始

### 1. 服务器端部署（腾讯云）

```bash
# 克隆项目
git clone https://github.com/your-org/DeviceManagementPlatform.git
cd DeviceManagementPlatform

# 创建conda环境
conda env create -f environment.yml
conda activate device-mgmt

# 部署服务
cd deployment
docker-compose up -d

# 访问管理后台
# http://your-server-ip
```

### 2. 设备端部署（边缘设备）

#### 方式A：使用预制镜像（推荐）
```bash
# 1. 烧录 golden-system.img 到SD卡
# 2. 插卡、接网线、通电
# 3. 在Web管理界面点击[一键部署]
```

#### 方式B：手动安装
```bash
# 在新设备上执行
curl -fsSL http://your-server/install.sh | bash
```

## 📖 详细文档

- [安装指南](docs/INSTALL.md) - 完整的安装步骤
- [使用手册](docs/USAGE.md) - 功能说明和操作指南
- [API文档](docs/API.md) - RESTful API参考
- [故障排查](docs/TROUBLESHOOTING.md) - 常见问题解决

## 🔧 技术栈

### 服务器端
- **Web框架**: Django 5.0+ / Django REST Framework
- **数据库**: PostgreSQL 14
- **消息队列**: Redis (可选)
- **容器化**: Docker + Docker Compose
- **反向代理**: Nginx

### 设备端
- **运行时**: Python 3.10+
- **容器**: Docker
- **通信**: HTTP/HTTPS + WebSocket

## 📊 系统架构

```
┌─────────────────────────────────────┐
│      腾讯云服务器 (4C8G12M)           │
│  ┌───────────────────────────────┐  │
│  │  管理后台 (Django)             │  │
│  │  - 设备列表                    │  │
│  │  - 部署向导                    │  │
│  │  - 更新管理                    │  │
│  │  - 日志查看                    │  │
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │  Docker Registry              │  │
│  │  - 镜像仓库                    │  │
│  └───────────────────────────────┘  │
└─────────────────┬───────────────────┘
                  │ 互联网
     ┌────────────┼────────────┐
     │            │            │
 ┌───▼───┐   ┌───▼───┐   ┌───▼───┐
 │设备A   │   │设备B   │   │设备C   │
 │Agent  │   │Agent  │   │Agent  │
 └───────┘   └───────┘   └───────┘
```

## 💡 核心功能

### 1. 零接触部署
- 新设备自动注册
- Web界面配置
- 自动下载镜像
- 一键启动服务

### 2. OTA远程更新
- Git push自动触发构建
- 批量更新设备
- 进度实时显示
- 失败自动回滚

### 3. 设备监控
- 在线状态
- CPU/内存/磁盘使用率
- 实时日志查看
- 告警通知

### 4. 配置管理
- Web界面修改配置
- 自动同步到设备
- 版本控制
- 一键回滚

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License

## 👥 作者

- 开发团队：YMS Tech
- 联系方式：tech@yms.com

## 🔗 相关项目

- [MiddlewareServer](https://github.com/your-org/MiddlewareServer) - 主项目
- [tubeOrientationAndLiquidDetection](https://github.com/your-org/tubeOrientationAndLiquidDetection) - 检测模块

