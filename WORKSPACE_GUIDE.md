# YMS 工作区架构文档

> 本文档旨在帮助 AI 助手快速理解工作区中各项目的架构、技术栈、核心模块及其相互关系。
> 相关项目路径：D:\yms\MiddlewareServer、D:\yms\DeviceManagementPlatform、D:\yms\PerformanceTest

## 项目概览

```
D:\yms\
├── MiddlewareServer/      # 医疗自动化流水线视觉检测服务 (部署在 Jetson NX)
├── DeviceManagementPlatform/  # 设备管理与远程部署平台 (部署在云服务器)
└── PerformanceTest/       # 性能测试脚本集合 (开发辅助)
```

### 项目关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                       云服务器                                    │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │        DeviceManagementPlatform (8081端口)              │   │
│   │  ┌────────────┐    ┌─────────────────────────────┐      │   │
│   │  │  Vue3 前端  │◄──►│    Django REST 后端         │      │   │
│   │  │ (设备管理)  │    │ (API/任务调度/文件存储)      │      │   │
│   │  └────────────┘    └─────────────────────────────┘      │   │
│   └──────────────────────────┬──────────────────────────────┘   │
│                              │ HTTP (心跳/任务轮询/部署指令)       │
└──────────────────────────────┼──────────────────────────────────┘
                               │
           ┌───────────────────┼───────────────────┐
           ▼                   ▼                   ▼
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │  Jetson NX A │    │  Jetson NX B │    │  Jetson NX C │
    │ ┌─────────┐  │    │ ┌─────────┐  │    │ ┌─────────┐  │
    │ │  Agent  │  │    │ │  Agent  │  │    │ │  Agent  │  │
    │ └────┬────┘  │    │ └────┬────┘  │    │ └────┬────┘  │
    │      ▼       │    │      ▼       │    │      ▼       │
    │ ┌─────────┐  │    │ ┌─────────┐  │    │ ┌─────────┐  │
    │ │Middleware│ │    │ │Middleware│ │    │ │Middleware│ │
    │ │ Server  │  │    │ │ Server  │  │    │ │ Server  │  │
    │ └────┬────┘  │    │ └────┬────┘  │    │ └────┬────┘  │
    │      ▼       │    │      ▼       │    │      ▼       │
    │  [相机群组]  │    │  [相机群组]  │    │  [相机群组]  │
    └─────────────┘    └─────────────┘    └─────────────┘
           │
           ▼
    PerformanceTest (开发机压测)
```

---

## 一、MiddlewareServer (视觉检测服务)

### 1.1 项目定位
医疗自动化流水线视觉检测后端服务，运行在 **Jetson NX/Orin** 边缘开发板上，连接工业相机对样本进行实时检测。

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Django 5 + Channels (WebSocket) |
| 前端 | Vue 3 + TypeScript + Vite |
| 深度学习 | Ultralytics (YOLO), MMDetection, MMYolo, ONNXRuntime |
| 图像处理 | OpenCV, NumPy |
| 相机驱动 | 海康威视 SDK (MvCameraControl) |
| 条码识别 | pyzbar, zxingcpp (可选) |
| 包管理 | Poetry |
| 生产部署 | Docker + NVIDIA Runtime |

### 1.3 目录结构

```
MiddlewareServer/
├── server/                    # Django 后端主目录
│   ├── server/                # Django 项目配置
│   │   ├── settings.py        # 项目设置
│   │   ├── urls.py            # 根路由配置
│   │   └── asgi.py            # ASGI 入口 (支持 WebSocket)
│   ├── core/                  # 核心功能模块
│   │   ├── plugin/            # 插件系统基类
│   │   │   ├── base.py        # BasePlugin 抽象基类
│   │   │   ├── models.py      # 插件结果数据模型
│   │   │   └── urls.py        # 插件动态路由注册
│   │   ├── auth/              # 认证模块 (登录/权限)
│   │   └── socketIO/          # WebSocket/TCP 处理器
│   ├── plugins/               # 检测插件目录 ⭐核心业务
│   │   ├── tubeOrientationAndLiquidDetection/  # 试管方向和液位检测
│   │   ├── tubeCapDetection/  # 试管盖检测
│   │   ├── TubeCapInspection/ # 试管盖品质检测
│   │   ├── cleanTubeCheck/    # 空管/洁净度检测
│   │   ├── attitudeDetection/ # 姿态检测
│   │   ├── barcode.py         # 条码/二维码识别
│   │   └── README.md          # 插件开发指南
│   ├── devices/               # 设备驱动模块
│   │   ├── MvImport/          # 海康相机 SDK 封装
│   │   ├── base.py            # BaseDevice 抽象基类
│   │   └── streams.py         # 视频流管理
│   ├── apis/                  # REST API 视图
│   │   ├── urls.py            # API 路由
│   │   ├── views.py           # 通用视图
│   │   ├── simulate_urls.py   # 模拟推理接口 (测试用)
│   │   ├── roi_views.py       # ROI 配置接口
│   │   └── metrics.py         # 性能指标接口
│   ├── models/                # Django ORM 模型
│   ├── scheduler/             # APScheduler 定时任务
│   ├── utils/                 # 工具模块
│   │   ├── schema/            # Pydantic 数据模型
│   │   ├── config.py          # 配置加载器
│   │   ├── log.py             # Loguru 日志配置
│   │   └── exception.py       # 自定义异常
│   └── wss/                   # WebSocket 日志推送
├── frontend/                  # Vue3 前端
│   └── src/
│       ├── views/             # 页面组件
│       ├── components/        # 通用组件
│       ├── store/             # Pinia 状态管理
│       └── apis/              # API 请求封装
├── config/                    # 运行时配置
│   ├── devices.yml            # 相机配置 (IP/参数)
│   └── reserved.yml           # 其他保留配置
├── tests/                     # 测试数据目录
│   ├── image/                 # 测试图片
│   ├── tubeOrientationAndLiquidDetection/  # 各插件测试数据
│   └── ...
├── localstore/                # 本地存储 (日志/结果图片)
│   ├── logs/                  # 按日期分割的日志文件
│   └── images/                # 检测结果图片
├── pyproject.toml             # Poetry 依赖配置
└── start.sh                   # Docker 容器启动脚本
```

### 1.4 核心架构：插件系统

所有检测功能通过**插件**实现，继承自 `BasePlugin` 抽象基类：

```python
# server/core/plugin/base.py 核心抽象

