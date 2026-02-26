# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 重要提示

**在开始任何工作之前，必须先阅读 [WORKSPACE_GUIDE.md](WORKSPACE_GUIDE.md)**，该文档包含完整的项目架构、业务场景、实际交付流程和痛点分析。本文件是技术开发指南，WORKSPACE_GUIDE.md 是业务和架构全景。

## 项目概述

DeviceManagementPlatform 是一个远程设备管理与自动化部署平台，专为边缘计算设备（Jetson NX/Orin 开发板）设计。它解决了多台边缘设备分散部署、远程维护困难、代码更新繁琐等痛点。

**三大组件：**

1. **Django 后端** (`server/`) - REST API，负责设备管理、项目部署、任务编排
2. **Vue3 前端** (`frontend/`) - Web 管理界面，提供设备监控、项目管理、部署操作
3. **Device Agent** (`device-agent/`) - 设备端 Python 守护进程，负责心跳上报、任务轮询、部署执行

**生态系统：** 本平台是 YMS 工作区的一部分，与 MiddlewareServer（视觉检测服务）和 PerformanceTest（性能测试）协同工作。详见 [WORKSPACE_GUIDE.md](WORKSPACE_GUIDE.md)。

## 开发命令

### 后端 (Django)

```bash
cd server

# 开发服务器
python manage.py runserver

# 数据库迁移
python manage.py makemigrations
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser

# Django shell（调试用）
python manage.py shell

# 收集静态文件（生产环境）
python manage.py collectstatic --noinput
```

### 前端 (Vue3)

```bash
cd frontend

# 安装依赖
npm install

# 开发服务器（热重载）
npm run dev

# 生产构建
npm run build

# 预览生产构建
npm run preview

# 类型检查
npm run build  # 包含 tsc 类型检查
```

### 部署

```bash
# 一键 Docker 部署（推荐）
cd deployment/deploy-simple
chmod +x deploy.sh entrypoint.sh
./deploy.sh 8081  # 端口可配置

# 设备端安装（在边缘设备上执行）
curl -fsSL http://服务器IP:8081/api/install.sh | sudo bash

# 查看部署日志
docker logs -f device-platform

# 重启服务
docker compose restart

# 停止服务
docker compose down
```

## 核心架构

### 任务驱动的通信模式

平台采用 **"任务创建 → 轮询 → 执行 → 上报"** 的异步通信模式，适用于所有设备操作：

```
Web UI → 后端（创建任务）→ Device Agent（轮询任务）→ 执行 → 上报结果
```

**应用场景：**
- 项目部署（`ProjectDeployment` 模型）
- 配置更新（`pending_config` 机制）
- 日志收集（`DeviceLog` 模型）
- 系统任务（存储在 `device.config['system_tasks']`）

**为什么不用 WebSocket？** 因为设备在内网，无法主动连接。轮询模式简单可靠，适合边缘设备场景。

### 关键数据模型

位于 `server/management/models.py`：

- **Device** - 设备注册、状态、监控指标、FRP 隧道配置
  - `device_id`: 唯一标识（基于 MAC 地址生成）
  - `status`: waiting/deploying/online/offline/error
  - `config`: JSONField，存储灵活配置（system_tasks、pending_config_id 等）
  - `frp_ssh_port`/`frp_web_port`: FRP 隧道端口
  - `auto_deploy_project`: 自动部署的项目（设备上线后自动部署）

- **Project** - 部署定义（Docker 镜像 + 代码包 + 容器配置）
  - 支持两种镜像来源：平台托管镜像（`docker_image`）或设备预装镜像（`local_image_name`）
  - `code_package`: 代码包，用于热更新（无需重新构建镜像）
  - `container_config`: JSONField，存储 Docker 运行参数（端口、卷、环境变量、runtime 等）

- **ProjectDeployment** - 部署任务，带状态跟踪
  - `status`: pending/pulling_image/deploying/completed/failed
  - `progress`: 0-100 进度百分比

- **DockerImage** - 平台托管的 Docker 镜像（.tar 文件）

- **CodePackage** - 代码包（.zip/.tar.gz），用于快速更新代码

- **DeviceLog** - 日志收集任务和存储

### Agent 架构

Device Agent (`device-agent/device-agent.py`) 作为 systemd 服务运行，包含多个轮询循环：

