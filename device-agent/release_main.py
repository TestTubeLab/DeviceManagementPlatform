"""完整发布包的入口。无参数时由原 systemd 服务启动 Agent。"""

from pathlib import Path
import subprocess
import sys
import zipimport


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        from device_agent import main

        main()
    elif args == ['--check']:
        from device_agent import AGENT_VERSION
        from ssh_management import SshManagement, atomic_write

        if not isinstance(__loader__, zipimport.zipimporter) or not callable(SshManagement) or not callable(atomic_write):
            sys.exit('Agent 发布包或 SSH 模块不完整')
        print(AGENT_VERSION)
    elif len(args) == 2 and args[0] == 'install':
        from agent_release import install

        try:
            print(install(Path(sys.argv[0]), args[1]))
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            sys.exit(f'Agent 安装失败: {exc}')
    elif args[0] in ('enroll', 'rollback'):
        from ssh_management import run_cli

        run_cli(args)
    else:
        sys.exit('用法: python <Agent 发布包> [--check | install <SHA-256> | enroll <CA 文件>]')
