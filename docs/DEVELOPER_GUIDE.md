# 设备管理平台 - 开发者指南

> 本文档帮助开发者理解、维护、调试和扩展本项目

---

## 目录

1. [项目架构概览](#项目架构概览)
2. [技术栈](#技术栈)
3. [目录结构](#目录结构)
4. [本地开发环境](#本地开发环境)
5. [核心数据模型](#核心数据模型)
6. [API 接口说明](#api-接口说明)
7. [Agent 工作原理](#agent-工作原理)
8. [部署流程详解](#部署流程详解)
9. [常见问题排查](#常见问题排查)
10. [扩展开发指南](#扩展开发指南)

---

## 项目架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                         云服务器                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Nginx     │  │   Django    │  │       SQLite            │ │
│  │  (前端+代理) │──│  (REST API) │──│    (数据存储)            │ │
│  │  :8081      │  │  :8000      │  │  /app/data/db.sqlite3   │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│         │                │                                      │
│         │                │  /app/media/code_packages/           │
│         │                │  (代码包存储)                         │
└─────────┼────────────────┼──────────────────────────────────────┘
          │                │
          │   HTTP API     │
          ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       边缘设备 (开发板)                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Device Agent (/opt/device-agent/agent.py)                  ││
│  │  - 每30秒发送心跳                                            ││
│  │  - 每10秒轮询部署任务                                        ││
│  │  - 执行部署: 下载代码 → 启动容器                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Docker Container (newserver:latest)                        ││
│  │  - 预装环境镜像 (CUDA, 海康SDK, Conda等)                     ││
│  │  - 代码挂载: /opt/project-code → /work                      ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| **后端** | Django + Django REST Framework | 4.2 |
| **前端** | Vue 3 + Element Plus + TypeScript | 3.x |
| **数据库** | SQLite (生产可换 PostgreSQL) | 3.x |
| **Web服务器** | Nginx + Gunicorn | - |
| **容器化** | Docker + Docker Compose | 24.x |
| **设备端** | Python 3 + requests | 3.8+ |

---

## 目录结构

```
DeviceManagementPlatform/
├── server/                     # Django 后端
│   ├── core/                   # Django 项目配置
│   │   ├── settings.py         # ⭐ 主配置文件
│   │   ├── urls.py             # 根路由
│   │   └── wsgi.py             # WSGI 入口
│   ├── management/             # 核心业务 App
│   │   ├── models.py           # ⭐ 数据模型定义
│   │   ├── views.py            # ⭐ API 视图逻辑
│   │   ├── serializers.py      # DRF 序列化器
│   │   ├── urls.py             # API 路由
│   │   └── admin.py            # Django Admin 配置
│   ├── media/                  # 上传文件存储
│   │   └── code_packages/      # 代码包 ZIP 文件
│   └── manage.py               # Django 管理命令
│
├── frontend/                   # Vue 前端
│   ├── src/
│   │   ├── api/                # API 调用封装
│   │   │   ├── request.ts      # ⭐ Axios 实例配置
│   │   │   ├── device.ts       # 设备 API
│   │   │   ├── project.ts      # 项目 API
│   │   │   └── auth.ts         # 认证 API
│   │   ├── views/              # 页面组件
│   │   │   ├── Dashboard.vue   # 仪表盘
│   │   │   ├── DeviceList.vue  # 设备列表
│   │   │   ├── ProjectManage.vue # ⭐ 项目管理(含部署)
│   │   │   └── TaskManage.vue  # 任务管理
│   │   ├── layouts/            # 布局组件
│   │   │   └── MainLayout.vue  # ⭐ 侧边栏菜单
│   │   ├── router/index.ts     # 路由配置
│   │   └── stores/             # Pinia 状态管理
│   ├── vite.config.ts          # Vite 配置
│   └── package.json            # 依赖配置
│
├── device-agent/               # 设备端 Agent
│   ├── device-agent.py         # ⭐ Agent 主程序
│   └── install.sh              # Agent 安装脚本
│
├── deployment/                 # 部署配置
│   └── deploy-simple/          # 简化部署方案
│       ├── Dockerfile          # ⭐ Docker 镜像构建
│       ├── docker-compose.yml  # ⭐ 容器编排
│       ├── nginx.conf          # Nginx 配置
│       ├── entrypoint.sh       # 容器启动脚本
│       └── deploy.sh           # 一键部署脚本
│
└── docs/                       # 文档
```

---

## 本地开发环境

### 1. 后端开发

```bash
# 进入后端目录
cd server

# 创建虚拟环境 (推荐)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 .\venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 数据库迁移
python manage.py migrate

# 创建管理员
python manage.py createsuperuser

# 启动开发服务器
python manage.py runserver 0.0.0.0:8000
```

### 2. 前端开发

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器 (自动代理到后端)
npm run dev
```

### 3. 本地访问

- 前端: http://localhost:5173
- 后端 API: http://localhost:8000/api/
- Django Admin: http://localhost:8000/admin/

---

## 核心数据模型

### 模型关系图

```
Project (项目)
    │
    ├── local_image_name    # 设备预装镜像名 (如 newserver:latest)
    ├── code_package ──────→ CodePackage (代码包)
    ├── container_config    # 容器配置 (runtime, network, volumes)
    └── start_command       # 启动命令
    
Device (设备)
    │
    ├── device_id           # 唯一标识 (Agent 生成)
    ├── status              # online/offline/deploying
    ├── auto_deploy_project → Project (自动部署项目)
    └── last_heartbeat      # 最后心跳时间

ProjectDeployment (项目部署任务)  ← 核心业务表
    │
    ├── project ───────────→ Project
    ├── device ────────────→ Device
    ├── status              # pending → pulling_code → starting → completed
    └── progress            # 0-100%
```

### 关键字段说明

**Project.container_config** (JSON):
```json
{
  "runtime_nvidia": true,      // 使用 --runtime nvidia
  "network_mode": "host",      // 使用 --network host
  "privileged": true,          // 使用 --privileged
  "volumes": [                 // 额外挂载
    "/dev:/dev"
  ]
}
```

---

## API 接口说明

### 认证方式

使用 Token 认证:
```bash
# 登录获取 Token
curl -X POST http://server:8081/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "xxx"}'

# 返回: {"token": "abc123...", "user": {...}}

# 后续请求携带 Token
curl http://server:8081/api/projects/ \
  -H "Authorization: Token abc123..."
```

### 核心 API 端点

| 端点 | 方法 | 说明 | 权限 |
|------|------|------|------|
| `/api/devices/` | GET | 设备列表 | AllowAny |
| `/api/devices/register/` | POST | 设备注册 | AllowAny |
| `/api/devices/{id}/heartbeat/` | POST | 心跳上报 | AllowAny |
| `/api/projects/` | GET/POST | 项目管理 | IsAuthenticated |
| `/api/projects/{id}/deploy/` | POST | 部署到设备 | IsAuthenticated |
| `/api/project-deployments/` | GET | 部署任务列表 | AllowAny |
| `/api/code-packages/upload/` | POST | 上传代码包 | IsAuthenticated |
| `/api/install.sh` | GET | Agent 安装脚本 | AllowAny |
| `/api/agent-script/` | GET | Agent 脚本下载 | AllowAny |

### Agent 专用接口 (AllowAny)

这些接口无需认证，供 Agent 调用:

```python
# server/management/views.py

class DeviceViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        # Agent 调用的接口不需要认证
        if self.action in ['register', 'heartbeat', 'retrieve', 'list']:
            return [AllowAny()]
        return [IsAuthenticated()]
```

---

## Agent 工作原理

### Agent 生命周期

```
安装 Agent
    │
    ▼
启动 → 生成/读取 device_id
    │
    ▼
注册设备 POST /api/devices/register/
    │
    ▼
┌───────────────────────────────────┐
│         主循环 (无限)              │
│  ┌─────────────────────────────┐  │
│  │ 每30秒: 发送心跳             │  │
│  │ POST /devices/{id}/heartbeat│  │
│  └─────────────────────────────┘  │
│  ┌─────────────────────────────┐  │
│  │ 每10秒: 轮询部署任务         │  │
│  │ GET /project-deployments/   │  │
│  │   ?device_id=xxx&status=pending │
│  │                             │  │
│  │ 如果有任务 → 执行部署        │  │
│  └─────────────────────────────┘  │
└───────────────────────────────────┘
```

### Agent 部署流程

```python
def execute_project_deployment(deployment):
    # 1. 检查本地镜像
    if local_image_name:
        if not docker_image_exists(local_image_name):
            raise "本地镜像不存在"
    
    # 2. 下载代码包
    if code_package_info:
        download_file(code_url, '/tmp/code.zip')
        extract_to(code_mount_path)  # 如 /opt/project-code
    
    # 3. 停止旧容器
    docker_stop(container_name)
    docker_rm(container_name)
    
    # 4. 构建 docker run 命令
    cmd = ['docker', 'run', '-d', '--name', container_name]
    
    if container_config.get('runtime_nvidia'):
        cmd += ['--runtime', 'nvidia']
    if container_config.get('network_mode') == 'host':
        cmd += ['--network', 'host']
    if container_config.get('privileged'):
        cmd += ['--privileged']
    
    # 挂载代码目录
    cmd += ['-v', f'{code_mount_path}:{work_dir}']
    cmd += ['-w', work_dir]
    cmd += [image_name]
    cmd += start_command.split()
    
    # 5. 启动容器
    subprocess.run(cmd)
    
    # 6. 上报成功
    report_progress(status='completed', progress=100)
```

### Agent 文件位置

```
/opt/device-agent/
├── agent.py              # Agent 主程序
├── device_id             # 设备唯一ID (首次运行生成)
└── logs/                 # 日志目录

/etc/systemd/system/device-agent.service  # Systemd 服务配置
```

---

## 部署流程详解

### 云服务器部署

```bash
# 1. 克隆代码
git clone https://github.com/YanXiCodes/DeviceManagementPlatform.git
cd DeviceManagementPlatform

# 2. 一键部署 (端口 8081)
cd deployment/deploy-simple
chmod +x deploy.sh
./deploy.sh 8081

# 3. 访问
http://服务器IP:8081
默认账号: admin / admin123
```

### Docker 镜像构建过程

```dockerfile
# deployment/deploy-simple/Dockerfile

# 阶段1: 构建后端依赖
FROM python:3.10-slim AS backend-builder
RUN pip install -r requirements.txt

# 阶段2: 构建前端
FROM node:18-alpine AS frontend-builder
RUN npm ci && npm run build

# 阶段3: 最终镜像
FROM python:3.10-slim
# 复制后端 + 前端构建产物 + Nginx
COPY --from=backend-builder ...
COPY --from=frontend-builder /app/dist /usr/share/nginx/html
```

### 更新平台代码

```bash
cd /root/DeviceManagementPlatform

# 拉取最新代码
git pull

# 重新构建
cd deployment/deploy-simple
docker-compose up -d --build
```

---

## 常见问题排查

### 1. Agent 401 错误

**现象**: Agent 日志显示 `获取设备信息失败: 401`

**原因**: API 权限配置问题

**解决**:
```python
# server/management/views.py
class DeviceViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['register', 'heartbeat', 'retrieve', 'list']:
            return [AllowAny()]  # Agent 接口不需要认证
        return [IsAuthenticated()]
```

### 2. 本地镜像不存在

**现象**: `本地镜像不存在: newserver:latest`

**原因**: 设备上没有加载该镜像

**解决**:
```bash
# 在设备上加载镜像
docker load -i newserver.tar

# 确认
docker images | grep newserver
```

### 3. 大文件上传超时

**现象**: 上传代码包时 `Network Error` 或 `timeout`

**解决**: 检查以下配置
```nginx
# nginx.conf
client_max_body_size 5G;
proxy_read_timeout 600s;
```

```bash
# entrypoint.sh (Gunicorn)
--timeout 600
```

```typescript
// frontend/src/api/request.ts
timeout: 600000  // 10分钟
```

### 4. 容器无法访问 GPU

**现象**: 容器内 `nvidia-smi` 失败

**解决**: 确保项目配置启用了:
```json
{
  "runtime_nvidia": true,
  "privileged": true
}
```

### 5. 查看 Agent 日志

```bash
# 实时日志
sudo journalctl -u device-agent -f

# 最近100条
sudo journalctl -u device-agent --no-pager -n 100

# Agent 状态
sudo systemctl status device-agent
```

### 6. 查看平台容器日志

```bash
# 实时日志
docker logs -f device-platform

# 最近100条
docker logs device-platform --tail 100
```

---

## 扩展开发指南

### 添加新 API

1. **定义模型** (`server/management/models.py`):
```python
class NewModel(models.Model):
    name = models.CharField(max_length=200)
    # ...
```

2. **创建序列化器** (`server/management/serializers.py`):
```python
class NewModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewModel
        fields = '__all__'
```

3. **添加视图** (`server/management/views.py`):
```python
class NewModelViewSet(viewsets.ModelViewSet):
    queryset = NewModel.objects.all()
    serializer_class = NewModelSerializer
```

4. **注册路由** (`server/management/urls.py`):
```python
router.register(r'new-models', views.NewModelViewSet)
```

5. **数据库迁移**:
```bash
python manage.py makemigrations
python manage.py migrate
```

### 添加前端页面

1. **创建视图** (`frontend/src/views/NewPage.vue`)

2. **添加路由** (`frontend/src/router/index.ts`):
```typescript
{
  path: '/new-page',
  component: () => import('@/views/NewPage.vue')
}
```

3. **添加菜单** (`frontend/src/layouts/MainLayout.vue`):
```vue
<el-menu-item index="/new-page">
  <el-icon><Icon /></el-icon>
  <span>新页面</span>
</el-menu-item>
```

### 修改 Agent 逻辑

1. 修改 `device-agent/device-agent.py`
2. 提交代码到 Git
3. 服务器重新构建: `docker-compose up -d --build`
4. 设备重新安装 Agent:
   ```bash
   curl -fsSL http://server:8081/api/install.sh | sudo bash
   ```

---

## 环境变量

### 服务器端 (docker-compose.yml)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 8081 | 服务端口 |
| `DEBUG` | False | 调试模式 |
| `SECRET_KEY` | - | Django 密钥 |
| `ALLOWED_HOSTS` | * | 允许的主机 |
| `SERVER_URL` | - | 平台 URL (用于 Agent) |

### Agent 端 (/opt/device-agent/agent.py)

| 变量 | 说明 |
|------|------|
| `CLOUD_SERVER` | 平台地址 (安装时写入) |
| `HEARTBEAT_INTERVAL` | 心跳间隔 (默认30秒) |
| `TASK_POLL_INTERVAL` | 任务轮询间隔 (默认10秒) |

---

## 联系与支持

- GitHub: https://github.com/YanXiCodes/DeviceManagementPlatform
- Issues: 提交问题和建议

---

*文档最后更新: 2025-11-25*

