# Device Agent 说明文档

当前 Agent 版本：`1.7.3`。本版本新增有界 journal 日志任务，并限制业务日志访问范围和资源消耗；不新增运行依赖。

新增日志功能保持 Python 3.8 兼容，路径包含关系和服务名后缀处理不依赖 Python 3.9 API。测试覆盖这些旧 API 边界；Python 3.8 语法解析检查不能替代目标设备的实际运行验证。

## 1. 这是什么

`device-agent` 是运行在边缘设备上的常驻代理程序，定位不是“被别人直接调用的服务端接口”，而是一个**主动向云端拉取任务、主动向云端上报状态的客户端 Agent**。

它的核心职责可以概括为 8 件事：

1. 设备首次注册与身份识别。
2. 定时心跳上报设备在线状态、IP、资源占用、容器状态、服务健康状态。
3. 轮询并执行 Docker 镜像部署任务。
4. 轮询并执行项目级部署任务（镜像、代码包、Git、配置、重启）。
5. 执行 OTA 更新任务。
6. 接收并应用 FRP 配置，控制本地 `frpc` 启停。
7. 轮询日志任务并回传结果，同时定时上传容器日志。
8. 支持 Agent 自更新。

如果只看一句话，这个 Agent 就是：

> 云平台和设备之间的“执行器 + 状态采集器 + 配置落地器”。

---

## 2. 目录里几个文件分别做什么

当前目录下主要有 3 个脚本：

| 文件 | 作用 | 当前定位 |
| --- | --- | --- |
| `device-agent.py` | 正式使用中的完整 Agent | 主体 |
| `bootstrap-agent.py` | 早期零接触引导版本，只负责注册、等待部署、启动基础容器 | 历史兼容 / 参考 |
| `install.sh` | 目录内静态安装脚本，会下载 `bootstrap-agent.py` | 旧入口 / 示例 |

这里有一个非常重要的区别：

- 仓库里的 `device-agent/install.sh` 是**旧版 bootstrap 安装入口**。
- 云平台暴露的 `/api/install.sh` 才是**当前正式安装入口**，它会下载 `device-agent.py` 并创建 `device-agent.service`。

也就是说，阅读这套系统时要分清两代逻辑：

- 旧逻辑：`install.sh` + `bootstrap-agent.py`
- 新逻辑：`/api/install.sh` + `device-agent.py`

当前正式维护对象应当以 `device-agent.py` 为准。

---

## 3. 推荐安装和启动方式

### 3.1 推荐方式

推荐通过云平台动态下发的安装脚本安装：

```bash
curl -fsSL http://<server>:8081/api/install.sh | sudo bash
```

这条命令背后做的事情是：

1. 安装 Python 运行依赖：`requests`、`psutil`、`yaml`。
2. 安装 Docker（如未安装）。
3. 创建 `/opt/device-agent` 目录。
4. 从云端下载最新 `device-agent.py` 到 `/opt/device-agent/agent.py`。
5. 创建 `systemd` 服务 `device-agent.service`。
6. 设置开机自启并立即启动。

### 3.2 安装后常用命令

```bash
sudo systemctl status device-agent
sudo systemctl restart device-agent
sudo journalctl -u device-agent -f
```

### 3.3 Agent 运行假设

`device-agent.py` 默认假设设备具备以下能力：

- Linux 环境
- `systemd`
- `docker`
- `python3`
- `ip` 命令
- 可访问云平台 HTTP API

---

## 4. Agent 启动后完整流程

### 4.1 首次启动

Agent 启动后会先读取本地 `device_id`：

- 如果 `/etc/device-id` 已存在，直接复用。
- 如果不存在，就根据硬件指纹生成稳定设备 ID，并调用注册接口。

### 4.2 主循环

`device-agent.py` 的 `main()` 是一个常驻循环，每秒醒一次，然后按不同间隔执行不同任务：

| 任务 | 默认间隔 | 说明 |
| --- | --- | --- |
| 心跳上报 | 5 秒 | 上报在线状态和指标 |
| 部署任务轮询 | 5 秒 | 查询镜像部署和项目部署 |
| 配置检查 | 3 秒 | 查询待应用配置 |
| 日志任务轮询 | 5 秒 | 查询远程日志操作任务 |
| 容器日志上传 | 30 秒 | 上传 `middleware` 容器日志片段 |
| Agent 自更新检查 | 3600 秒 | 检查 Agent 版本 |