- **心跳上报** (5秒间隔) - 上报 CPU/内存/磁盘使用率、容器状态、服务健康状态
- **任务轮询** (5秒间隔) - 检查待执行的 `ProjectDeployment` 任务
- **配置同步** (3秒间隔) - 拉取并应用配置更新
- **日志任务** (5秒间隔) - 执行日志收集请求
- **FRP 状态** (周期性) - 上报隧道连接状态
- **自动更新** (1小时间隔) - 检查 Agent 版本并自动升级

**Agent 版本管理：** Agent 版本号在 `device-agent.py` 和 `server/management/views.py` 中都有定义（`AGENT_VERSION`）。发布新 Agent 功能时，必须同时更新两处。

### API 结构

所有 API 都在 `/api/` 前缀下：

```
/api/devices/                    # 设备管理
  POST register/                 # 设备自注册（无需认证）
  POST {device_id}/heartbeat/    # 心跳上报（无需认证）
  POST {device_id}/restart/      # 重启容器
  GET {device_id}/container_logs/ # 获取容器日志
  POST {device_id}/apply_config/ # 推送配置到设备
  GET {device_id}/pending_config/ # Agent 轮询配置（无需认证）
  POST {device_id}/config_result/ # Agent 上报结果（无需认证）
  GET {device_id}/pending_system_tasks/ # Agent 轮询系统任务（无需认证）
  POST {device_id}/report_system_task/ # Agent 上报系统任务结果（无需认证）

/api/projects/                   # 项目 CRUD
  POST {id}/deploy/              # 部署到设备

/api/images/                     # Docker 镜像管理
  POST /                         # 上传镜像（.tar）
  GET {id}/download/             # Agent 下载镜像

/api/code-packages/              # 代码包管理
  POST /                         # 上传代码包（.zip/.tar.gz）
  GET {id}/download/             # Agent 下载代码包

/api/project-deployments/        # 部署任务
  GET /                          # Agent 轮询待执行任务（无需认证）
  POST {id}/update_progress/     # Agent 上报进度（无需认证）

/api/agent/
  GET version/                   # 最新 Agent 版本
  GET download/                  # 下载 Agent 脚本

/api/install.sh                  # 设备安装脚本
```

**认证说明：** Agent 端点（register、heartbeat、轮询端点）使用 `permission_classes=[AllowAny]`，Web UI 端点需要 `IsAuthenticated` 权限。

### 前端结构

- **Views** (`frontend/src/views/`) - 页面组件（Dashboard、DeviceList、DeviceDetail、ProjectManage 等）
- **API Layer** (`frontend/src/api/`) - 基于 Axios 的 API 封装，带 TypeScript 类型
- **Router** (`frontend/src/router/`) - Vue Router 配置
- **Request Interceptor** (`frontend/src/api/request.ts`) - Token 认证、401 处理

## 添加新的设备功能

遵循 WORKSPACE_GUIDE.md 第 5 章记录的 **三阶段模式**：

**1. 后端** - 在 `server/management/views.py` 的 `DeviceViewSet` 中添加 `@action` 方法

- 创建任务存储（通常在 `device.config` JSON 字段中）
- 添加 Agent 轮询端点（使用 `permission_classes=[AllowAny]`）
- 添加结果上报端点

**2. Agent** - 在 `device-agent/device-agent.py` 中添加函数

- `poll_xxx()` - 从后端获取待执行任务
- `execute_xxx()` - 在设备上执行任务
- `report_xxx()` - 上报结果到后端
- 在 `main()` 循环中添加轮询调用

**3. 前端** - 在 `frontend/src/views/` 中添加 UI

- 在 `frontend/src/api/device.ts` 中添加 API 函数
- 添加按钮/表单触发操作
- 显示任务状态/结果

**完整示例：** 参见 WORKSPACE_GUIDE.md 第 5.2 节的"开机自启动浏览器"功能完整实现。

## FRP 隧道配置

平台支持自动配置 FRP（Fast Reverse Proxy）隧道，用于 SSH 访问 NAT 后的设备：

- **端口分配** - 后端在设备注册时自动从端口池（39983-39993）分配 SSH 端口
- **配置生成** - `views.py` 中的 `build_frp_config_for_device()` 生成 frpc.ini 内容
- **Agent 应用** - Agent 下载 frpc 二进制文件，写入配置，启动 systemd 服务
- **状态跟踪** - `device.frp_status` 字段跟踪隧道连接状态

FRP 配置存储在 Django settings（`FRP_CONFIG` 字典）中，包括服务器地址、端口、token 和端口池。

**实际使用场景：** 设备部署在客户现场内网，通过 FRP 隧道可以从任意地方 SSH 连接设备，无需 VPN。详见 WORKSPACE_GUIDE.md 第 9 章。

## 重要文件位置

