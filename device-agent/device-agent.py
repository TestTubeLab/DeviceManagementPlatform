#!/usr/bin/env python3
"""
Device Agent - 设备监控和OTA更新代理
项目部署后运行，负责：
1. 定时心跳上报（状态、性能指标）
2. 接收并执行OTA更新任务
3. 收集并上传日志
"""

import os
import sys
import time
import json
import subprocess
import requests
import psutil
from pathlib import Path

# ==================== 配置 ====================
CLOUD_SERVER = os.getenv("CLOUD_SERVER", "http://your-cloud.com/api")
DEVICE_ID_FILE = "/etc/device-id"
VERSION_FILE = "/work/.version"
HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）

# ==================== 读取设备ID ====================
def get_device_id():
    """读取设备ID"""
    if Path(DEVICE_ID_FILE).exists():
        return Path(DEVICE_ID_FILE).read_text().strip()
    else:
        print("错误：设备未注册，请先运行bootstrap-agent")
        sys.exit(1)

def get_current_version():
    """读取当前版本号"""
    if Path(VERSION_FILE).exists():
        return Path(VERSION_FILE).read_text().strip()
    return "unknown"

# ==================== 系统监控 ====================
def collect_metrics():
    """收集系统指标"""
    cpu_usage = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        "cpu_usage": round(cpu_usage, 2),
        "memory_usage": round(memory.percent, 2),
        "disk_usage": round(disk.percent, 2),
    }

# ==================== 心跳上报 ====================
def send_heartbeat():
    """发送心跳"""
    device_id = get_device_id()
    version = get_current_version()
    metrics = collect_metrics()
    
    data = {
        "version": version,
        **metrics
    }
    
    try:
        resp = requests.post(
            f"{CLOUD_SERVER}/devices/{device_id}/heartbeat/",
            json=data,
            timeout=10
        )
        
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"心跳失败: {resp.status_code}")
            return {"command": "none"}
    except Exception as e:
        print(f"心跳失败: {e}")
        return {"command": "none"}

# ==================== OTA更新 ====================
def execute_update(task_id, version):
    """执行OTA更新"""
    print(f"开始OTA更新: {version}")
    
    try:
        # 步骤1：拉取新镜像
        print("[1/3] 下载新版本...")
        report_update_progress(task_id, "downloading", 30)
        
        image = f"registry:5000/middleware:{version}"
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"镜像拉取失败: {result.stderr}")
        
        # 步骤2：停止旧容器
        print("[2/3] 停止旧服务...")
        report_update_progress(task_id, "installing", 60)
        subprocess.run(["docker", "stop", "middleware"], capture_output=True)
        subprocess.run(["docker", "rm", "middleware"], capture_output=True)
        
        # 步骤3：启动新容器
        print("[3/3] 启动新版本...")
        cmd = [
            "docker", "run",
            "-d",
            "--name", "middleware",
            "--restart", "always",
            "--network", "host",
            "-v", "/work/config:/work/config",
            "-v", "/work/localstore:/work/localstore",
            "--env-file", "/work/.env",
            image
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"容器启动失败: {result.stderr}")
        
        # 等待健康检查
        time.sleep(10)
        
        # 更新版本文件
        Path(VERSION_FILE).write_text(version)
        
        print(f"✓ 更新成功: {version}")
        report_update_progress(task_id, "success", 100)
        return True
        
    except Exception as e:
        print(f"✗ 更新失败: {e}")
        report_update_progress(task_id, "failed", 0, str(e))
        return False

def report_update_progress(task_id, status, progress, error_msg=""):
    """上报更新进度"""
    try:
        requests.post(
            f"{CLOUD_SERVER}/updates/{task_id}/update_progress/",
            json={
                "status": status,
                "progress": progress,
                "error_message": error_msg
            },
            timeout=5
        )
    except:
        pass

# ==================== 主循环 ====================
def main():
    device_id = get_device_id()
    print(f"Device Agent启动 - 设备ID: {device_id}")
    print(f"版本: {get_current_version()}")
    print(f"心跳间隔: {HEARTBEAT_INTERVAL}秒")
    
    while True:
        try:
            # 发送心跳并获取命令
            command = send_heartbeat()
            
            # 处理命令
            if command["command"] == "update":
                task_id = command["task_id"]
                version = command["version"]
                execute_update(task_id, version)
            
            elif command["command"] == "deploy":
                # 不应该在这里收到部署命令，忽略
                pass
            
            # 等待下一次心跳
            time.sleep(HEARTBEAT_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n停止Device Agent")
            break
        except Exception as e:
            print(f"错误: {e}")
            time.sleep(HEARTBEAT_INTERVAL)

if __name__ == "__main__":
    main()