这些间隔可以通过环境变量调整：

| 环境变量 | 默认值 |
| --- | --- |
| `CLOUD_SERVER` | `http://your-server.com/api` |
| `DEVICE_ID_FILE` | `/etc/device-id` |
| `VERSION_FILE` | `/work/.version` |
| `HEARTBEAT_INTERVAL` | `5` |
| `TASK_POLL_INTERVAL` | `5` |
| `LOG_UPLOAD_INTERVAL` | `30` |
| `UPDATE_CHECK_INTERVAL` | `3600` |
| `CONFIG_CHECK_INTERVAL` | `3` |
| `LOG_TASK_POLL_INTERVAL` | `5` |
| `MIDDLEWARE_LOG_DIR` | `/opt/project-code/MiddlewareServer/localstore/logs` |

---

## 5. 设备身份是怎么生成的

这是这个 Agent 很关键的一部分，因为它决定“设备重装系统后会不会被识别成同一台设备”。

### 5.1 网络身份采集

`get_network_identity()` 会：

1. 找出物理网卡，排除 `lo`、`docker`、`veth` 等虚拟网卡。
2. 优先把默认路由对应的网卡作为主网卡。
3. 采集主 IP、主 MAC，以及所有物理网卡 MAC 列表。

### 5.2 硬件指纹优先级

`get_hardware_fingerprint()` 会按下面顺序找最稳定的硬件标识：

1. Jetson 序列号：`/proc/device-tree/serial-number`
2. Tegra 芯片 UID：`/sys/module/tegra_fuse/parameters/tegra_chip_uid`
3. SoC 序列号：`/sys/devices/soc0/serial_number`
4. `product_uuid`
5. `product_serial`
6. `board_serial`
7. 所有物理网卡 MAC 组合
8. 主 MAC
9. `/etc/machine-id`
10. 主机名

### 5.3 设备 ID 生成方式

硬件指纹拿到后，会做一次 MD5，生成类似这样的 ID：

```text
DEV-1a2b3c4d
```

这意味着：

- 只要硬件层面的稳定指纹没变，重装系统后理论上仍应识别为同一台设备。
- 如果平台侧已存在同样的硬件指纹或 MAC，注册接口会尽量复用原设备记录，而不是新建一条。

---

## 6. 这个 Agent 对外“暴露”的接口是什么

严格来说，`device-agent.py` **不对外监听 HTTP 端口**，所以它没有传统意义上的“别人来调用我的 API”。

它的“接口”主要分两类：

1. **云端接口**：Agent 主动调用云平台 API。
2. **本地运行接口**：安装、systemd、配置文件、日志文件这些运维入口。

下面重点讲第一类，也就是最核心的“Agent 如何和平台交互”。

---

## 7. Agent 会调用哪些云端 API

### 7.1 设备注册与心跳

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/devices/register/` | `POST` | 首次注册设备 |
| `/api/devices/{device_id}/heartbeat/` | `POST` | 周期性心跳上报 |
| `/api/devices/{device_id}/` | `GET` | 查询设备详情，拿数据库主键 |

#### 注册报文示例

```json
{
  "device_id": "DEV-1a2b3c4d",
  "hardware_fingerprint": "jetson_serial:xxxx",
  "hardware_fingerprint_source": "jetson_serial",
  "mac_address": "00:11:22:33:44:55",
  "mac_addresses": [
    "00:11:22:33:44:55"
  ],
  "ip_address": "192.168.31.36",
  "hostname": "jetson"
}
```

#### 心跳上报内容

心跳会带上这些信息：

- 项目版本
- Agent 版本
- FRP 配置版本
- 当前 IP 和 MAC
- 硬件指纹
- CPU / 内存 / 磁盘占用
- `middleware` 容器状态
- 本地服务健康检查结果

默认健康检查地址是：

```text
http://localhost:8088/api/metrics
```

#### 心跳返回的控制字段

云端可以通过心跳响应告诉 Agent 做一些动作，当前主循环真正处理的是：

```json
{
  "command": "none",
  "frp_update_required": false,
  "frp_disable_required": false
}
```

目前主循环实际处理的 `command` 有：

- `none`
- `update`
- `update_agent`

说明一下：

- 服务端心跳接口里保留了 `deploy` 响应格式。
- 但当前正式 `device-agent.py` 的部署主入口其实是**独立轮询 `/deployments/` 和 `/project-deployments/`**。
- 所以现在的部署链路以“任务轮询”为主，而不是“心跳直接下发 deploy 命令”。

---

### 7.2 Docker 镜像部署任务

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/deployments/?device=<pk>&status=pending` | `GET` | 查询待执行镜像部署任务 |
| `/api/deployments/{id}/update_progress/` | `POST` | 上报部署进度 |