| 用途 | 路径 |
| --- | --- |
| 数据模型 | `server/management/models.py` |
| API 视图 | `server/management/views.py` |
| API 序列化器 | `server/management/serializers.py` |
| URL 路由 | `server/management/urls.py` |
| Django 设置 | `server/core/settings.py` |
| Agent 主脚本 | `device-agent/device-agent.py` |
| 设备安装脚本 | `device-agent/install.sh` |
| 前端 API 层 | `frontend/src/api/*.ts` |
| 前端类型定义 | `frontend/src/types/index.ts` |
| 部署配置 | `deployment/deploy-simple/` |

## 环境变量

### 后端 (Django)

- `SECRET_KEY` - Django 密钥
- `DEBUG` - 调试模式（默认：True）
- `ALLOWED_HOSTS` - 允许的主机列表，逗号分隔（默认：*）
- `DATABASE_URL` - 数据库连接字符串（默认：SQLite）

### Agent (设备端)

- `CLOUD_SERVER` - 后端 API URL（例如：`http://server-ip:8081/api`）
- `HEARTBEAT_INTERVAL` - 心跳间隔（秒，默认：5）
- `TASK_POLL_INTERVAL` - 任务轮询间隔（默认：5）
- `CONFIG_CHECK_INTERVAL` - 配置同步间隔（默认：3）
- `DEVICE_ID_FILE` - 设备 ID 存储路径（默认：/etc/device-id）
- `LOG_UPLOAD_INTERVAL` - 日志上传间隔（默认：30）
- `UPDATE_CHECK_INTERVAL` - 更新检查间隔（默认：3600）

## 数据库架构说明

- **Device.config** - JSONField，用于灵活配置存储：
  - `system_tasks` - 待执行的系统配置任务
  - `pending_config_id` - 等待应用的配置 ID
  - 自定义设备特定设置

- **Project.container_config** - JSONField，存储 Docker 运行参数：
  - `ports` - 端口映射（例如：`{"8000/tcp": 8000}`）
  - `volumes` - 卷挂载
  - `environment` - 环境变量
  - `runtime` - Docker runtime（例如："nvidia"）
  - `network_mode` - 网络模式（例如："host"）
  - `privileged` - 特权模式标志

## 测试注意事项

- Agent 端点（`register`、`heartbeat`、轮询端点）使用 `permission_classes=[AllowAny]` 以便设备访问
- Web UI 端点需要 `IsAuthenticated` 权限
- 默认管理员凭据：`admin` / `admin123`（生产环境请修改）
- 测试设备注册：

```bash
curl -X POST http://localhost:8081/api/devices/register/ \
  -H "Content-Type: application/json" \
  -d '{"device_id":"test-001","mac_address":"00:11:22:33:44:55","ip_address":"192.168.1.100"}'
```

## 相关文档

- [WORKSPACE_GUIDE.md](WORKSPACE_GUIDE.md) - YMS 所有项目的完整架构文档（必读）
- [README.md](README.md) - 快速入门指南和项目概述
- [docs/CLOUD_DEPLOY_GUIDE.md](docs/CLOUD_DEPLOY_GUIDE.md) - 服务器部署说明

## 版本跟踪

更新 Agent 时的步骤：

1. 在 `device-agent/device-agent.py` 中递增 `AGENT_VERSION`
2. 在 `server/management/views.py` 中更新 `AGENT_VERSION`
3. Agent 通过比较版本号自动从 `/api/agent/download/` 下载新脚本并更新

## 业务场景理解

**核心问题：** 多台边缘设备分散在客户现场，传统 SSH 逐台维护效率低下。

**解决方案：** 统一 Web 管理平台 + 设备端 Agent，实现：

- 一键安装：设备执行一条命令即可自动注册
- 批量部署：Web 界面选择设备，一键推送代码更新
- 远程配置：修改配置后自动同步到设备
- 状态监控：实时查看设备在线状态、资源使用、服务健康
- 远程访问：通过 FRP 隧道 SSH 连接内网设备

**典型工作流：** 详见 WORKSPACE_GUIDE.md 第 8 章"实际交付流程 SOP"。

## 开发注意事项

- **不要破坏向后兼容性**：Agent 可能运行旧版本，API 变更需考虑兼容性
- **任务幂等性**：部署任务可能重试，确保操作幂等
- **错误处理**：Agent 在无网络环境下应优雅降级，不应崩溃
- **日志记录**：关键操作必须记录日志，便于远程排查问题
- **安全性**：上传的镜像和代码包应验证完整性（checksum）
