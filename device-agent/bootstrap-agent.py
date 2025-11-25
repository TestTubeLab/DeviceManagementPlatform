#!/usr/bin/env python3
"""
Bootstrap Agent - 零接触部署代理
开机自启动，等待云端部署指令

安装方法：
  curl -fsSL http://your-cloud.com/install.sh | bash
"""

import os
import sys
import time
import json
import socket
import hashlib
import subprocess
import requests
from pathlib import Path

# ==================== 配置 ====================
CLOUD_SERVER = os.getenv("CLOUD_SERVER", "http://your-cloud.com/api")
DEVICE_ID_FILE = "/etc/device-id"
STATE_FILE = "/opt/bootstrap/state.json"
VERSION_FILE = "/work/.version"

# ==================== 生成设备ID ====================
def get_device_id():
    """
    生成唯一设备ID（基于MAC地址）
    格式：dev_abc123def456
    """
    if Path(DEVICE_ID_FILE).exists():
        return Path(DEVICE_ID_FILE).read_text().strip()
    
    # 获取主网卡MAC地址
    mac = get_mac_address()
    device_id = f"dev_{hashlib.md5(mac.encode()).hexdigest()[:12]}"
    
    # 保存到文件
    os.makedirs(os.path.dirname(DEVICE_ID_FILE), exist_ok=True)
    Path(DEVICE_ID_FILE).write_text(device_id)
    return device_id

def get_mac_address():
    """获取第一个非lo网卡的MAC地址"""
    try:
        output = subprocess.check_output(['ip', 'link', 'show']).decode()
        for line in output.split('\n'):
            if 'link/ether' in line:
                return line.split()[1]
    except:
        return socket.gethostname()

def get_local_ip():
    """获取本机IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "unknown"

# ==================== 设备注册 ====================
def register_device():
    """向云端注册设备"""
    device_id = get_device_id()
    
    device_info = {
        "device_id": device_id,
        "mac_address": get_mac_address(),
        "hostname": socket.gethostname(),
        "ip_address": get_local_ip(),
        "status": "waiting_deployment"
    }
    
    try:
        resp = requests.post(
            f"{CLOUD_SERVER}/devices/register/",
            json=device_info,
            timeout=10
        )
        
        if resp.status_code == 200:
            print(f"✓ 设备注册成功: {device_id}")
            return True
        else:
            print(f"✗ 注册失败: {resp.status_code}")
            return False
    except Exception as e:
        print(f"✗ 连接服务器失败: {e}")
        return False

# ==================== 检查部署指令 ====================
def check_deployment_command():
    """轮询检查是否有部署指令"""
    device_id = get_device_id()
    
    try:
        resp = requests.get(
            f"{CLOUD_SERVER}/devices/{device_id}/deployment/",
            timeout=5
        )
        
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"status": "waiting"}
    except:
        return {"status": "error"}

# ==================== 执行部署 ====================
def execute_deployment(deployment_config):
    """执行部署任务"""
    print("=" * 60)
    print("开始部署项目...")
    print("=" * 60)
    
    try:
        # 步骤1：拉取Docker镜像
        print("\n[1/5] 拉取项目镜像...")
        report_progress("downloading", 20, "正在下载镜像...")
        
        image = deployment_config["image"]
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"镜像拉取失败: {result.stderr}")
        
        print(f"✓ 镜像拉取完成: {image}")
        
        # 步骤2：创建配置文件
        print("\n[2/5] 生成配置文件...")
        report_progress("configuring", 40, "正在生成配置...")
        
        create_config_files(deployment_config["config"])
        print("✓ 配置文件生成完成")
        
        # 步骤3：创建数据目录
        print("\n[3/5] 创建数据目录...")
        os.makedirs("/work/localstore/data", exist_ok=True)
        os.makedirs("/work/localstore/logs", exist_ok=True)
        print("✓ 数据目录创建完成")
        
        # 步骤4：启动容器
        print("\n[4/5] 启动服务容器...")
        report_progress("starting", 70, "正在启动服务...")
        
        start_container(deployment_config)
        print("✓ 容器启动完成")
        
        # 步骤5：健康检查
        print("\n[5/5] 健康检查...")
        report_progress("checking", 90, "正在检查服务状态...")
        
        if wait_for_health_check():
            print("✓ 服务启动成功！")
            report_progress("completed", 100, "部署完成")
            save_state("deployed", deployment_config)
            return True
        else:
            raise Exception("健康检查失败")
        
    except Exception as e:
        print(f"✗ 部署失败: {e}")
        report_progress("failed", 0, str(e))
        return False

def create_config_files(config):
    """生成配置文件"""
    os.makedirs("/work/config", exist_ok=True)
    
    # 生成 .env 文件
    env_content = f"""