这类任务做的是比较通用的 Docker 部署：

1. 拉镜像。
2. 停旧容器。
3. 按任务里的端口、环境变量、卷挂载、重启策略拼 `docker run`。
4. 启动新容器。
5. 检查容器是否正常运行。
6. 把版本写到 `/work/.version`。

如果任务类型是 `restart`，则只重启容器，不重新部署。

---

### 7.3 OTA 更新任务

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/updates/{id}/update_progress/` | `POST` | 上报 OTA 更新进度 |

OTA 更新由心跳返回的 `command=update` 触发，默认逻辑是：

1. 拉取 `registry:5000/middleware:<version>`。
2. 停止旧的 `middleware` 容器。
3. 用固定挂载重新启动容器。
4. 更新 `/work/.version`。

这是一个比较固定的“升级现有 middleware 容器”的流程。

---

### 7.4 项目级部署任务

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/project-deployments/?device_id=<device_id>&status=pending` | `GET` | 查询项目部署任务 |
| `/api/project-deployments/{id}/update_progress/` | `POST` | 上报项目部署进度 |
| `/api/code-packages/{id}/download/` | `GET` | 下载代码包 |

这是当前更完整、也更灵活的部署通道，支持：

- 仅使用本地已存在镜像
- 从仓库拉取 Docker 镜像
- 从平台下载代码包并解压
- 直接 `git clone` / `git pull`
- 生成独立 `.env`
- 执行宿主机部署钩子
- 启动支持 GPU、`host` 网络、设备映射、特权模式的容器

项目部署默认会把代码放到：

```text
/opt/project-code
```

并把项目配置写到：

```text
/opt/project-config/.env
```

如果代码目录下存在：

```text
MiddlewareServer/setup-browser.sh
```

Agent 会把它当作宿主机部署后钩子执行。

#### 代码包校验、运行数据与失败回滚（1.7.3）

入口 `download_and_extract_code_package(code_package_info, target_dir)` 沿用 ZIP/TAR 的原始目录层级，不剥离顶层项目目录。下载和解压使用 `target_dir` 同父目录下的私有暂存目录；完整读取归档并通过 ZIP CRC / TAR 读取与压缩尾部校验后才开始替换。校验实际下载字节数与 `Content-Length`；元数据提供精确 `size` 或 MD5/SHA-256 `checksum` 时也校验，不将四舍五入的 `size_mb` 用于校验。拒绝空归档、绝对路径、`..`、Windows 路径、链接和特殊文件。

保留挂载根目录 `target_dir` 本身，仅备份和替换其顶层条目。归档校验完成后，先将旧条目移入同文件系统备份区，再把以下原始运行数据移动到待激活目录，保留文件/目录 inode；不使用仍在运行的 SQLite 数据库副本：

- 根目录 `.env`、`localstore`、`server/db.sqlite3*`。
- 每个顶层项目目录中的 `.env`、`localstore`、`server/db.sqlite3*`，包括数据库的 WAL、SHM 和 journal 文件。

包内同名运行数据由旧数据覆盖；`config/*.yml`、模型和插件配置仍按新包更新。归档保留普通权限位及可执行位，忽略所有者和特殊权限位。暂存解压时空间不足或校验失败不改动旧目录；条目替换失败则逆序归还运行数据并恢复备份。回滚本身失败时保留暂存/备份目录，在错误中返回恢复路径，供人工检查；不继续后续容器重启步骤。

该流程没有暂停业务进程，多条目切换仍有短暂路径间隙，不是完整的并发更新或数据库事务保证。正常完成或成功回滚后清理暂存目录；空间需求包含下载归档和新代码树。验证入口是 `device-agent/tests/test_code_packages.py`，覆盖真实归档、校验失败、运行数据 inode、配置更新及替换失败回滚。

---