class BasePlugin(ABC, LoginRequiredMixin, View):
    """插件基类 - 所有检测插件必须继承此类"""
    
    params: PluginParams           # 请求参数
    work_data: PluginResultFile    # 工作时产生的数据
    
    @property
    def video_device(self) -> BaseDevice:
        """获取对应的相机设备对象"""
        return device_manager.get_device(self.params.device_id)
    
    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """插件名称，用于 URL 路由注册"""
        raise NotImplementedError
    
    def read(self) -> tuple[bool, MatLike]:
        """读取图像（带自动重连机制，失败重试3次）"""
        ...
    
    def video_read(self, duration: int) -> Generator:
        """捕获指定时长视频流"""
        ...
    
    @abstractmethod
    def work(self, **kwargs) -> WorkResultData:
        """核心工作方法 - 处理单帧图像"""
        raise NotImplementedError
    
    def work_video(self, **kwargs) -> WorkResultData:
        """可选：处理视频流"""
        ...
```

**插件开发示例** (条码识别):

```python
# server/plugins/barcode.py

@load_plugin  # 装饰器自动注册到路由系统
class BarcodePlugin(BasePlugin):
    @classmethod
    def name(cls) -> str:
        return "barcode"  # 对应 URL: /api/plugin/barcode
    
    def work(self) -> WorkResultData:
        _, frame = self.read()         # 从相机读取图像
        codes = self.three_code(frame)  # 三槽位条码识别
        return {"codes": codes, "pos": [c is not None for c in codes]}
```

### 1.5 相机管理

通过 `config/devices.yml` 配置：

```yaml
# 示例配置
- name: 样品盘               # 相机别名
  device: "devices.HiKDevice"  # 驱动类
  params: 192.168.31.201      # 相机 IP
  config:
    ExposureTime: 11000       # 曝光时间 (μs)
    AcquisitionFrameRate: 3   # 帧率

- name: 前处理
  device: "devices.HiKDevice"
  params: 192.168.31.202
  config:
    ExposureTime: 5600
    ReverseY: true
```

相机由 `DeviceManager` 单例管理，支持：
- 自动发现与连接
- 断连自动重连 (连续失败10次触发)
- 参数动态配置

### 1.6 API 路由结构

```
/api/
├── plugin/                    # 插件调用入口
│   ├── barcode               POST  # 条码识别
│   ├── tubeOrientationAndLiquidDetection  POST  # 试管方向+液位
│   ├── tubeCapDetection      POST  # 试管盖检测
│   ├── cleanTubeCheck        POST  # 空管检测
│   └── attitudeDetection     POST  # 姿态检测
│   └── {plugin}/roi          GET/POST  # ROI 配置
├── simulate/                  # 模拟推理 (用测试图片)
│   └── run                   POST
├── device/                    # 相机管理
│   ├── list                  GET   # 相机列表
│   └── {id}/preview          GET   # 预览流
├── auth/
│   ├── login                 POST
│   └── logout                POST
├── metrics                   GET   # 性能指标
└── health                    GET   # 健康检查
```

### 1.7 现有检测插件

| 插件名称 | 功能描述 | 权重(压测) |
|---------|---------|-----------|
| `tubeOrientationAndLiquidDetection` | 试管方向识别 + 液位检测 | 5 |
| `tubeCapDetection` | 试管盖存在性检测 | 3 |
| `TubeCapInspection` | 试管盖质量/颜色检测 | - |
| `cleanTubeCheck` | 空管洁净度检测 | 2 |
| `attitudeDetection` | 样本姿态检测 | 2 |
| `barcode` | 条码/二维码识别 (三槽位) | 1 |
| `liquidLevelDetection` | 液位检测 | 1 |

### 1.8 部署方式

```bash
# 开发环境
cd frontend && npm run dev    # 前端开发服务器
cd server && python manage.py runserver  # Django 开发服务器

# 生产环境 (Docker)
docker run --restart unless-stopped -it \
  --runtime nvidia \           # 使用 GPU
  --network host \             # 主机网络
  -v /home/z/work/:/work \     # 挂载代码
  --name middleware <镜像ID> \
  /bin/bash -c "cp /work/MiddlewareServer/start.sh /start.sh && /start.sh"
