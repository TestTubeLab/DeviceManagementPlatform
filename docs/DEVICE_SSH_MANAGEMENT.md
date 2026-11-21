# 设备 SSH 管理

## 操作与权限

在「设备详情 → 远程连接 → SSH 管理」读取设备报告。仅持 Django Staff 身份且拥有 `management.manage_device_ssh` 权限的账号可以读写；超级管理员已有该权限。未纳管或超过 45 秒没有专用心跳的设备不接受写任务。页面只显示公钥、指纹和执行记录。

1. 从运维电脑导入单行 Ed25519 公钥，或在 HTTPS 页面生成并下载无口令的 OpenSSH 私钥。后者只在浏览器本地生成；确认安全保存文件、限制本机文件权限，再添加公钥。平台不能找回私钥。
2. 确认一条不依赖本设备 FRP 的恢复入口，例如现场终端；同时确认旧 FRP SSH 已限制来源。在目标公钥旁选择「启用仅公钥」。此步重启目标设备的 frpc；该设备正在使用的 SSH、Web 会话可能断开，但 Web 映射不变。
3. 在 5 分钟内，从独立终端通过原 FRP SSH 外部端口新建公钥会话。登录账号以本页显示为准，首次连接要通过可信来源校验主机指纹。本页监测到专用 SSH 服务接受该账号与公钥后，点击「确认已通过 FRP 登录」。Agent 无法仅凭 sshd 日志区分本机用户和经过 frpc 的登录；操作者须确认走的确实是原 FRP 路径。
4. 换钥时先添加，再选择新公钥「开始试登」，登录并确认后才撤旧钥。Agent 不允许撤销最后一把已经验证的公钥。已建立的 SSH 会话不会因为撤钥而被强制断开。

现场 `22` 的 sshd、主机密钥、账户密码和用户自己的 `authorized_keys` 不变。“现场密码策略”是对纳管账号做的配置探测，不代表每个 `Match` 来源、PAM 条件或所有账号都允许密码。远程入口独立监听 `127.0.0.1:2222`，只接受指定非 root 账号的公钥，关闭 TCP/Agent/X11 等转发；网页继续使用现有 Web 映射。此功能只约束纳管的 frpc，不替代云防火墙和 FRP 白名单，不能覆盖其他隧道服务或宿主机入侵。

## 平台内置 TLS

同一个平台容器中的 Nginx 提供 TLS 管理入口，无需域名、外部 CA 或独立代理。功能默认关闭。启用后管理网页及运维认证使用 HTTPS，旧 Agent 的普通 HTTP 心跳仍可访问。平台登录按来源地址限制到每分钟 8 次，允许短时突发 5 次。启用前修改已知默认管理员密码，退役曾经通过明文传输的运维 Token，并在部署前复查访问端口和入口健康。

1. 在平台主机使用可信控制台运行 `bash setup-ssh-management-tls.sh <设备可访问的IPv4地址或DNS名称>`。重复执行会复用 CA，仅在服务证书无效、临近到期或地址不匹配时续签。CA 私钥留在平台主机，设备和浏览器只接收经核对指纹的公开 CA。
2. 将 [内置 TLS 覆盖文件](../deployment/deploy-simple/docker-compose.ssh-tls.yml) 纳入该平台 Compose 项目的配置。在已经接入更新器的环境，把相同配置纳入现有 `docker-compose.override.yml`，使平台设置页发版时持续生效。使用镜像内 Nginx 配置；从上一套试点切换时，将旧的 `/etc/nginx/nginx.conf` 挂载从覆盖文件中移除，保留证书和数据挂载。生产更新沿用 [更新器文档](../deployment/updater/README.md)。
3. 配置 `DEVICE_SSH_PUBLIC_URL` 为设备长期可访问的 HTTPS API 基地址，比如 `https://192.0.2.10:8443/api`。默认绑定回环地址，适合在运维电脑转发访问；要让设备直接连接，设置 `DMP_SSH_TLS_BIND` 为经过核对的主机接口地址，并在网络层限制管理入口的访问范围。设备和运维电脑均需验证证书及地址。临时 SSH 转发可用于测试，不能承担设备长期管理。
4. 验证有效入口后再签发凭据。浏览器在「设备详情 → 远程连接 → SSH 管理」下载的 JSON 只在当前操作中可重新下载。数据库只保存凭据摘要，纳管文件不得进入源码、聊天、日志、公共下载或备份共享。

