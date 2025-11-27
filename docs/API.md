# API文档

## 基础信息

**Base URL**: `http://your-cloud.com/api/`

**认证方式**: Token Authentication

**Content-Type**: `application/json`

---

## 认证

### 获取Token

```http
POST /api/auth/token/
Content-Type: application/json

{
  "username": "admin",
  "password": "your_password"
}
```

**响应**:
```json
{
  "token": "abc123def456..."
}
```

在后续请求中携带Token：
```http
Authorization: Token abc123def456...
```

---

## 设备管理

### 1. 注册设备

设备端调用，向云端注册新设备。

```http
POST /api/devices/register/
Content-Type: application/json

{
  "device_id": "dev_abc123",
  "mac_address": "00:11:22:33:44:55",
  "ip_address": "192.168.1.100",
  "hostname": "device-001"
}
```

**响应**:
```json
{
  "device_id": "dev_abc123",
  "status": "waiting",
  "created": true
}
```

### 2. 获取设备列表

```http
GET /api/devices/
```

**响应**:
```json
{
  "count": 10,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "device_id": "dev_abc123",
      "name": "生产线A-设备1",
      "location": "北京工厂",
      "mac_address": "00:11:22:33:44:55",
      "ip_address": "192.168.1.100",
      "status": "online",
      "current_version": "v1.0.3",
      "last_heartbeat": "2025-11-24T10:30:00Z",
      "cpu_usage": 45.2,
      "memory_usage": 62.5,
      "disk_usage": 38.7,
      "is_online": true,
      "created_at": "2025-11-20T08:00:00Z",
      "updated_at": "2025-11-24T10:30:00Z"
    }
  ]
}
```

### 3. 获取设备详情

```http
GET /api/devices/{device_id}/
```

**响应**:
```json
{
  "id": 1,
  "device_id": "dev_abc123",
  "name": "生产线A-设备1",
  "location": "北京工厂",
  "mac_address": "00:11:22:33:44:55",
  "ip_address": "192.168.1.100",
  "status": "online",
  "current_version": "v1.0.3",
  "last_heartbeat": "2025-11-24T10:30:00Z",
  "cpu_usage": 45.2,
  "memory_usage": 62.5,
  "disk_usage": 38.7,
  "config": {
    "reverse_socket_host": "192.168.31.29",
    "reverse_socket_port": 9088
  },
  "is_online": true,
  "created_at": "2025-11-20T08:00:00Z",
  "updated_at": "2025-11-24T10:30:00Z"
}
```

### 4. 更新设备信息

```http
PATCH /api/devices/{device_id}/
Content-Type: application/json

{
  "name": "生产线B-设备1",
  "location": "上海工厂",
  "config": {
    "reverse_socket_host": "192.168.31.30"
  }
}
```

### 5. 设备心跳

设备端定时调用，上报状态和性能指标。

```http
POST /api/devices/{device_id}/heartbeat/
Content-Type: application/json

{
  "version": "v1.0.3",
  "cpu_usage": 45.2,
  "memory_usage": 62.5,
  "disk_usage": 38.7
}
```

**响应**:
```json
{
  "command": "update",
  "task_id": 123,
  "version": "v1.0.4"
}
```

**command类型**:
- `none`: 无任务
- `deploy`: 部署任务
- `update`: 更新任务

### 6. 获取部署指令

设备端调用，检查是否有待执行的部署任务。

```http
GET /api/devices/{device_id}/deployment/
```

**响应（有任务）**:
```json
{
  "status": "ready_to_deploy",
  "deployment_config": {
    "image": "registry:5000/middleware:v1.0.3",
    "config": {
      "reverse_socket_host": "192.168.31.29",
      "reverse_socket_port": 9088
    }
  }
}
```

**响应（无任务）**:
```json
{
  "status": "waiting"
}
```

### 7. 上报进度

设备端上报部署/更新进度。

```http
POST /api/devices/{device_id}/progress/
Content-Type: application/json

{
  "status": "downloading",
  "progress": 50,
  "message": "正在下载镜像..."
}
```

### 8. 批量更新

```http
POST /api/devices/batch_update/
Content-Type: application/json

{
  "device_ids": ["dev_001", "dev_002", "dev_003"],
  "version": "v1.0.4"
}
```

**响应**:
```json
{
  "created_tasks": 3,
  "task_ids": [101, 102, 103]
}
```

---

## 部署管理

### 1. 创建部署任务

```http
POST /api/deployments/
Content-Type: application/json

{
  "device": 1,
  "target_version": "v1.0.3",
  "config": {
    "reverse_socket_host": "192.168.31.29",
    "reverse_socket_port": 9088
  }
}
```

