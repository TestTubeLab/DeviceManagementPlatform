# 系统日志

左侧菜单在“FRP管理”下方提供“系统日志”。所有已登录用户均可查询，后台同时校验登录权限。

## 页面与数据来源

“平台日志”查询操作审计与后台请求异常，支持时间、级别、模块、操作人、结果及关键词筛选。平台从本功能启用后开始记录，不补造历史操作记录。

- 同步操作记录成功或失败；部署、配置等异步操作先记录“已下发”，设备回传终态后记录执行结果。
- 登录、设备/项目/代码包/镜像维护、部署、配置及 FRP 控制属于审计范围。普通查询、心跳及日志轮询不逐次记录。
- 不保存完整请求或响应。异常详情仅保存堆栈位置和脱敏错误信息，不记录局部变量、密码和令牌。
- 审计存储失败写入标准错误日志，不能将已完成的业务操作变成失败。

“设备日志”按设备和来源查看：

| 来源 | 获取方式 | 设备离线时 |
| --- | --- | --- |
| 容器 | 平台已接收的容器日志，时间为平台接收时间 | 可查看已有记录 |
| 业务文件 | 原有日志任务接口，设备读取业务日志目录 | 不创建新查询 |
| Agent / FRP / Docker 服务 | Agent 只读查询对应 systemd journal | 不创建新查询 |
| 系统 | Agent 只读查询系统 journal | 不创建新查询 |

容器日志仍按现有 Agent 周期上传，并非连续实时流。业务文件和 journal 的保存范围取决于设备现有日志及 journal 留存设置。

## API

所有 Web 查询均需要 `Authorization: Token <登录取得的令牌>`。

### 平台日志

`GET /api/system-logs/`：返回 `{count, next, previous, results}`。

参数：`start_time`、`end_time`（ISO 8601）、`level`、`module`、`actor`、`result`、`device_id`、`search`、`page`、`page_size`。开始时间不得晚于结束时间；默认每页 50 条，最多 100 条，时间及 ID 倒序。

模块：`auth`、`device`、`project`、`image`、`package`、`deployment`、`frp`、`system`。结果：`submitted`、`success`、`failed`。

记录字段：`id`、`timestamp`、`level`、`module`、`action`、`actor`、`target`、`result`、`message`、`detail`、`device_id`、`task_id`。目标和操作人为快照，不因原对象删除而丢失。`GET /api/system-logs/{id}/` 读取详情。接口不开放创建、修改或删除。

`GET /api/logs/` 保留原有设备日志字段，补充 `device_id`、`device_name`；支持设备、级别、时间、关键词和分页查询。旧容器日志接口保持可用。

### 服务日志任务

`POST /api/devices/{device_id}/service_logs/`：

```json
{
  "source": "agent",
  "lines": 500,
  "level": "ERROR",
  "keyword": "连接"
}
```

`source` 必填，仅允许 `agent`、`frpc`、`docker`、`system`。可选 `start_time`、`end_time`，默认从一小时前开始；`lines` 默认 500，范围 1–2000。`level` 为 DEBUG/INFO/WARNING/ERROR/CRITICAL；关键词匹配当前有界结果窗口。

成功返回 `{task_id, message}`，继续通过原有 `GET /api/devices/{device_id}/log_task_result/?task_id=...` 查询。任务类型新增 `journal`，结果包括 `content`、`returned_lines`、`truncated`、`source`、`collected_at`。参数无效返回 400；设备离线或 Agent 低于 1.7.3 返回 409；未登录返回 401/403；任务不存在返回 404。

Agent 沿用 `pending_log_tasks/` 领取及 `report_log_task/` 上报，不更改已有通信方式。领取接口接受可选 `limit=1–5`，旧客户端默认 5；新版 Agent 每次请求 1 项，减少日志查询对主循环心跳的阻塞。仅实际领取任务变为 processing，重复终态上报不会覆盖第一次结果。journal 任务 120 秒后失效，设备晚到的结果不能恢复已失效任务。前端最多等待 60 秒，离开页面或切换设备后停止等待。

业务文件任务在服务器也校验日期和文件名，保护尚未升级的旧 Agent。日期必须是有效的 `YYYY-MM-DD`，文件名不能包含路径，每次下载最多 100 个文件；读取最多 2000 行，旧调用的 `lines=0` 转为 2000 行。Agent 1.7.3 还会校验实际路径和符号链接边界。

## 保留与部署

- 新增平台日志默认保留 90 天，通过环境变量 `SYSTEM_LOG_RETENTION_DAYS` 调整。设备日志任务已完成结果保留 7 天；设备文件和现有容器日志留存策略独立。
- 清理由日志写入触发，每个进程最多每小时一次，每类每批 1000 条、每次最多 5 批。无写入时不会触发清理，也不新增定时服务。
- 迁移 `0013` 新建日志表，`0014` 将原 `Device.config.log_tasks` 转存任务表，保留任务 ID、状态及结果，移除配置中的旧任务内容。
- 上线前备份平台数据库，暂停平台应用写入后执行迁移，再启动新版应用。不要在旧应用继续写配置时单独执行数据迁移。原设备及项目数据不做版本回滚。
- 后台和 Agent 发布版本同步为 1.7.3。先更新平台，再升级一台测试设备；旧 Agent 继续执行容器/业务日志任务，新服务日志在升级后才可使用。
- 回滚应用前，在暂停写入状态下执行 `python manage.py migrate management 0013` 将任务恢复至原配置，再切换旧应用。新增审计表可保留供恢复；不要通过删除数据卷回滚。

## 开发验证

使用仓库的 Conda 环境与 requirements：

```powershell
conda env create -f environment.yml
conda run -n device-mgmt python -m pip install -r server/requirements.txt
cd server
conda run -n device-mgmt python manage.py test management --noinput
conda run -n device-mgmt python manage.py makemigrations --check --dry-run
```

前端在 `frontend/` 执行 `npm ci`、`npm run build`。Agent 测试和 Linux 实机验证见 `device-agent/README.md`。