## 设备首次纳管

Jetson 使用 systemd、OpenSSH、iproute2、Python 和 Agent 已有的 `requests`。部署流程或本机控制台须有授权的 root 权限。先确认目标 Agent 基线、目标设备 ID、现有 FRP 入口和视觉服务健康，备份已运行的 Agent。通过可信发布渠道一起交付兼容的 `device-agent.py` 和 `ssh_management.py`，将它们分别安装为 `/opt/device-agent/agent.py` 和 `/opt/device-agent/ssh_management.py`，所有者为 root，普通账号不可写。

```bash
python3 /opt/device-agent/ssh_management.py enroll ca.crt < enrollment.json
systemctl restart device-agent
```

纳管命令核对本机设备 ID、账号、证书和逐设备凭据，仅写入本机纳管配置。核对页面首次专用心跳后，清理暂存的凭据文件。首次安装时仅在已经实际登录过独立恢复入口、且旧远程 SSH 入口的来源受限时追加 `--recovery-verified`。网页正常添加公钥和查看状态通过 Agent 管理通道执行。仅公钥服务对认证设定 3 次尝试和 20 秒登录时限，上线验收还应检查原 SSH 和 Web 映射。

可信控制台可用 `python manage.py provision_device_ssh DEVICE_ID` 轮换设备凭据，或用 `--revoke` 撤销。轮换后从已有可信特权入口更新设备纳管凭据并重启 Agent，保留已生效策略和公钥。未纳管设备继续使用现有更新流程。已纳管设备拒绝旧 HTTP 单脚本更新，通过可信渠道更新完整 Agent。

## 回退与验证

运行 `bash deployment/deploy-simple/test-ssh-tls.sh <待验收镜像>` 验证内置 TLS、HTTP 兼容、登录限速、纳管和公钥下发回执。脚本使用隔离数据和证书，发布流水线通过该检查后才生成 Release。

首次尝试保存现有 frpc 配置，并由独立 systemd 定时器设置 5 分钟截止时间；即使平台断线或 Agent 重启也能尝试回退。未确认时只恢复 SSH 映射的原本地端口，保留合法的其他映射变化；FRP 已由平台停用时不能因回退而重新启动。若任务中途失败，看设备端 `device-agent-ssh-rollback.service` 和 `frpc.service` 的日志，使用独立恢复入口处理。确认后 Agent 锁定本机目标，平台收到可信回执后也锁定下发目标；下线或撤销凭据不会自动切回 22。不得删除策略文件、手动恢复旧 Agent 或移除 SSH 服务来当作回退。

隔离环境应实测公钥成功、FRP 密码失败、现场密码成功、旧钥撤销、Agent 重启、frpc 重连和等待超时自动回退；验证其他映射未改变、主机指纹一致、平台及视觉业务正常。真实测试前不得对现网开启。浏览器导出校验可用 `ssh-keygen -y -f <下载文件>`，与表单中的公钥对照。测试文件只用于隔离 QA，验证后删除。

## 接口

- 平台 HTTPS：`GET /api/devices/{device_id}/ssh-management/` 返回设备与签发状态。`POST .../enrollment/` 接受非 root 的 `account` 和 `independent_recovery_verified: false`，返回 201 和设备纳管配置。设备本地单独核验恢复入口。
- SSH 任务：`POST /api/devices/{device_id}/ssh-management/tasks/`。操作限 `add_key`、`activate`、`verify_key`、`confirm`、`remove_key`。添加只接受 `public_key`，其余用 `fingerprint`。激活与确认还要求操作者明确核验。创建返回 201，状态不允许时返回 409。
- Agent HTTPS：`POST /api/agent/ssh-management/{device_id}/poll/` 上报限字段状态并领取最多一项，`POST .../receipt/` 提交回执。使用逐设备 Bearer 凭据，不与旧匿名任务接口混用。任务认领后不自动重投，回执可幂等补发，超期后以设备状态为准核实实际执行结果。
