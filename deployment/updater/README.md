# 平台在线更新

管理员在左侧打开「平台设置」查看当前版本、最近检查时间、发布说明和执行进度。发现新版后，标题旁的标签会变为橙色。服务器每五分钟查询 GitHub Releases，也可以点击「检查更新」。

## 发布

推送测试通过的代码和一个新的正式版本标签，例如 `v1.8.0`。使用附注标签时，把更新说明写在标签消息正文。GitHub Actions 构建 Linux amd64 镜像并发布 GitHub Release。服务器使用 Release 的镜像包，检查 GitHub API 提供的 SHA-256 摘要后再加载。

## 安装

全新 Linux 主机安装 Docker Compose v2 后，在 `deployment/deploy-simple` 运行 `bash deploy.sh 8081`。命令保留已有 `.env`，启用宿主机更新服务，运行最新正式版。开发时可用 `DMP_SOURCE_BUILD=1 bash deploy.sh 8081` 从源码构建。

已有简化版部署先执行 `sudo bash deployment/updater/install.sh <已有 Compose 目录> <已有项目名>`。对照 `docker compose ls` 核对目录和项目名，然后执行 `sudo python3 /opt/device-platform-updater/apply.py /var/lib/device-platform-updater --bootstrap v1.8.0`，版本填写最新正式版。

## 切换和恢复

更新器先拉取镜像并在 SQLite 副本上预检迁移。切换期间暂停入站业务请求，停写后备份数据库，只重建 Compose 的 `app`。新版通过 Nginx 到 Django 的就绪检查后恢复流量，继续使用原 SQLite 与上传文件数据卷。FRP、Registry 和现场业务容器独立运行。

若切换失败，更新器在放行写入前恢复之前的数据库和镜像。查看 `sudo journalctl -u device-platform-updater` 可定位故障。若状态显示需要人工恢复，排除故障后运行 `sudo python3 /opt/device-platform-updater/apply.py /var/lib/device-platform-updater --retry-recovery`。备份位于 `/var/lib/device-platform-updater/backups/`，仅 root 可读。管理已接入的 Compose 项目时，将 `/var/lib/device-platform-updater/release-compose.json` 放在最后一个 `-f`。

如果服务器下载镜像慢，可以在网络较快的机器下载 Release 镜像包，核对 GitHub API 提供的 SHA-256 后传到宿主机并运行 `docker load -i device-platform-linux-amd64.tar.gz`。下次点击更新时，更新器重新核对本地镜像 ID 与发布记录，一致才跳过下载。准备阶段平台继续服务。

平台更新接口使用现有 Token 登录鉴权。`GET /api/platform/release/` 返回当前版本、新版和任务状态，`?refresh=true` 立即检查。管理员向 `POST /api/platform/updates/` 提交 `{"version":"v1.8.0"}`，成功返回 `202`。版本变化或存在进行中任务返回 `409`，更新服务或 GitHub 不可用返回 `503`。