REVERSE_SOCKET_HOST={config.get('reverse_socket_host', '192.168.31.29')}
REVERSE_SOCKET_PORT={config.get('reverse_socket_port', 9088)}
PROJECT_ROOT=/work/MiddlewareServer
"""
    Path("/work/.env").write_text(env_content)

def start_container(deployment_config):
    """启动Docker容器"""
    # 先删除旧容器（如果存在）
    subprocess.run(["docker", "rm", "-f", "middleware"], 
                   capture_output=True)
    
    # 启动新容器
    cmd = [
        "docker", "run",
        "-d",
        "--name", "middleware",
        "--restart", "always",
        "--network", "host",
        "-v", "/work/config:/work/config",
        "-v", "/work/localstore:/work/localstore",
        "--env-file", "/work/.env",
        deployment_config["image"]
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"容器启动失败: {result.stderr}")

def wait_for_health_check(timeout=60):
    """等待服务健康检查通过"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            resp = requests.get("http://localhost:8000/api/health/", timeout=2)
            if resp.status_code == 200:
                return True
        except:
            pass
        
        time.sleep(3)
    
    return False

# ==================== 状态上报 ====================
def report_progress(status, progress, message):
    """上报部署进度"""
    device_id = get_device_id()
    
    try:
        requests.post(
            f"{CLOUD_SERVER}/devices/{device_id}/progress/",
            json={
                "status": status,
                "progress": progress,
                "message": message
            },
            timeout=5
        )
    except:
        pass

def save_state(status, config=None):
    """保存本地状态"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state = {
        "status": status,
        "timestamp": time.time(),
        "config": config
    }
    Path(STATE_FILE).write_text(json.dumps(state, indent=2))

# ==================== 主循环 ====================
def main():
    print("=" * 60)
    print("Bootstrap Agent - 零接触部署代理")
    print("=" * 60)
    
    device_id = get_device_id()
    print(f"设备ID: {device_id}")
    print(f"IP地址: {get_local_ip()}")
    print(f"云端服务器: {CLOUD_SERVER}")
    
    # 检查是否已部署
    if Path(STATE_FILE).exists():
        state = json.loads(Path(STATE_FILE).read_text())
        if state.get("status") == "deployed":
            print("\n✓ 项目已部署，退出bootstrap模式")
            return
    
    # 注册设备
    print("\n正在注册设备...")
    retry_count = 0
    while not register_device():
        retry_count += 1
        print(f"重试 ({retry_count}/10)...")
        time.sleep(10)
        if retry_count >= 10:
            print("✗ 无法连接到云端服务器，请检查网络")
            sys.exit(1)
    
    # 等待部署指令
    print("\n等待管理员下发部署指令...")
    print("提示：请在Web管理界面点击[部署]按钮")
    
    while True:
        cmd = check_deployment_command()
        
        if cmd["status"] == "ready_to_deploy":
            print("\n收到部署指令！")
            if execute_deployment(cmd["deployment_config"]):
                print("\n✓ 部署成功！")
                break
            else:
                print("\n✗ 部署失败，继续等待...")
        
        elif cmd["status"] == "waiting":
            # 每30秒轮询一次
            time.sleep(30)
        
        else:
            time.sleep(10)

if __name__ == "__main__":
    main()