```

---

## 二、DeviceManagementPlatform (设备管理平台)

### 2.1 项目定位
轻量级远程设备管理平台，实现多台 Jetson 开发板的集中管理与自动化部署。

### 2.2 业务场景与解决的问题

#### 场景背景
医疗自动化流水线需要在**多个工位**部署视觉检测设备，每个工位配置一台 Jetson NX 开发板。随着设备数量增加（5台、10台甚至更多），传统的逐台 SSH 登录维护方式面临严重的运维瓶颈。

#### 核心痛点

| 痛点 | 传统方式 | 本平台解决方案 |
|------|---------|---------------|
| **设备分散** | 需要记忆每台设备IP，逐个SSH登录 | 统一Web界面，一览所有设备状态 |
| **部署繁琐** | 手动拷贝代码、配置环境、启动服务 | 一键部署：选设备→点部署→自动完成 |
| **版本不一致** | 各设备代码版本混乱难追踪 | 代码包集中管理，版本清晰可追溯 |
| **配置同步难** | 修改相机IP需逐台登录修改yml文件 | Web界面修改配置，自动推送到设备 |
| **状态不可见** | 不知道设备是否在线、服务是否正常 | 实时心跳监控 + 容器/服务健康状态 |
| **故障排查难** | 需登录设备查看日志 | 远程日志查看、搜索、下载 |
| **扩容困难** | 新设备需要大量手动配置 | 一条命令自动注册 + 自动部署 |

#### 典型使用场景

**场景1：新工位上线**
```
运维人员拿到新的 Jetson NX 开发板
↓ 执行: curl -fsSL http://平台IP:8081/api/install.sh | sudo bash
↓ 设备自动出现在管理平台的设备列表中
↓ 设置「自动部署项目」
↓ 设备自动拉取代码、启动服务
↓ 完成！整个过程 < 5分钟
```

**场景2：批量代码更新**
```
开发人员修复了一个检测算法Bug
↓ 打包代码上传到平台
↓ 勾选需要更新的10台设备
↓ 点击「批量部署」
↓ 10台设备并行更新，进度实时显示
↓ 全部更新完成，无需任何SSH操作
```

**场景3：远程配置调整**
```
现场更换了某工位的相机，IP变了
↓ Web界面修改该设备的相机配置
↓ 点击「应用配置」
↓ Agent自动更新 devices.yml 并重启服务
↓ 新相机开始工作
```

**场景4：故障快速定位**
```
某工位检测异常
↓ 管理平台查看：设备在线、容器运行中、但服务不健康
↓ 点击「查看日志」→ 搜索「ERROR」
↓ 发现：相机连接超时
↓ 远程重启服务 或 调整配置
```

### 2.3 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Element Plus + Vite |
| 后端 | Django 5 + Django REST Framework |
| 数据库 | SQLite (开发) / PostgreSQL (生产) |
| 认证 | Token 认证 (rest_framework.authtoken) |
| 部署 | Docker + Nginx |
| 设备端 | Python Agent (systemd 服务) |

### 2.4 目录结构

```
DeviceManagementPlatform/
├── frontend/                  # Vue3 前端
│   └── src/
│       ├── views/             # 页面组件
│       │   ├── Dashboard.vue      # 仪表盘
│       │   ├── DeviceList.vue     # 设备列表
│       │   ├── DeviceDetail.vue   # 设备详情
│       │   ├── ProjectManage.vue  # 项目管理
│       │   ├── TaskManage.vue     # 任务管理
│       │   └── Login.vue          # 登录页
│       ├── api/               # API 请求封装
│       │   ├── device.ts          # 设备 API
│       │   ├── project.ts         # 项目 API
│       │   ├── codePackage.ts     # 代码包 API
│       │   └── request.ts         # Axios 封装
│       ├── components/        # 组件
│       │   ├── DeviceCard.vue     # 设备卡片
│       │   └── StatusBadge.vue    # 状态徽章
│       ├── types/             # TypeScript 类型定义
│       │   └── index.ts
│       ├── stores/            # Pinia 状态管理
│       └── router/            # Vue Router
├── server/                    # Django 后端
│   ├── core/                  # Django 项目配置
│   │   └── settings.py
│   └── management/            # 核心应用
│       ├── models.py          # 数据模型 ⭐
│       ├── views.py           # API 视图 ⭐
│       ├── serializers.py     # DRF 序列化器
│       ├── urls.py            # 路由配置
│       └── admin.py           # Django Admin
├── device-agent/              # 设备端 Agent ⭐
│   ├── device-agent.py        # 主 Agent 脚本 (1972行)
│   ├── bootstrap-agent.py     # 引导脚本
│   └── install.sh             # 安装脚本
├── deployment/                # 部署配置
│   ├── deploy-simple/         # 简化部署方案
│   │   ├── Dockerfile
│   │   ├── deploy.sh
│   │   └── docker-compose.yml
│   └── nginx.conf
└── docs/                      # 文档
```

### 2.5 数据模型

```python
# server/management/models.py

class Device(models.Model):
    """设备信息"""
    device_id = models.CharField(unique=True)  # 设备唯一标识
    name = models.CharField()                   # 设备名称
    ip_address = models.CharField()             # IP 地址
    mac_address = models.CharField()            # MAC 地址
    status = models.CharField()                 # waiting/deploying/online/offline/error
    
    # 硬件监控
    cpu_usage = models.FloatField()
    memory_usage = models.FloatField()
    disk_usage = models.FloatField()
    
    # 服务监控
    container_status = models.CharField()       # running/stopped/not_found
    service_status = models.CharField()         # healthy/unhealthy/unknown
    last_heartbeat = models.DateTimeField()
    
    # 配置
    auto_deploy_project = models.ForeignKey('Project')  # 自动部署项目
    config = models.JSONField()                 # 扩展配置

class Project(models.Model):
    """项目定义"""
    name = models.CharField()
    version = models.CharField()
    
    # 镜像配置 (二选一)
    docker_image = models.ForeignKey('DockerImage')      # 平台托管镜像
    local_image_name = models.CharField()                 # 本地预装镜像
    
    # 代码配置
    code_package = models.ForeignKey('CodePackage')      # 代码包
    code_mount_path = models.CharField()                  # 挂载路径
    
    # 容器配置
    container_name = models.CharField()
    container_config = models.JSONField()                 # 端口/卷/环境变量
    start_command = models.TextField()

class ProjectDeployment(models.Model):
    """部署任务"""
    project = models.ForeignKey(Project)
    device = models.ForeignKey(Device)
    task_type = models.CharField()   # deploy/restart
    status = models.CharField()       # pending/pulling_image/completed/failed
    progress = models.IntegerField()

class DockerImage(models.Model):
    """Docker 镜像"""
    name = models.CharField()
    tag = models.CharField()
    file_path = models.CharField()   # .tar 文件路径
    size = models.BigIntegerField()

class CodePackage(models.Model):
    """代码包"""
    name = models.CharField()
    version = models.CharField()
    file_path = models.CharField()   # .zip/.tar.gz 文件路径
