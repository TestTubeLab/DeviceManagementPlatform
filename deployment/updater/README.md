# 平台在线更新

管理员在左侧打开「平台设置」查看当前版本、最近检查时间、发布说明和执行进度。发现新版后，标题旁的标签会变为橙色。服务器每五分钟查询 GitHub Releases，也可以点击「检查更新」。

## 发布

推送测试通过的代码和一个新的正式版本标签，例如 `v1.8.0`。使用附注标签时，把更新说明写在标签消息正文。GitHub Actions 构建 Linux amd64 镜像并发布 GitHub Release。服务器使用 Release 的镜像包，检查 GitHub API 提供的 SHA-256 摘要后再加载。

镜像包从 GitHub Release 下载时固定使用 HTTPS 与 HTTP/1.1，并对传输错误进行有限重试和断点续传。下载完成后仍必须同时通过归档大小、SHA-256、加载后的镜像标签和镜像 ID 校验；未通过校验的部分文件不会进入 Docker。

每个正式版镜像同时包含该版本的宿主机更新器源码和版本标记。更新器只从已通过镜像 ID 校验的镜像提取源码，检查文件、版本和 Python 语法；应用切换并通过健康检查后才替换宿主机更新器文件，并由常驻服务原位重新加载。切换失败时会恢复旧应用和旧更新器文件。该过程属于同一个平台更新任务，不需要单独上传或手工替换更新器。

## 安装

全新 Linux 主机安装 Docker Compose v2 后，在 `deployment/deploy-simple` 运行 `bash deploy.sh 8081`。命令保留已有 `.env`，启用宿主机更新服务，运行最新正式版。开发时可用 `DMP_SOURCE_BUILD=1 bash deploy.sh 8081` 从源码构建。

已有简化版部署先执行 `sudo bash deployment/updater/install.sh <已有 Compose 目录> <已有项目名>`。对照 `docker compose ls` 核对目录和项目名，然后执行 `sudo python3 /opt/device-platform-updater/apply.py /var/lib/device-platform-updater --bootstrap v1.8.0`，版本填写最新正式版。

现有主机首次启用“随 Release 同步宿主机更新器”时，需要在没有排队更新或未完成事务的前提下，将 `deployment/updater/install.sh` 安装的版本更新一次，并重启 `device-platform-updater.service`。这只重启宿主机更新守护进程，不重启平台容器或修改数据卷；完成后后续版本均由平台内更新任务同步更新器。

## 切换和恢复

更新器先拉取镜像并在 SQLite 副本上预检迁移。切换期间暂停入站业务请求，停写后备份数据库，只重建 Compose 的 `app`。新版通过 Nginx 到 Django 的就绪检查后恢复流量，继续使用原 SQLite 与上传文件数据卷。FRP、Registry 和现场业务容器独立运行。

若切换失败，更新器在放行写入前恢复之前的数据库和镜像。查看 `sudo journalctl -u device-platform-updater` 可定位故障。若状态显示需要人工恢复，排除故障后运行 `sudo python3 /opt/device-platform-updater/apply.py /var/lib/device-platform-updater --retry-recovery`。备份位于 `/var/lib/device-platform-updater/backups/`，仅 root 可读。管理已接入的 Compose 项目时，将 `/var/lib/device-platform-updater/release-compose.json` 放在最后一个 `-f`。

## 磁盘占用与保留

更新成功或失败后已完成旧版回滚时，更新器只保留最近一次可回滚版本的 SQLite 快照和对应旧镜像标签。更早的更新快照、更新器生成的过期 `device-platform-rollback:*` 标签，以及本平台仓库中不再保留的旧版本镜像标签会被逐项清理。仅清理更新器 UUID 任务目录和本平台明确匹配的镜像标签，不运行全局 `docker image prune`，不清理其他项目镜像、容器或数据卷。清理失败会记入宿主机更新服务日志，不会把已健康运行的新版本标记为失败。

清理只会在新版本健康检查通过，或旧版恢复并通过健康检查后进行；升级/回滚未完成时，恢复所需快照和镜像不会被清理。`/app/media` 媒体卷不会复制或删除。一次更新的稳定备份占用约为当前 SQLite 数据库快照大小；切换期间还需要临时空间容纳新镜像归档/镜像及新数据库快照。若单份 SQLite 数据库本身很大，保留一份仍会占用相应空间，应在更新前检查宿主机磁盘余量。

日常发布必须通过「平台设置 → 检查更新 → 更新」完成。不要把手工下载、上传 Release 包或在服务器执行 `docker load` 当作常规更新流程。只有用户明确要求处理已确认的 GitHub 下载链路故障时，才可将经官方 Release 元数据 SHA-256 校验的包作为临时镜像缓存；之后仍须由平台内更新任务完成切换和健康检查。下载期间现有平台继续服务。

平台更新接口使用现有 Token 登录鉴权。`GET /api/platform/release/` 返回当前版本、新版和任务状态，`?refresh=true` 立即检查。管理员向 `POST /api/platform/updates/` 提交 `{"version":"v1.8.0"}`，成功返回 `202`。版本变化或存在进行中任务返回 `409`，更新服务或 GitHub 不可用返回 `503`。