### 7.5 配置下发

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/devices/{device_id}/pending_config/` | `GET` | 查询待应用配置 |
| `/api/devices/{device_id}/config_result/` | `POST` | 上报配置应用结果 |

当前 Agent 内置了一套专门面向 `MiddlewareServer` 的配置应用逻辑，会自动修改三类文件：

| 本地文件 | 作用 |
| --- | --- |
| `/opt/project-code/MiddlewareServer/config/devices.yml` | 相机列表 |
| `/opt/project-code/MiddlewareServer/server/server/settings.py` | PLC / Socket 配置 |
| `/opt/project-code/MiddlewareServer/frontend/vite.config.ts` | 前端代理地址 |

应用流程是：

1. 先备份旧配置到 `/opt/config-backup/<timestamp>/`
2. 生成 / 修改配置文件
3. 重启 `middleware` 容器
4. 做一次本地访问验证
5. 成功则上报成功，失败则尝试回滚

这部分说明了一个事实：

> 当前 Agent 并不是纯通用 Agent，它已经内置了对 `MiddlewareServer` 项目结构的理解。

---

### 7.6 日志任务

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/devices/{device_id}/pending_log_tasks/` | `GET` | 拉取待执行日志任务 |
| `/api/devices/{device_id}/report_log_task/` | `POST` | 回传日志任务结果 |

当前支持的日志任务类型有：

- `list`：列出日志目录和文件
- `read`：读取单个日志文件
- `search`：按关键词搜索
- `download`：把日志打包后回传
- `journal`：读取宿主机 systemd journal 的最近日志窗口（Agent 1.7.3 起）

默认日志目录：

```text
/opt/project-code/MiddlewareServer/localstore/logs
```

除此之外，Agent 还会定时上传 `middleware` 容器日志片段，属于另一条“主动上报”链路。

Agent 1.7.3 领取日志任务时发送 `limit=1`，配合支持该参数的平台每轮只领取一项，避免批量日志采集和结果上报长时间占用主循环。平台应先升级以支持该参数；旧 Agent 不传参数时仍默认每轮最多领取五项。

#### journal 任务接口（1.7.3）

沿用上面的任务拉取和结果回传接口，不增加 Agent 监听端口。平台负责创建任务和访问权限；Agent 只执行固定日志采集能力。拉取响应中的任务示例：

```json
{
  "task_id": "example-journal-task",
  "task_type": "journal",
  "params": {
    "source": "agent",
    "start_time": "2026-11-18T08:00:00+08:00",
    "end_time": "2026-11-18T09:00:00+08:00",
    "lines": 500,
    "level": "INFO",
    "keyword": "heartbeat"
  }
}
```