```

### 2.6 API 路由结构

```
/api/
├── devices/                   # 设备管理
│   ├── GET                    # 设备列表
│   ├── POST register/         # 设备注册 (Agent 调用)
│   ├── POST {device_id}/heartbeat/  # 心跳上报 (Agent)
│   ├── POST {device_id}/restart/    # 重启服务
│   ├── GET {device_id}/container_logs/  # 获取容器日志
│   ├── POST {device_id}/apply_config/   # 应用配置
│   ├── GET {device_id}/pending_config/  # 获取待应用配置 (Agent)
│   └── POST {device_id}/config_result/  # 配置应用结果 (Agent)
├── projects/                  # 项目管理
│   ├── GET/POST               # CRUD
│   └── {id}/deploy/          POST  # 部署到设备
├── images/                    # Docker 镜像管理
│   ├── GET/POST               # 上传/列表
│   └── {id}/download/        GET   # 下载
├── code-packages/             # 代码包管理
│   ├── GET/POST
│   └── {id}/download/        GET
├── project-deployments/       # 部署任务
│   ├── GET                    # 任务列表 (Agent 轮询)
│   └── {id}/update_progress/ POST  # 更新进度 (Agent)
├── agent/
│   ├── version/              GET   # Agent 最新版本
│   └── download/             GET   # 下载 Agent 脚本
├── install.sh                GET   # 设备安装脚本
└── auth/
    ├── login/                POST
    └── logout/               POST
```

### 2.7 Device Agent (设备端)

运行在每台开发板上的 Python 守护进程，负责：

1. **心跳上报** (每5秒)：CPU/内存/磁盘使用率、容器状态、服务健康状态
2. **任务轮询** (每5秒)：检查是否有待执行的部署/重启任务
3. **配置同步** (每3秒)：获取并应用远程配置
4. **部署执行**：拉取镜像、下载代码包、启动容器
5. **自动更新**：Agent 脚本自动升级

```python
# device-agent/device-agent.py 核心结构

AGENT_VERSION = "1.4.0"
HEARTBEAT_INTERVAL = 5     # 心跳间隔
TASK_POLL_INTERVAL = 5     # 任务轮询间隔
CONFIG_CHECK_INTERVAL = 3  # 配置检查间隔

def main():
    while True:
        # 1. 发送心跳
        send_heartbeat()
        
        # 2. 轮询部署任务
        tasks = poll_project_deployments()
        for task in tasks:
            if task['task_type'] == 'restart':
                execute_project_restart(task)
            else:
                execute_project_deployment(task)
        
        # 3. 检查配置更新
        check_and_apply_config()
        
        time.sleep(HEARTBEAT_INTERVAL)

def execute_project_deployment(deployment):
    """执行项目部署"""
    # 1. 更新状态：pulling_image
    # 2. 下载代码包到 code_mount_path
    # 3. 停止旧容器
    # 4. 启动新容器 (docker run)
    # 5. 健康检查
    # 6. 更新状态：completed/failed
```

### 2.8 部署流程

```
1. 用户访问 Web 管理界面
2. 在「项目管理」创建项目，配置镜像/代码包/启动命令
3. 选择目标设备，点击「部署」
4. 系统创建 ProjectDeployment 任务 (status=pending)
5. 设备 Agent 轮询到任务
6. Agent 执行：下载代码包 → 停止旧容器 → 启动新容器
7. Agent 上报进度和结果
8. Web 界面实时显示部署状态
```

### 2.9 设备上线流程

```bash
# 设备执行一条命令即可自动注册
curl -fsSL http://云服务器IP:8081/api/install.sh | sudo bash

# 安装脚本会：
# 1. 安装依赖 (Python3, Docker)
# 2. 下载 device-agent.py
# 3. 配置 systemd 服务
# 4. 自动注册到管理平台
```

---

## 三、PerformanceTest (性能测试)

### 3.1 项目定位
基于 Locust 的性能压测工具，用于测试 MiddlewareServer 的推理接口性能。

### 3.2 测试脚本

| 脚本 | 功能 |
|------|------|
| `locustfile.py` | Locust 主测试脚本，模拟用户并发请求 |
| `pipeline_test.py` | 流水线端到端测试 |
| `comprehensive_test.py` | 综合功能测试 |
| `stability_test.py` | 稳定性测试 |
| `abnormal_test.py` | 异常场景测试 |
| `e2e_simulator.py` | 端到端模拟器 |

### 3.3 Locust 使用

```bash
# 激活环境
conda activate perf-test

# Web UI 模式
locust -f locustfile.py
# 访问 http://localhost:8089

# 命令行模式
locust -f locustfile.py --headless -u 10 -r 2 -t 60s --html report.html
```

### 3.4 测试场景权重

```python
@task(5)  # 权重5，最常执行
def test_tube_orientation(self):
    """试管方向和液位检测"""

@task(3)  # 权重3
def test_tube_cap(self):
    """试管盖检测"""

@task(2)  # 权重2
def test_clean_tube(self):
    """空管检测"""

@task(1)  # 权重1
def test_barcode(self):
    """条码识别"""
```

---

## 四、技术要点速查

### 4.1 MiddlewareServer 关键代码位置

| 功能 | 文件路径 |
|------|---------|
| 插件基类 | `server/core/plugin/base.py` |
| 插件注册装饰器 | `server/plugins/__init__.py` |
| 相机配置 | `config/devices.yml` |
| 相机驱动 | `server/devices/MvImport/__init__.py` |
| API 路由 | `server/apis/urls.py` |
| 认证模块 | `server/core/auth/` |
| 日志目录 | `localstore/logs/YYYY-MM-DD/` |

### 4.2 DeviceManagementPlatform 关键代码位置

| 功能 | 文件路径 |
|------|---------|
| 数据模型 | `server/management/models.py` |
| API 视图 | `server/management/views.py` |
| Agent 脚本 | `device-agent/device-agent.py` |
| 前端路由 | `frontend/src/router/index.ts` |
| 类型定义 | `frontend/src/types/index.ts` |
| 部署脚本 | `deployment/deploy-simple/deploy.sh` |

### 4.3 常用配置

**MiddlewareServer 相机参数:**
```yaml
ExposureTime: 11000     # 曝光时间 (μs)
AcquisitionFrameRate: 3 # 帧率
ReverseY: true          # Y轴翻转
```

**DeviceManagementPlatform 环境变量:**
```
CLOUD_SERVER=http://服务器IP:8081/api
HEARTBEAT_INTERVAL=5
TASK_POLL_INTERVAL=5
CONFIG_CHECK_INTERVAL=3
```

### 4.4 常见开发任务

**添加新检测插件 (MiddlewareServer):**
1. 在 `server/plugins/` 创建新 Python 文件
2. 继承 `BasePlugin` 并实现 `name()` 和 `work()` 方法
3. 使用 `@load_plugin` 装饰器自动注册
4. 在 `tests/` 添加测试图片

**添加新 API:**
- 后端：在 `views.py` 添加 ViewSet 方法，在 `urls.py` 注册路由
- 前端：在 `api/` 目录添加请求函数，在页面中调用

**配置远程设备相机 IP:**
1. 在管理平台编辑设备配置
2. 配置自动推送到设备
3. Agent 更新 `config/devices.yml` 并重启服务

---

## 五、DeviceManagementPlatform 新功能开发指南

> 本章以「**一键配置开机自启动打开 Web 平台**」为例，详细说明端到端的功能开发流程。

### 5.1 功能需求分析

**需求描述：** 在管理平台上点击按钮，让设备开机后自动打开浏览器访问 MiddlewareServer 的 Web 界面。

**涉及组件：**
1. **后端 API** - 接收请求，创建任务
2. **Agent** - 轮询任务，在设备上执行配置
3. **前端** - 提供操作按钮，显示执行结果

### 5.2 开发步骤详解

#### 步骤1：后端 - 添加 API 接口

**文件：** `server/management/views.py`

在 `DeviceViewSet` 类中添加新的 action：

```python
# 在 DeviceViewSet 类中添加（约第850行附近，其他 @action 方法旁边）