**响应**:
```json
{
  "id": 456,
  "device": 1,
  "device_name": "生产线A-设备1",
  "target_version": "v1.0.3",
  "status": "pending",
  "progress": 0,
  "message": "",
  "created_at": "2025-11-24T10:00:00Z"
}
```

### 2. 获取部署任务列表

```http
GET /api/deployments/
```

**查询参数**:
- `device`: 设备ID（过滤）
- `status`: 状态（过滤）

### 3. 更新部署进度

设备端调用。

```http
POST /api/deployments/{task_id}/update_progress/
Content-Type: application/json

{
  "status": "downloading",
  "progress": 50,
  "message": "正在下载镜像...",
  "error_message": ""
}
```

---

## 更新管理

### 1. 创建更新任务

```http
POST /api/updates/
Content-Type: application/json

{
  "device": 1,
  "from_version": "v1.0.3",
  "target_version": "v1.0.4"
}
```

### 2. 获取更新任务列表

```http
GET /api/updates/
```

**查询参数**:
- `device`: 设备ID（过滤）
- `status`: 状态（过滤）

### 3. 更新任务进度

设备端调用。

```http
POST /api/updates/{task_id}/update_progress/
Content-Type: application/json

{
  "status": "downloading",
  "progress": 50,
  "error_message": ""
}
```

---

## 日志管理

### 1. 获取设备日志

```http
GET /api/logs/?device_id=dev_abc123
```

**查询参数**:
- `device_id`: 设备ID（必填）
- `level`: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
- `start_time`: 开始时间（ISO格式）
- `end_time`: 结束时间（ISO格式）

**响应**:
```json
{
  "count": 100,
  "results": [
    {
      "id": 1001,
      "device": 1,
      "device_name": "生产线A-设备1",
      "level": "INFO",
      "message": "服务启动成功",
      "timestamp": "2025-11-24T10:00:00Z"
    }
  ]
}
```

### 2. 创建日志

设备端调用（批量上报）。

```http
POST /api/logs/
Content-Type: application/json

{
  "device": 1,
  "logs": [
    {
      "level": "INFO",
      "message": "检测到试管: 3个",
      "timestamp": "2025-11-24T10:00:00Z"
    },
    {
      "level": "WARNING",
      "message": "相机连接不稳定",
      "timestamp": "2025-11-24T10:01:00Z"
    }
  ]
}
```

---

## 错误码

| 状态码 | 说明 |
|-------|------|
| 200 | 请求成功 |
| 201 | 创建成功 |
| 204 | 删除成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 500 | 服务器错误 |

**错误响应格式**:
```json
{
  "error": "错误描述",
  "detail": "详细信息"
}
```

---

## Webhook（可选功能）

配置Webhook URL后，系统会在特定事件发生时推送通知。

### 事件类型

#### 设备离线

```json
{
  "event": "device.offline",
  "device_id": "dev_abc123",
  "device_name": "生产线A-设备1",
  "timestamp": "2025-11-24T10:00:00Z"
}
```

#### 部署完成

```json
{
  "event": "deployment.completed",
  "device_id": "dev_abc123",
  "version": "v1.0.3",
  "timestamp": "2025-11-24T10:05:00Z"
}
```

#### 更新失败

```json
{
  "event": "update.failed",
  "device_id": "dev_abc123",
  "version": "v1.0.4",
  "error": "镜像拉取失败",
  "timestamp": "2025-11-24T10:10:00Z"
}
```

---

## 示例代码

### Python

```python
import requests

# 认证
resp = requests.post(
    "http://your-cloud.com/api/auth/token/",
    json={"username": "admin", "password": "password"}
)
token = resp.json()["token"]

# 获取设备列表
headers = {"Authorization": f"Token {token}"}
resp = requests.get(
    "http://your-cloud.com/api/devices/",
    headers=headers
)
devices = resp.json()["results"]

# 创建部署任务
resp = requests.post(
    "http://your-cloud.com/api/deployments/",
    headers=headers,
    json={
        "device": 1,
        "target_version": "v1.0.3",
        "config": {"reverse_socket_host": "192.168.31.29"}
    }
)
task = resp.json()
```

### JavaScript

```javascript
// 认证
const authResp = await fetch("http://your-cloud.com/api/auth/token/", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({username: "admin", password: "password"})
});
const {token} = await authResp.json();

// 获取设备列表
const devicesResp = await fetch("http://your-cloud.com/api/devices/", {
  headers: {"Authorization": `Token ${token}`}
});
const {results: devices} = await devicesResp.json();
```

### Bash

```bash
# 认证
TOKEN=$(curl -s -X POST http://your-cloud.com/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}' \
  | jq -r '.token')

# 获取设备列表
curl -H "Authorization: Token $TOKEN" \
  http://your-cloud.com/api/devices/
```

---

更多示例请参考 [使用手册](USAGE.md)。



