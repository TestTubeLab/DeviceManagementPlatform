# MiddlewareServer 远程部署 SOP 手册

> 版本: v1.0.0  
> 更新日期: 2025-11-27  
> 适用项目: 生物样本检测流水线视觉服务器

---

## 一、系统架构概述

```
┌─────────────────────────────────────────────────────────────┐
│                      开发/运维端                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          DeviceManagementPlatform                   │   │
│  │          http://114.132.187.96:8081                 │   │
│  │  • 设备管理  • 项目管理  • 远程部署  • 任务监控     │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────┘
                             │ 互联网 (4G/WiFi/内网穿透)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      客户现场                                │
│                                                              │
│  ┌──────────────┐   有线网络    ┌──────────────────────┐   │
│  │   工业相机    │◄────────────►│   Jetson Orin        │   │
│  │ 192.168.x.201│              │   (MiddlewareServer)  │   │
│  │ 192.168.x.202│              │                       │   │
│  │ 192.168.x.203│              │  • Device Agent       │   │
│  │ 192.168.x.204│              │  • Docker Container   │   │
│  │ 192.168.x.205│              │  • 视觉检测服务       │   │
│  └──────────────┘              └───────────┬───────────┘   │
│                                            │               │
│                                            ▼               │
│                                ┌──────────────────────┐   │
│                                │      上位机          │   │
│                                │   192.168.x.29       │   │
│                                │   (接收检测结果)      │   │
│                                └──────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、部署前准备

### 2.1 需要确认的信息

| 项目 | 说明 | 示例 |
|------|------|------|
| 现场网段 | 相机/上位机所在网段 | `192.168.16` |
| 上位机 IP | 接收检测结果的电脑 | `192.168.16.29` |
| 上位机端口 | Socket 通信端口 | `9088` |
| 相机 IP | 5台相机的 IP | `192.168.16.201-205` |
| 开发板联网方式 | WiFi/4G/有线 | WiFi |

### 2.2 准备物料

#### 2.2.1 Docker 镜像

```bash
# 镜像名称
middleware-server-env:r36.2.0

# 镜像大小
约 15GB（压缩后 7-8GB）

# 导出命令
docker save middleware-server-env:r36.2.0 | gzip > middleware-env.tar.gz
```

#### 2.2.2 代码包

```
MiddlewareServer.zip
├── MiddlewareServer/
│   ├── start.sh          # 启动脚本
│   ├── config/
│   │   └── devices.yml   # 相机配置
│   ├── server/
│   │   └── server/
│   │       └── settings.py  # 上位机配置
│   └── frontend/
│       └── ...
```

#### 2.2.3 start.sh 模板

```bash
#!/bin/bash

# ========== 设置 PATH ==========
export PATH="/opt/node/bin:$PATH"

# ========== 环境初始化 ==========
export MVCAM_COMMON_RUNENV=/opt/MVS/lib 
export TZ=Asia/Shanghai

# Conda 初始化
eval "$(/root/miniforge3/bin/conda shell.bash hook)"
conda activate server

# ========== 首次初始化（只执行一次）==========
INIT_FLAG="/work/.initialized"

if [ ! -f "$INIT_FLAG" ]; then
    echo "=========================================="
    echo "首次部署，执行初始化..."
    echo "=========================================="
    
    cd /work/MiddlewareServer/server
    python manage.py migrate --noinput
    
    python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('管理员账户已创建: admin / admin123')
"
    
    cd /work/MiddlewareServer/frontend
    [ ! -d "node_modules" ] && npm install
    
    touch "$INIT_FLAG"
fi

# ========== 启动服务 ==========
echo "=========================================="
echo "启动服务..."
echo "=========================================="

# 启动前端
cd /work/MiddlewareServer/frontend
npm run dev &

# 启动后端
eval "$(/root/miniforge3/bin/conda shell.bash hook)"
conda activate server
cd /work/MiddlewareServer/server
python manage.py runserver 0.0.0.0:8000 --noreload &