@action(detail=True, methods=['post'])
def setup_autostart_browser(self, request, device_id=None):
    """
    配置开机自启动浏览器打开Web平台
    POST /api/devices/{device_id}/setup_autostart_browser/
    Body: {"url": "http://localhost:8000", "enabled": true}
    """
    device = self.get_object()
    url = request.data.get('url', 'http://localhost:8000')
    enabled = request.data.get('enabled', True)
    
    # 创建系统配置任务（复用现有的任务机制）
    task_id = self._create_system_task(device, 'setup_autostart_browser', {
        'url': url,
        'enabled': enabled
    })
    
    return Response({
        'status': 'success',
        'message': '开机自启动配置任务已创建',
        'task_id': task_id
    })

def _create_system_task(self, device, task_type, params):
    """创建系统配置任务（存储在 device.config 中）"""
    import time
    if not device.config:
        device.config = {}
    if 'system_tasks' not in device.config:
        device.config['system_tasks'] = {}
    
    task_id = str(int(time.time() * 1000))
    device.config['system_tasks'][task_id] = {
        'task_type': task_type,
        'params': params,
        'status': 'pending',
        'created_at': timezone.now().isoformat()
    }
    device.save()
    return task_id
```

**文件：** `server/management/views.py`

添加 Agent 轮询接口（如果复用现有机制则跳过）：

```python
@action(detail=True, methods=['get'], permission_classes=[AllowAny])
def pending_system_tasks(self, request, device_id=None):
    """Agent轮询待执行的系统配置任务"""
    device = self.get_object()
    if not device.config or 'system_tasks' not in device.config:
        return Response({'tasks': []})
    
    pending = []
    for task_id, task in device.config['system_tasks'].items():
        if task['status'] == 'pending':
            pending.append({'task_id': task_id, **task})
            device.config['system_tasks'][task_id]['status'] = 'processing'
    
    if pending:
        device.save()
    return Response({'tasks': pending})

@action(detail=True, methods=['post'], permission_classes=[AllowAny])
def report_system_task(self, request, device_id=None):
    """Agent上报系统任务执行结果"""
    device = self.get_object()
    task_id = request.data.get('task_id')
    status = request.data.get('status')  # completed/failed
    error_message = request.data.get('error_message', '')
    
    if device.config and 'system_tasks' in device.config:
        if task_id in device.config['system_tasks']:
            device.config['system_tasks'][task_id]['status'] = status
            device.config['system_tasks'][task_id]['error_message'] = error_message
            device.save()
    
    return Response({'message': 'ok'})
