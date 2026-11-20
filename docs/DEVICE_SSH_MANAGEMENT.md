# 设备 SSH 管理

## 操作与权限

在「设备详情 → 远程连接 → SSH 管理」读取设备报告。仅持 Django Staff 身份且拥有 `management.manage_device_ssh` 权限的账号可以读写；超级管理员已有该权限。未纳管或超过 45 秒没有专用心跳的设备不接受写任务。页面只显示公钥、指纹和执行记录。

1. 从运维电脑导入单行 Ed25519 公钥，或在 HTTPS 页面生成并下载无口令的 OpenSSH 私钥。后者只在浏览器本地生成；确认安全保存文件、限制本机文件权限，再添加公钥。平台不能找回私钥。
2. 确认一条不依赖本设备 FRP 的恢复入口，例如现场终端；同时确认旧 FRP SSH 已限制来源。在目标公钥旁选择「启用仅公钥」。此步重启目标设备的 frpc；该设备正在使用的 SSH、Web 会话可能断开，但 Web 映射不变。
3. 在 5 分钟内，从独立终端通过原 FRP SSH 外部端口新建公钥会话。登录账号以本页显示为准，首次连接要通过可信来源校验主机指纹。本页监测到专用 SSH 服务接受该账号与公钥后，点击「确认已通过 FRP 登录」。Agent 无法仅凭 sshd 日志区分本机用户和经过 frpc 的登录；操作者须确认走的确实是原 FRP 路径。
4. 换钥时先添加，再选择新公钥「开始试登」，登录并确认后才撤旧钥。Agent 不允许撤销最后一把已经验证的公钥。已建立的 SSH 会话不会因为撤钥而被强制断开。

现场 `22` 的 sshd、主机密钥、账户密码和用户自己的 `authorized_keys` 不变。“现场密码策略”是对纳管账号做的配置探测，不代表每个 `Match` 来源、PAM 条件或所有账号都允许密码。远程入口独立监听 `127.0.0.1:2222`，只接受指定非 root 账号的公钥，关闭 TCP/Agent/X11 等转发；网页继续使用现有 Web 映射。此功能只约束纳管的 frpc，不替代云防火墙和 FRP 白名单，不能覆盖其他隧道服务或宿主机入侵。

## 隔离部署

本改动默认关闭，不应直接发布到生产。当前本地 Agent 为 1.7.2，线上是 1.7.3，并且生产已有日志任务的 0013/0014 两项迁移。试点前必须对齐现网代码和迁移链，在生产迁移之后另行编号本地白名单与 SSH 管理两项增量；不要覆盖已执行迁移，不要以 1.7.2 替换 1.7.3 的版本接口或下载件。先在隔离副本确认日志功能与迁移数据完整。

- 平台启用 `DEVICE_SSH_MANAGEMENT_ENABLED=1`，迁移并从 HTTPS 访问。只有后端完全不能被非可信源直接访问、且可信入口覆写 `X-Forwarded-Proto` 时，才配置 `DEVICE_SSH_TRUST_HTTPS_PROXY=1`；默认关闭。若使用项目内 Nginx，应确保 HTTPS 入口传给 Django 的协议为 https，不接受客户端自报协议。
- 确认隔离 Jetson 使用 Linux systemd、OpenSSH 服务和 iproute2，存在当前配置使用的 Ed25519 主机密钥，使用常规 `frpc -c /etc/frp/frpc.ini` 服务。Python 沿用 Agent 已安装的 `requests` 和标准库，不新增 pip 或 npm 依赖。
- 经可信控制台执行 `python manage.py provision_device_ssh DEVICE_ID`。设备凭据仅在该控制台显示一次，不进入普通发布日志。数据库只保存摘要；执行同一命令带 `--revoke` 撤销。撤销或轮换会使未完成的后台任务失效，但不会放宽已生效的 SSH 策略。
- 使用已审查的 Agent 和同目录的 `ssh_management.py` 一起安装，保持代码归 root 且普通账号不可写。创建 `/etc/device-agent/ssh-management`（root、0700），在 `enrollment.json`（root、0600）中填写 `account`、`credential`，核实独立恢复入口及旧转发入口确实受限后再将 `independent_recovery_verified` 置为 true。Agent 使用原 `CLOUD_SERVER` 的 HTTPS 地址，校验证书且不跟随重定向。
- 修改 Agent 自更新不是本轮范围：现有版本查询、下载、轮询和手动更新保持不变，也不会自动配送此独立模块。对已纳管设备，后续所有发行版都必须携带 FRP 保护入口并保持模块兼容；上线前另外验证旧发布不会覆盖新 Agent 或绕过策略，以及更新来源可信或经过验签。

## 回退与验证

首次尝试保存现有 frpc 配置，并由独立 systemd 定时器设置 5 分钟截止时间；即使平台断线或 Agent 重启也能尝试回退。未确认时只恢复 SSH 映射的原本地端口，保留合法的其他映射变化；FRP 已由平台停用时不能因回退而重新启动。若任务中途失败，看设备端 `device-agent-ssh-rollback.service` 和 `frpc.service` 的日志，使用独立恢复入口处理。确认后 Agent 锁定本机目标，平台收到可信回执后也锁定下发目标；下线或撤销凭据不会自动切回 22。不得删除策略文件、手动恢复旧 Agent 或移除 SSH 服务来当作回退。

隔离环境应实测公钥成功、FRP 密码失败、现场密码成功、旧钥撤销、Agent 重启、frpc 重连和等待超时自动回退；验证其他映射未改变、主机指纹一致、平台及视觉业务正常。真实测试前不得对现网开启。浏览器导出校验可用 `ssh-keygen -y -f <下载文件>`，与表单中的公钥对照。测试文件只用于隔离 QA，验证后删除。

## 接口

- 平台 HTTPS：`GET /api/devices/{device_id}/ssh-management/`；`POST /api/devices/{device_id}/ssh-management/tasks/`。操作限 `add_key`、`activate`、`verify_key`、`confirm`、`remove_key`；添加只接受 `public_key`，其余用 `fingerprint`；激活与确认还要求操作者明确核验。已创建返回 201，状态不允许时返回 409。
- Agent HTTPS：`POST /api/agent/ssh-management/{device_id}/poll/` 上报限字段状态并领取最多一项，`POST .../receipt/` 提交回执。使用逐设备 Bearer 凭据，不与旧匿名任务接口混用。任务认领后不自动重投，回执可幂等补发，超期后以设备状态为准核实实际执行结果。