# 保持运行
tail -f /dev/null
```

---

## 三、首次部署流程

### 3.1 现场硬件准备（现场人员）

```
□ 1. 开发板接通电源
□ 2. 连接有线网口到现场交换机（相机/上位机同网段）
□ 3. 连接 WiFi 或插入 4G 网卡（用于远程管理）
□ 4. 确认开发板正常启动
□ 5. 告知远程人员开发板 IP 或内网穿透地址
```

### 3.2 安装 Agent（远程操作）

```bash
# SSH 连接到开发板
ssh nx001@开发板IP

# 一键安装 Agent
curl -fsSL http://114.132.187.96:8081/api/install.sh | sudo bash

# 检查 Agent 状态
sudo systemctl status device-agent

# 查看 Agent 日志
sudo journalctl -u device-agent -f
```

### 3.3 传输 Docker 镜像（如果现场没有）

```bash
# 从开发机传输到现场（支持断点续传）
rsync -avP --progress -e "ssh -p 端口" middleware-env.tar.gz user@现场地址:/home/user/

# 现场加载镜像
ssh user@现场地址
docker load < middleware-env.tar.gz
docker images  # 确认镜像已加载
```

### 3.4 配置并上传代码包

#### 3.4.1 修改网络配置

**settings.py** - 修改上位机 IP：
```python
SOCKET_CONFIG = {
    "reverse": {
        "HOST": "192.168.16.29",  # ← 改成现场上位机 IP
        "PORT": 9088,
    },
}
```

**config/devices.yml** - 修改相机 IP：
```yaml
- name: 样品盘
  device: "devices.HiKDevice"
  params: 192.168.16.201  # ← 改成现场网段

- name: 前处理
  device: "devices.HiKDevice"
  params: 192.168.16.202  # ← 改成现场网段
  
# ... 其他相机同理
```

#### 3.4.2 打包代码

```powershell
# Windows PowerShell
cd D:\yms
Compress-Archive -Path MiddlewareServer -DestinationPath MiddlewareServer.zip -Force
```

#### 3.4.3 上传到平台

1. 访问 http://114.132.187.96:8081
2. 登录（admin / admin123）
3. 进入「项目管理」
4. 上传代码包，填写版本号

### 3.5 在平台配置项目

| 配置项 | 值 |
|--------|-----|
| 项目名称 | MiddlewareServer |
| 版本 | v1.0.0 |
| 本地镜像名 | `middleware-server-env:r36.2.0` |
| 容器名称 | `middleware` |
| 代码挂载路径 | `/opt/work` |
| 工作目录 | `/work` |
| 启动命令 | `bash /work/MiddlewareServer/start.sh` |
| NVIDIA Runtime | ✅ 启用 |
| Host 网络 | ✅ 启用 |
| 特权模式 | ✅ 启用 |

### 3.6 执行部署

1. 在「项目管理」点击「部署」按钮
2. 选择目标设备
3. 确认部署
4. 在「任务管理」监控进度

### 3.7 验证部署结果

```bash
# SSH 到现场开发板
ssh user@现场地址

# 检查容器状态
docker ps

# 查看运行日志
docker logs -f middleware