```

#### 步骤2：Agent - 添加任务执行逻辑

**文件：** `device-agent/device-agent.py`

在主循环中添加系统任务轮询（约第1800行附近）：

```python
# ==================== 系统配置任务 ====================
def poll_system_tasks():
    """轮询系统配置任务"""
    device_id = get_device_id()
    try:
        resp = requests.get(
            f"{CLOUD_SERVER}/devices/{device_id}/pending_system_tasks/",
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get('tasks', [])
    except Exception as e:
        logger.error(f"轮询系统任务失败: {e}")
    return []

def execute_system_task(task):
    """执行系统配置任务"""
    task_id = task['task_id']
    task_type = task['task_type']
    params = task['params']
    
    logger.info(f"执行系统任务: {task_type}")
    
    try:
        if task_type == 'setup_autostart_browser':
            result = setup_autostart_browser(params)
        else:
            result = False, f"未知任务类型: {task_type}"
        
        success, message = result
        report_system_task_result(task_id, 
            'completed' if success else 'failed',
            '' if success else message
        )
    except Exception as e:
        logger.error(f"执行系统任务失败: {e}")
        report_system_task_result(task_id, 'failed', str(e))

def setup_autostart_browser(params):
    """
    配置开机自启动浏览器
    在 Jetson 上创建 autostart 桌面文件
    """
    url = params.get('url', 'http://localhost:8000')
    enabled = params.get('enabled', True)
    
    autostart_dir = os.path.expanduser('~/.config/autostart')
    autostart_file = os.path.join(autostart_dir, 'middleware-browser.desktop')
    
    if not enabled:
        # 禁用：删除自启动文件
        if os.path.exists(autostart_file):
            os.remove(autostart_file)
            logger.info("已禁用开机自启动浏览器")
        return True, "已禁用"
    
    # 启用：创建自启动文件
    os.makedirs(autostart_dir, exist_ok=True)
    
    desktop_content = f"""[Desktop Entry]
Type=Application
Name=Middleware Web Browser
Exec=chromium-browser --start-fullscreen {url}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Auto open middleware web interface
"""
    
    with open(autostart_file, 'w') as f:
        f.write(desktop_content)
    
    # 设置可执行权限
    os.chmod(autostart_file, 0o755)
    
    logger.info(f"已配置开机自启动浏览器: {url}")
    return True, "配置成功"

def report_system_task_result(task_id, status, error_message=''):
    """上报系统任务执行结果"""
    device_id = get_device_id()
    try:
        requests.post(
            f"{CLOUD_SERVER}/devices/{device_id}/report_system_task/",
            json={
                'task_id': task_id,
                'status': status,
                'error_message': error_message
            },
            timeout=10
        )
    except Exception as e:
        logger.warning(f"上报系统任务结果失败: {e}")
```

在主循环 `main()` 函数中添加调用（约第1950行）：

```python
# 在 main() 的 while True 循环中添加：

# 4. 轮询并执行系统配置任务
for task in poll_system_tasks():
    execute_system_task(task)
```

#### 步骤3：前端 - 添加操作按钮

**文件：** `frontend/src/api/device.ts`

添加 API 请求函数：

```typescript
// 配置开机自启动浏览器
export function setupAutostartBrowser(deviceId: string, params: {
  url?: string
  enabled?: boolean
}) {
  return request.post(`/devices/${deviceId}/setup_autostart_browser/`, params)
}
```

**文件：** `frontend/src/views/DeviceDetail.vue`

在设备详情页添加操作按钮：

```vue
<template>
  <!-- 在操作按钮区域添加 -->
  <el-button @click="handleSetupAutostart" :loading="autostartLoading">
    配置开机自启动
  </el-button>
</template>

<script setup lang="ts">
import { setupAutostartBrowser } from '@/api/device'

const autostartLoading = ref(false)

const handleSetupAutostart = async () => {
  try {
    await ElMessageBox.confirm(
      '是否配置该设备开机后自动打开Web管理界面？',
      '配置开机自启动',
      { confirmButtonText: '确定', cancelButtonText: '取消' }
    )
    
    autostartLoading.value = true
    await setupAutostartBrowser(device.value.device_id, {
      url: 'http://localhost:8000',
      enabled: true
    })
    
    ElMessage.success('配置任务已下发，设备将在下次重启后生效')
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('配置失败')
    }
  } finally {
    autostartLoading.value = false
  }
}
</script>
```

### 5.3 数据流图解

```
┌─────────────────────────────────────────────────────────────────────┐
│                          开发流程图                                  │
└─────────────────────────────────────────────────────────────────────┘

用户点击「配置开机自启动」按钮
              │
              ▼
┌─────────────────────────────┐
│  前端 DeviceDetail.vue      │
│  调用 setupAutostartBrowser │
└──────────────┬──────────────┘
               │ POST /api/devices/{id}/setup_autostart_browser/
               ▼
┌─────────────────────────────┐
│  后端 views.py              │
│  DeviceViewSet              │
│  .setup_autostart_browser() │
│  → 创建任务存入 device.config │
└──────────────┬──────────────┘
               │ 任务存储在 device.config['system_tasks']
               ▼
┌─────────────────────────────┐
│  Agent 主循环（每5秒）       │
│  poll_system_tasks()        │
│  → 获取 pending 任务         │
└──────────────┬──────────────┘
               │ GET /api/devices/{id}/pending_system_tasks/
               ▼
┌─────────────────────────────┐
│  Agent 执行任务              │
│  execute_system_task()      │
│  → setup_autostart_browser()│
│  → 创建 .desktop 文件       │
└──────────────┬──────────────┘
               │ POST /api/devices/{id}/report_system_task/
               ▼
┌─────────────────────────────┐
│  后端更新任务状态            │
│  completed / failed         │
└─────────────────────────────┘
```

### 5.4 关键代码位置速查

| 开发任务 | 修改文件 | 位置提示 |
|---------|---------|----------|
| 添加后端 API | `server/management/views.py` | DeviceViewSet 类中，@action 装饰器 |
| 添加 Agent 任务处理 | `device-agent/device-agent.py` | 约1800行后，参考现有的 poll_xxx / execute_xxx |
| 添加前端 API | `frontend/src/api/device.ts` | 导出新函数 |
| 添加前端页面交互 | `frontend/src/views/DeviceDetail.vue` | 或 DeviceList.vue 视需求 |
| 添加类型定义 | `frontend/src/types/index.ts` | 新接口需要的类型 |

### 5.5 通用开发模式总结

DeviceManagementPlatform 的新功能开发遵循 **「任务下发-轮询执行-结果上报」** 三阶段模式：

```
┌──────────┐    任务创建     ┌──────────┐    轮询获取     ┌──────────┐
│  Web端   │ ──────────────► │  服务端   │ ◄────────────── │  Agent   │
│  用户操作 │                │  Django  │                │  设备端   │
└──────────┘                └──────────┘                └──────────┘
                                   │                        │
                                   │      执行结果上报        │
                                   ◄────────────────────────┘