| 参数 | 约束和含义 |
| --- | --- |
| `source` | 必填，严格限定 `agent`、`frpc`、`docker`、`system` |
| `start_time` / `end_time` | 可选，ISO 日期时间，必须有秒；可带 1-6 位小数、`Z` 或 `+08:00` 等时区。无时区时按设备本地时区解释，再转 UTC。起始不得晚于结束 |
| `lines` | 正整数，默认 500，超过 2000 按 2000；不接受 0、负数、布尔或字符串 |
| `level` | 可选，空字符串或省略表示全部；非空值严格限定 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`；精确匹配 journal PRIORITY，依次为 7、6、4、3、2，不按消息文本识别级别，也不自动包含更严重级别 |
| `keyword` | 可选，最多 1024 字符，区分大小写的字面子串；只在时间、级别过滤后的最近 `lines` 条窗口内匹配，不扫描窗口以外的历史日志 |

来源固定映射：`agent` -> `device-agent.service`；`frpc` -> 现有 `FRP_SERVICE_NAME` 对应的 `.service`（当前 `frpc.service`）；`docker` -> `docker.service`；`system` 不指定 unit。`docker` 是 Docker 守护进程日志，业务容器日志仍使用既有上传链路。

不接受自定义 unit、文件路径、命令、额外参数、相对时间或 `@epoch` 时间表达式。子进程只用参数数组执行 `systemctl show` 和 `journalctl`，不使用 shell。时间和级别先校验再组装参数，关键词不会传入命令。unit 存在性检查和 journal 采集共享 15 秒截止时间，超时终止并回收子进程。

stdout/stderr 增量读取，合计最多保留 512 KiB，达到上限终止采集并标记 `truncated`；UTF-8 内容不超过 512 KiB、最多 2000 行。先从最新日志开始采集，再按时间顺序返回，达到字节上限时保留最新窗口。`truncated=false` 仅表示请求窗口完整，窗口前仍可能存在更早日志。

采集成功的 helper 返回以下字段；轮询器将其放进 `report_log_task` 的 `result`，并设置 `status=completed`：

```json
{
  "content": "2026-11-18T08:30:00+0800 device agent[123]: heartbeat sent",
  "returned_lines": 1,
  "truncated": false,
  "source": "agent",
  "collected_at": "2026-11-18T01:00:01+00:00"
}
```

有效 journal 中没有匹配日志时成功返回空 `content`、`returned_lines=0`。没有 journal 文件/工具、journal 权限不足、服务不存在、systemd 不可用、执行失败和超时分别给出可操作的 `{"error": "..."}`。轮询器沿用原失败契约：`status=failed`、`result={}`、`error_message` 为该错误说明。journal 依赖 Linux/systemd 和 Agent 用户的 journal 读取权限（通常 root 或 `systemd-journal` 组）；不会为采集任务自动启停服务或修改权限。

#### 既有业务日志任务的边界

`list/read/search/download` 的原参数和结果字段保留，路径以 `MIDDLEWARE_LOG_DIR` 为根。日期必须为有效日历日期 `YYYY-MM-DD`，文件只能是 basename；拒绝绝对路径、斜杠、反斜杠、盘符/流名称和目录穿越。解析日期目录和文件的 symlink 后检查包含关系，逃出日志根/日期目录的条目不列出、不搜索，直接读取/下载时报错。只读取普通文件。

| 任务 | 上限与结果语义 |
| --- | --- |
| `list` | 保留最近 30 个日期；每任务目录枚举总计最多 4096 条、名称合计 512 KiB、5 秒，超限返回错误并要求缩小日期范围 |
| `read` | 最多 2000 行、512 KiB 文本；兼容原 `lines=0`/省略，现表示有界读取上限。扫描最多 16 MiB/5 秒，`tail=true` 对大文件从末尾 16 MiB 开始。新增 `truncated` 和 `total_lines_exact`；未完整扫描时 `total_lines` 是扫描窗口计数，不是全文件总数 |
| `search` | 保留原最近 7 天、级别和大小写规则；最多返回 500 条、512 KiB 文本；所有文件合计扫描最多 16 MiB/5 秒。超限返回 `truncated=true`，此时 `total_matches` 是已扫描匹配计数，不是全历史总数 |
| `download` | 最多 100 个文件；总源文件及 ZIP 各最多 16 MiB，增量打包，读取期间继续检查增长和 5 秒期限；ZIP 关闭后再次检查大小，随后才转 base64。超限返回错误，不返回残缺 ZIP。base64 体积约为 ZIP 的 4/3 |

超长单行仅保留有界前缀并标记截断；不会把整文件或无界子进程输出一次性载入内存。扫描预算针对常规本地日志文件，不为阻塞的远程文件系统提供硬实时保证。

#### 测试与 Linux 现场验证

在配置好的项目 Python 环境中，从 DeviceManagementPlatform 根目录运行（继承父工程 Poetry 环境时可加 `poetry run`）：

```bash
python -m unittest discover -s device-agent/tests -v
python -m py_compile device-agent/device-agent.py device-agent/tests/test_log_tasks.py
```

测试使用 `unittest` 和临时业务日志；通过 importlib 隔离导入，mock HTTP、metrics、进程边界及 logging，Windows 上不会打开 `/var/log/device-agent.log`，也不依赖 requests/psutil 已安装。真实 symlink 用例在系统不允许创建链接时跳过；解析后包含关系另有可跨平台执行的测试。

Linux/systemd 设备现场应以 Agent 服务的实际运行用户验证读取权限，先做只读检查：

```bash
systemctl show --property=LoadState --value device-agent.service frpc.service docker.service
journalctl --no-pager --output=short-iso --reverse --lines=20 --unit=device-agent.service
journalctl --no-pager --output=short-iso --reverse --lines=20 --unit=frpc.service
journalctl --no-pager --output=short-iso --reverse --lines=20 --unit=docker.service
journalctl --no-pager --output=short-iso --reverse --lines=20
```

通过平台任务链路分别提交四个 `source`，核对 `report_log_task` 的来源、UTC 时间和行数；再验证 ISO 时间窗口、级别、关键词、无匹配窗口、大量日志截断及错误报告。缺服务/权限/存储失败可用单元测试或隔离测试机验证，不在生产机停服务或删除 journal。验证前后检查心跳与 FRP 状态；本地单元测试不代表这些现场检查已经完成。

---

### 7.7 FRP 管理

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/devices/{device_id}/report_frp_status/` | `POST` | 上报 FRP 状态 |
| `/api/devices/{device_id}/fetch_frp_config/` | `GET` | 预留的主动拉取 FRP 配置接口 |