# 检查关键服务
curl http://localhost:8000/  # Django 后端
curl http://localhost:5013/  # Vite 前端
```

**日志中应看到：**
```
✅ 数据库迁移成功
✅ 管理员账户已创建
✅ Django 启动成功 (http://0.0.0.0:8000/)
✅ Vite 启动成功 (http://localhost:5013/)
✅ 插件加载成功 (7个)
✅ 相机连接成功
✅ 上位机连接成功
```

---

## 四、更新部署流程

### 4.1 代码更新

```
1. 本地修改代码
2. 重新打包 ZIP
3. 上传新代码包到平台
4. 点击「部署」选择设备
5. 监控部署进度
```

### 4.2 重启服务

**方法1：通过平台**
```
设备详情 → 点击「重启」按钮
```

**方法2：通过命令行**
```bash
docker restart middleware
```

---

## 五、故障排查

### 5.1 Agent 无法启动

```bash
# 查看日志
sudo journalctl -u device-agent -n 50

# 常见问题
# 1. 缺少依赖
pip3 install requests psutil -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 语法错误
python3 -m py_compile /opt/device-agent/agent.py
```

### 5.2 容器启动失败

```bash
# 查看详细错误
docker logs middleware

# 常见问题
# 1. 镜像不存在
docker images | grep middleware

# 2. 权限问题（start.sh）
# 确保启动命令是：bash /work/MiddlewareServer/start.sh
```

### 5.3 npm: command not found

```bash
# 进入容器查找 npm 路径
docker exec -it middleware bash
find / -name npm -type f 2>/dev/null | head -5

# 在 start.sh 开头添加正确的 PATH
export PATH="/opt/node/bin:$PATH"
# 或
export PATH="/root/.nvm/versions/node/v18.x.x/bin:$PATH"
```

### 5.4 相机连接失败

```
错误：192.168.31.201 is not a valid device index or IP address
原因：相机 IP 与配置不匹配

解决：
1. 确认现场网段
2. 修改 config/devices.yml 中的相机 IP
3. 重新打包上传部署
```

### 5.5 上位机连接超时

```
错误：Connection timed out... Reconnecting to 192.168.31.29:9088
原因：上位机 IP 配置错误或网络不通

解决：
1. 确认上位机 IP
2. 修改 settings.py 中的 SOCKET_CONFIG
3. 重新打包上传部署
```

---

## 六、网络配置参考

### 6.1 典型网络拓扑

```
开发板 (192.168.16.101)
    ├── eth0 ──► 相机网络 (192.168.16.x)
    │            ├── 相机1: 192.168.16.201
    │            ├── 相机2: 192.168.16.202
    │            ├── 相机3: 192.168.16.203
    │            ├── 相机4: 192.168.16.204
    │            ├── 相机5: 192.168.16.205
    │            └── 上位机: 192.168.16.29
    │
    └── wlan0 ──► 管理网络 (WiFi/4G)
                  └── 连接管理平台
```

### 6.2 常用网段配置

| 现场 | 网段 | 上位机 | 相机范围 |
|------|------|--------|----------|
| 默认 | 192.168.31 | .29 | .201-.205 |
| 医院A | 192.168.16 | .29 | .201-.205 |
| 医院B | 10.0.1 | .29 | .201-.205 |

---

## 七、检查清单

### 7.1 部署前检查

```
□ 确认现场网段
□ 确认上位机 IP
□ 确认相机 IP
□ 修改 settings.py
□ 修改 devices.yml
□ 更新 start.sh
□ 打包代码
□ 上传到平台
```

### 7.2 部署后检查

```
□ 容器运行正常 (docker ps)
□ Django 启动成功 (端口 8000)
□ Vite 启动成功 (端口 5013)
□ 数据库迁移完成
□ 管理员账户创建
□ 相机全部连接
□ 上位机通信正常
```

---

## 八、联系方式

| 角色 | 联系方式 |
|------|----------|
| 开发负责人 | - |
| 运维支持 | - |
| 现场支持 | - |

---

## 附录

### A. 管理平台地址

- URL: http://114.132.187.96:8081
- 账号: admin
- 密码: admin123

### B. 常用命令速查

```bash
# Agent 管理
sudo systemctl status device-agent
sudo systemctl restart device-agent
sudo journalctl -u device-agent -f

# 容器管理
docker ps
docker logs -f middleware
docker restart middleware
docker exec -it middleware bash

# 网络检查
ip addr
ping 上位机IP
```

### C. 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0.0 | 2025-11-27 | 初始版本 |

---

*文档维护：如有流程变更，请及时更新本手册*