```

**添加新的 Agent 功能的标准步骤：**

1. **后端**：在 `DeviceViewSet` 添加创建任务的 API + 轮询/上报 API
2. **Agent**：添加 `poll_xxx()` + `execute_xxx()` + `report_xxx()` 函数
3. **前端**：添加 API 函数 + 页面按钮/表单
4. **测试**：先手动调用 API，再测试完整流程

---

## 六、故障排查

### 6.1 MiddlewareServer

| 问题 | 排查步骤 |
|------|---------|
| 相机无法连接 | 检查 `config/devices.yml` IP配置；ping相机IP；检查防火墙 |
| 插件推理失败 | 查看 `localstore/logs/` 日志；检查模型文件是否存在 |
| 条码识别为空 | 调整 ROI 配置；增加曝光时间 |
| 容器无法启动 | 检查 NVIDIA Runtime；确认镜像正确加载 |

### 6.2 DeviceManagementPlatform

| 问题 | 排查步骤 |
|------|---------|
| 设备显示离线 | 检查 Agent 服务状态：`systemctl status device-agent` |
| 部署任务卡住 | 查看 Agent 日志：`/var/log/device-agent.log` |
| 配置未生效 | 确认 `pending_config_id` 已清除；检查配置格式 |

---

## 七、版本信息

| 组件 | 当前版本 |
|------|---------|
| MiddlewareServer | 基于 Django 5.0.4 |
| DeviceManagementPlatform | v1.0 |
| Device Agent | 1.4.0 |
| Python | 3.10+ |
| Node.js | 18+ |

---

## 八、实际交付流程 SOP

> 本章记录单人全栈远程交付视觉系统的完整流程，基于实际经验对齐，用于指导 AI 助手理解真实业务场景。

### 8.1 项目阶段定位

当前处于**预售阶段**：
- 系统功能已固定，工位1-5为同一套系统
- 尚未正式投产运行真实样本
- 存在功能边界争议（甲方试图追加合同外需求）
- 交付由**单人全栈**完成（开发+部署+运维）

### 8.2 完整交付流程

```
┌─────────────────────────────────────────────────────────────────┐
│  阶段1：出厂准备（你的工作，远程，约2天/台）                        │
├─────────────────────────────────────────────────────────────────┤
│  1. 淘宝采购 Jetson NX 开发板                                     │
│  2. Windows 虚拟机 Ubuntu + SDK Manager 刷 JetPack               │
│     ⚠️ 耗时最长，不太稳定，CUDA/cuDNN/TensorRT 通过此安装          │
│  3. 安装外壳 + 接杜邦线（实现通电自开机）                           │
│  4. 公司局域网下 SSH 连接开发板                                    │
│  5. SCP 传输 Docker 镜像 tar 包（本地 docker save）                │
│  6. docker load 加载镜像                                          │
│  7. systemctl enable docker（Docker 开机自启动）                   │
│  8. 执行 install.sh 安装 Agent → 自动注册到管理平台                 │
│  9. 管理平台点「部署」→ 容器启动（--restart=always）               │
│  10. 安装 Chromium 浏览器                                         │
│  11. 创建浏览器应用快捷方式 + 配置开机自启动打开 Web 页面            │
│  12. 预装向日葵（远程桌面兜底）                                     │
│  13. 手动配置 frpc.ini（SSH/Web 端口穿透）                         │
│  14. 验证一切正常后发货                                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  阶段2：配件采购（销售协调）                                        │
├─────────────────────────────────────────────────────────────────┤
│  - 海康工业相机 → 销售采购，直发甲方                                │
│  - 配件（网线/电源/支架/光源）→ 销售采购，直发甲方                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  阶段3：现场安装（甲方工人）                                        │
├─────────────────────────────────────────────────────────────────┤
│  1. 收货验收                                                       │
│  2. 物理安装：Jetson + 相机 + 显示屏 + 配件                         │
│  3. 接线、联网                                                     │
│  4. 给你开通外网访问权限                                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  阶段4：远程配置（你的工作）                                        │
├─────────────────────────────────────────────────────────────────┤
│  1. 向日葵连接 → 先看桌面情况（但卡、复制粘贴不好用）                 │
│  2. 通过 frp 建立 SSH 隧道 → 稳定的命令行                           │
│  3. 配置相机 IP、网络等                                            │
│  4. 验证系统正常                                                   │
│  5. 必要时打电话远程指挥甲方工人操作                                 │
│  6. 非必要不去现场                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  阶段5：日常运维（持续）                                            │
├─────────────────────────────────────────────────────────────────┤
│  - 远程通过 向日葵 + frp 介入                                       │
│  - 设备管理平台查看状态、日志                                       │
│  - 代码更新：打包上传 → 管理平台部署                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 当前痛点分析

#### 8.3.1 出厂准备阶段

| 痛点 | 现状 | 影响 |
|------|------|------|
| **JetPack 刷机不稳定** | SDK Manager 在虚拟机中运行，每次结果不确定 | 单台设备可能要反复尝试 |
| **刷机耗时长** | 完整刷机 + 安装依赖需要数小时 | 2天/台的主要时间消耗 |
| **手动步骤多** | 从第4步到第13步全是手工操作 | 容易遗漏、效率低 |
| **浏览器自启不优雅** | 手动装浏览器 + 配 autostart | 每台都要重复 |
| **frp 配置繁琐** | 手动 SSH 写 frpc.ini，手动分配端口 | 容易出错、端口难管理 |

#### 8.3.2 远程运维阶段

| 痛点 | 现状 | 影响 |
|------|------|------|
| **向日葵体验差** | 卡顿、复制粘贴不好用 | 只能兜底看桌面 |
| **frp 依赖手动配置** | 每台设备要单独配端口 | 设备多了难管理 |
| **无法主动连接设备** | 设备在内网，必须设备先连出来 | 依赖甲方给外网权限 |
| **状态不够可视化** | 管理平台信息有限 | 排查问题时抓瞎 |

#### 8.3.3 商务层面

| 痛点 | 现状 |
|------|------|
| **功能边界争议** | 甲方试图用尾款套牢，追加合同外需求（粪便检测、自动学习等） |
| **科研合同 vs 产品化** | 合同是科研横向，甲方按医疗设备标准要求 |
| **验收标准漂移** | 即使书面锁定，现场投诉仍会传导压力 |

### 8.4 已实现的能力

基于代码分析，当前系统已具备：

| 能力 | 状态 | 实现位置 |
|------|------|----------|
| 设备自动注册 | ✅ 已实现 | `install.sh` + Agent |
| 心跳监控 | ✅ 已实现 | 30秒心跳，2分钟判定离线 |
| 资源监控 | ✅ 已实现 | CPU/内存/磁盘上报 |
| 远程部署 | ✅ 已实现 | ProjectDeployment |
| 批量部署 | ✅ 已实现 | 多设备选择 |
| 容器管理 | ✅ 已实现 | 启动/停止/重启 |
| 日志远程查看 | ✅ 已实现 | list/read/search_logs |
| Agent 自动更新 | ✅ 已实现 | 版本检查 + 热更新 |
| 服务健康检查 | ✅ 已实现 | HTTP 健康检查 |
| 配置远程同步 | ✅ 已实现 | pending_config 机制 |

### 8.5 待实现的能力