当前实际 FRP 配置获取方式有两种：

1. 注册成功时，服务端直接在返回体里带 `frp_config`
2. 心跳响应里返回 `frp_update_required` 和 `frp_config`

Agent 收到后会：

1. 确保本地存在 `frpc` 二进制。
2. 生成 `/etc/frp/frpc.ini`。
3. 确保 `frpc` 的 `systemd` 服务存在。
4. 重启 `frpc` 服务。
5. 把本地 FRP 配置版本写到 `/etc/frp/.version`。
6. 向云端上报 `connected / disconnected / error` 状态。

如果云端要求停用 FRP，则会停止并禁用 `frpc` 服务。

当前服务端默认下发两条隧道：

| 隧道 | 本地目标 | 远端端口规则 | 用途 |
| --- | --- | --- | --- |
| `ssh` | `127.0.0.1:22` | `frp_ssh_port = N` | 远程 SSH 登录设备 |
| `web` | `127.0.0.1:8088` | `frp_web_port = N + 1` | 访问设备上的 MiddlewareServer Web 服务 |

这两条隧道共用平台 FRP 端口池。每台启用 FRP 的设备固定占用两个相邻端口，服务端会保证端口对完整落在端口池范围内。

注意：

- `fetch_frp_config` 在服务端已经预留。
- 但当前 `device-agent.py` 主循环并没有主动调用它。
- 现有正式链路仍然是“注册/心跳返回中顺带下发 FRP 配置”。

---

### 7.8 Agent 自更新

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/agent/version/` | `GET` | 查询最新 Agent 版本 |
| `/api/agent/download/` | `GET` | 下载最新 Agent 脚本 |

自更新流程很直接：

1. 周期性查询版本。
2. 如果服务端版本高于本地 `AGENT_VERSION`，下载新脚本。
3. 备份当前 `/opt/device-agent/agent.py`。
4. 覆盖写入新版本。
5. 重启 `device-agent` 服务。

服务端也可以通过心跳响应中的 `command=update_agent` 主动触发这件事。

---

## 8. 本地落地了哪些文件和服务

### 8.1 关键文件

| 路径 | 用途 |
| --- | --- |
| `/opt/device-agent/agent.py` | 当前运行中的 Agent 脚本 |
| `/etc/device-id` | 本地缓存设备 ID |
| `/work/.version` | 设备当前项目版本 |
| `/var/log/device-agent.log` | Agent 自身日志 |
| `/etc/frp/frpc.ini` | 本地 FRP 客户端配置 |
| `/etc/frp/.version` | 本地 FRP 配置版本号 |
| `/opt/project-code` | 项目代码落地目录 |
| `/opt/project-config/.env` | 项目环境变量文件 |
| `/opt/config-backup/<timestamp>/` | 配置修改前的备份 |

### 8.2 关键服务与容器

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `device-agent` | `systemd` 服务 | Agent 主进程 |
| `frpc` | `systemd` 服务 | FRP 客户端 |
| `middleware` | Docker 容器 | 当前默认被监控、被重启、被上传日志的业务容器 |

---

## 9. 预留了哪些扩展点

如果后面要继续扩展这套 Agent，当前代码里已经留出了几个比较自然的接入点。

### 9.1 心跳返回命令扩展

当前 `main()` 已经有“拿到心跳响应后执行动作”的框架。

适合扩展的场景：

- 新增设备侧轻量控制命令
- 不想单独再开一个轮询接口的快速功能

建议做法：

- 在服务端心跳响应里增加字段
- 在 `main()` 的 `cmd_type` 分支里增加处理逻辑

### 9.2 新的周期性任务

主循环已经是标准“多个定时器并行轮询”的结构。

适合扩展的场景：

- 新增远程诊断任务
- 新增证书同步
- 新增设备文件同步

建议做法：

- 新增一个 `last_xxx_check`
- 加一个独立的 `poll_xxx()` 函数
- 用单独环境变量控制轮询间隔

### 9.3 系统任务接口

服务端已经预留了这两条接口：

- `/api/devices/{device_id}/pending_system_tasks/`
- `/api/devices/{device_id}/report_system_task/`

当前 `device-agent.py` 还**没有真正把这组接口接进主循环**，所以这是一个很明显的预留扩展点。

适合承载的能力：

- 修改主机名
- 调整时区
- 安装系统包
- 设备重启
- 网络切换

### 9.4 FRP 隧道扩展

当前 `render_frpc_ini()` 会按服务端下发的 `tunnels` 字典生成多条隧道，默认包含 SSH 和 Web。

以后可以很自然地扩展：

- VNC
- 自定义 TCP / UDP 隧道

### 9.5 日志任务扩展

`poll_and_execute_log_tasks()` 现在是按 `task_type` 分发的。

如果要新增能力，比如：

- 下载某个目录
- 获取最近 N 分钟日志
- 导出容器状态快照

只需要：

1. 新增一个任务类型
2. 增加对应处理函数
3. 在结果回传时保持统一格式

### 9.6 配置下发扩展

当前 `apply_middleware_config()` 明显是为 `MiddlewareServer` 写的。

如果后面要支持别的项目，建议不要继续把新逻辑硬塞在这里，而是改成：

- 按项目类型分发
- 每个项目一套独立配置适配器

这样能避免 Agent 越长越重、越改越难维护。

---

## 10. 设计上需要特别理解的点

### 10.1 这是“拉模型”不是“推模型”

设备侧不开放一个给平台回调的 HTTP 服务，而是：

- 设备主动发心跳
- 设备主动轮询任务
- 设备主动上报执行结果

这样做的好处是：

- 设备部署简单
- 不依赖设备侧开放公网入口
- 更适合局域网、NAT、移动网络、Jetson 边缘设备

### 10.2 当前 Agent 既通用又不完全通用

它有一部分能力是通用的：

- 注册
- 心跳
- Docker 部署
- OTA
- FRP
- 日志

但也有一部分是项目耦合的：

- `MiddlewareServer` 的配置文件修改
- 默认容器名 `middleware`
- 默认日志目录
- 本地验证地址 `http://localhost:8088/`