| 能力 | 优先级 | 说明 |
|------|--------|------|
| **反向 SSH 隧道** | P0 | 设备联网即可 SSH，不依赖手动配 frp |
| **端口自动分配** | P0 | 管理平台自动分配，告别手动管理 |
| **出厂配置自动化** | P1 | install.sh 一条命令完成所有配置 |
| **离线告警** | P1 | 设备离线主动通知 |
| **版本回滚** | P2 | 部署失败可一键回退 |
| **磁盘自动清理** | P2 | 防止日志写满 |

---

## 九、Agent 增强方案设计

> 目标：**一条命令完成出厂配置，设备联网即可远程管理**

### 9.1 目标架构

```
理想工作流：
┌─────────────────────────────────────────────────────────────────┐
│  1. 刷好 JetPack（未来可用镜像克隆）                                │
│  2. 执行一条命令：curl install.sh | bash                           │
│  3. Agent 自动完成：                                               │
│     ├── 注册到管理平台                                             │
│     ├── 获取「出厂配置」任务                                        │
│     ├── systemctl enable docker                                   │
│     ├── 拉取并启动 Docker 容器（--restart=always）                  │
│     ├── 创建浏览器应用 + 开机自启动                                  │
│     ├── 配置 frp 反向隧道 → 管理平台自动分配端口                      │
│     ├── 安装向日葵（可选）                                          │
│     └── 上报完成状态                                               │
│  4. 发货                                                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  甲方插电联网后：                                                   │
│  - 设备自动连上管理平台                                             │
│  - 自动建立 frp 隧道 → 管理平台显示 SSH 连接命令                      │
│  - 你随时能 SSH 进去                                               │
│  - 管理平台展示一切：状态、日志、配置、监控                           │
│  - 不抓瞎                                                         │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 反向隧道方案

#### 当前 frp 环境

```yaml
# 已有资源（咸鱼购买）
frp_server: frp9.mmszxc.xin
server_port: 39981
admin_port: 39982  # 管理界面
token: "198631"
port_range: 39983-39993  # 可用端口
```

#### 方案设计

```
┌──────────────────┐         ┌──────────────────┐
│  Jetson 设备      │         │  frp 服务器       │
│                  │  主动连接 │  (公网)          │
│  Agent           │ ───────► │                  │
│  内置 frpc       │          │  39983 → SSH     │
│                  │ ◄─────── │  39984 → Web     │
│  SSH:22          │  反向隧道 │  ...             │
│  Web:8000        │          │                  │
└──────────────────┘         └──────────────────┘

你在任意地方执行：
  ssh -p 39983 user@frp9.mmszxc.xin
  浏览器访问 http://frp9.mmszxc.xin:39984
即可连接到甲方内网的 Jetson
```

#### 端口自动分配

```python
# 管理平台后端 - 设备注册时自动分配端口
class Device(models.Model):
    # ... 现有字段 ...
    frp_ssh_port = models.IntegerField(null=True)   # 分配的 SSH 端口
    frp_web_port = models.IntegerField(null=True)   # 分配的 Web 端口
    frp_status = models.CharField(default='disconnected')  # 隧道状态

def allocate_frp_ports():
    """自动分配端口"""
    used_ports = Device.objects.values_list('frp_ssh_port', 'frp_web_port')
    used = set(p for pair in used_ports for p in pair if p)
    available = set(range(39983, 39994)) - used
    # 返回两个连续端口
    ...
```

### 9.3 Agent 新增命令

```python
# device-agent.py 新增功能

# 出厂配置命令（install.sh 后自动执行）
setup_factory_config():
    ├── setup_docker_autostart()      # systemctl enable docker
    ├── setup_browser_app()           # 创建 .desktop 应用
    ├── setup_autostart_browser()     # 开机自启动浏览器
    ├── setup_frp_tunnel()            # 配置 frpc + systemd 服务
    └── setup_sunlogin()              # 安装向日葵（可选）

# 运维命令（管理平台下发）
get_frp_status()                      # 获取隧道状态
restart_frp()                         # 重启隧道
cleanup_logs()                        # 清理旧日志
get_system_info()                     # 获取系统详情
capture_screenshot()                  # 截取桌面（可选）
```

### 9.4 管理平台增强

```
设备详情页增强：
├── 「SSH 连接」卡片
│   ├── 显示：ssh -p 39983 user@frp9.mmszxc.xin
│   ├── 一键复制按钮
│   └── 隧道状态：🟢 已连接 / 🔴 断开
├── 「Web 访问」卡片
│   └── 显示：http://frp9.mmszxc.xin:39984
├── 「向日葵」卡片
│   └── 显示向日葵识别码（如果已配置）
└── 「系统任务」记录
    └── 显示出厂配置执行历史
```

### 9.5 实现优先级

| 阶段 | 功能 | 工作量 | 价值 |
|------|------|--------|------|
| **Phase 1** | 反向隧道 + 端口自动分配 | 2-3天 | 解决远程 SSH 痛点 |
| **Phase 2** | 出厂配置自动化 | 1-2天 | 减少手工步骤 |
| **Phase 3** | 离线告警通知 | 0.5天 | 被动变主动 |
| **Phase 4** | 磁盘清理 + 版本回滚 | 1天 | 运维便利 |

---

## 十、常见问题 FAQ

### Q: 设备在甲方内网，怎么远程连接？

**现状**：预装向日葵 + 手动配置 frp，比较繁琐。

**规划**：Agent 自动配置 frp 反向隧道，管理平台显示 SSH 连接命令。

### Q: 出厂一台设备要多久？

**现状**：专心搞约2天，主要耗时在 JetPack 刷机和手工配置。

**优化方向**：
1. 系统镜像克隆（刷机几十分钟）
2. install.sh 一键完成所有配置

### Q: 甲方工人需要做什么？

只需要：
1. 物理安装设备
2. 插电、插网线
3. 给你开通外网访问权限

其他全部远程完成。

### Q: 代码更新流程是什么？

1. 本地打包代码为 ZIP
2. 上传到管理平台「代码包」
3. 选择设备，点击「部署」
4. Agent 自动下载、解压、重启容器

---

*文档生成时间: 2026-01-29*
*最后更新: 2026-01-29 - 新增交付流程SOP、痛点分析、Agent增强方案*