所以后续如果希望把它发展成真正的平台级 Agent，最好逐步把项目耦合能力做成插件化或适配器化。

### 10.3 目前存在新旧两套任务风格并存

从代码上看，现在同时存在：

- `bootstrap-agent.py` 风格的“注册后等部署命令”
- `device-agent.py` 风格的“心跳 + 多路轮询”

因此阅读时如果看到两个相似接口，不一定是重复错误，也可能是新旧兼容痕迹。

---

## 11. 排查问题时先看哪里

### 11.1 看 Agent 是否正常启动

```bash
sudo systemctl status device-agent
sudo journalctl -u device-agent -n 100
```

### 11.2 看 Python 依赖是否齐全

```bash
python3 -c "import requests, psutil, yaml"
```

### 11.3 看设备 ID 是否稳定

```bash
cat /etc/device-id
```

如果要进一步排查身份识别问题，重点看：

- 是否能读取 Jetson 硬件序列号
- 物理网卡 MAC 是否变化
- 平台侧是否已经存在同硬件指纹记录

### 11.4 看 Docker 和业务容器状态

```bash
docker ps -a
docker logs --tail 100 middleware
```

### 11.5 看 FRP 状态

```bash
sudo systemctl status frpc
cat /etc/frp/frpc.ini
cat /etc/frp/.version
```

---

## 12. 给后续维护者的结论

如果你是第一次接手这部分代码，可以先记住下面这几句：

1. 真正在线上跑的是 `device-agent.py`，不是目录里的旧 `install.sh`。
2. 它不是服务端 API，而是设备侧常驻客户端。
3. 任务执行以“主动轮询”为主，心跳只是其中一条控制通道。
4. FRP、部署、日志、配置、Agent 更新都已经接进同一个主循环。
5. 当前它对 `MiddlewareServer` 有明显项目耦合，扩展时最好做分层，不要继续硬写死。

如果后面要继续扩展能力，建议优先沿着这几条线走：

- 在主循环里增加新的独立轮询器
- 把项目相关配置逻辑抽成适配层
- 利用已预留的 `pending_system_tasks / report_system_task`
- 保持所有新能力都具备“轮询获取任务 + 明确回传结果”的闭环

