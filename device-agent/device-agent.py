#!/usr/bin/env python3
"""
Device Agent - 设备监控和部署代理
运行在边缘设备上，负责：
1. 定时心跳上报（状态、性能指标）
2. 轮询并执行部署任务（拉取镜像、启动容器）
3. 执行更新任务
4. 收集并上传日志
"""

import os
import sys
import time
import json
import subprocess
import requests
import psutil
from pathlib import Path
import logging

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/device-agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 配置 ====================
AGENT_VERSION = "1.2.1"  # Agent 版本号，每次更新递增
CLOUD_SERVER = os.getenv("CLOUD_SERVER", "http://your-server.com/api")
DEVICE_ID_FILE = os.getenv("DEVICE_ID_FILE", "/etc/device-id")
VERSION_FILE = os.getenv("VERSION_FILE", "/work/.version")
AGENT_SCRIPT_PATH = "/opt/device-agent/agent.py"  # Agent 脚本路径
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "10"))  # 心跳间隔（秒）
TASK_POLL_INTERVAL = int(os.getenv("TASK_POLL_INTERVAL", "5"))   # 任务轮询间隔（秒）
LOG_UPLOAD_INTERVAL = int(os.getenv("LOG_UPLOAD_INTERVAL", "1")) # 日志上传间隔（秒）
UPDATE_CHECK_INTERVAL = int(os.getenv("UPDATE_CHECK_INTERVAL", "3600")) # 更新检查间隔（1小时）
CONFIG_CHECK_INTERVAL = int(os.getenv("CONFIG_CHECK_INTERVAL", "10")) # 配置检查间隔（秒）

# ==================== 设备注册 ====================
def register_device():
    """注册设备到云端服务器"""
    import socket
    import uuid
    import hashlib
    
    try:
        logger.info("正在注册设备...")
        
        # 获取本机IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        
        # 获取MAC地址
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) 
                       for ele in range(0, 48, 8)][::-1])
        
        # 基于MAC地址生成确定性的设备ID（同一设备每次注册都得到相同ID）
        mac_hash = hashlib.md5(mac.encode()).hexdigest()[:8]
        device_id = f"DEV-{mac_hash}"
        
        # 获取主机名
        hostname = socket.gethostname()
        
        # 注册到服务器
        data = {
            "device_id": device_id,
            "mac_address": mac,
            "ip_address": ip_address,
            "hostname": hostname
        }
        
        resp = requests.post(
            f"{CLOUD_SERVER}/devices/register/",
            json=data,
            timeout=10
        )
        
        if resp.status_code == 200:
            result = resp.json()
            registered_device_id = result.get('device_id', device_id)
            
            # 保存设备ID到文件
            Path(DEVICE_ID_FILE).parent.mkdir(parents=True, exist_ok=True)
            Path(DEVICE_ID_FILE).write_text(registered_device_id)
            
            logger.info(f"设备注册成功: {registered_device_id}")
            return registered_device_id
        else:
            logger.error(f"设备注册失败: HTTP {resp.status_code}")
            logger.error(f"响应内容: {resp.text}")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"设备注册异常: {e}")
        sys.exit(1)

# ==================== 读取设备ID ====================
def get_device_id():
    """读取设备ID，如果不存在则自动注册"""
    if Path(DEVICE_ID_FILE).exists():
        return Path(DEVICE_ID_FILE).read_text().strip()
    else:
        logger.warning("设备ID文件不存在，正在自动注册...")
        return register_device()

def get_current_version():
    """读取当前版本号"""
    if Path(VERSION_FILE).exists():
        return Path(VERSION_FILE).read_text().strip()
    return "unknown"

def save_version(version):
    """保存版本号"""
    try:
        Path(VERSION_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(VERSION_FILE).write_text(version)
        logger.info(f"版本号已更新: {version}")
    except Exception as e:
        logger.error(f"保存版本号失败: {e}")

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

# ==================== 容器和服务状态监控 ====================
def collect_container_status(container_name="middleware"):
    """收集容器状态"""
    try:
        # 检查容器是否存在和运行
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}|{{.State.StartedAt}}", container_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "container_status": "not_found",
                "container_name": container_name,
                "container_uptime": ""
            }
        
        output = result.stdout.strip()
        parts = output.split("|")
        status = parts[0] if parts else "unknown"
        started_at = parts[1] if len(parts) > 1 else ""
        
        # 计算运行时长
        uptime = ""
        if status == "running" and started_at:
            try:
                from datetime import datetime
                # 解析 Docker 时间格式
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00").split(".")[0])
                now = datetime.now(started.tzinfo) if started.tzinfo else datetime.now()
                delta = now - started.replace(tzinfo=None)
                
                days = delta.days
                hours, remainder = divmod(delta.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                
                if days > 0:
                    uptime = f"{days}d {hours}h"
                elif hours > 0:
                    uptime = f"{hours}h {minutes}m"
                else:
                    uptime = f"{minutes}m"
            except Exception as e:
                logger.debug(f"计算运行时长失败: {e}")
                uptime = "运行中"
        
        return {
            "container_status": "running" if status == "running" else "stopped",
            "container_name": container_name,
            "container_uptime": uptime
        }
    except subprocess.TimeoutExpired:
        return {
            "container_status": "error",
            "container_name": container_name,
            "container_uptime": ""
        }
    except Exception as e:
        logger.error(f"获取容器状态失败: {e}")
        return {
            "container_status": "error",
            "container_name": container_name,
            "container_uptime": ""
        }

def check_service_health(health_url="http://localhost:8000/api/"):
    """检查服务健康状态"""
    import time
    
    try:
        start_time = time.time()
        resp = requests.get(health_url, timeout=5)
        response_time = int((time.time() - start_time) * 1000)  # 转为毫秒
        
        if resp.status_code < 500:  # 2xx, 3xx, 4xx 都认为服务是活着的
            return {
                "service_status": "healthy",
                "service_response_time": response_time
            }
        else:
            return {
                "service_status": "unhealthy",
                "service_response_time": response_time
            }
    except requests.exceptions.Timeout:
        return {
            "service_status": "unhealthy",
            "service_response_time": 5000
        }
    except requests.exceptions.ConnectionError:
        return {
            "service_status": "unhealthy",
            "service_response_time": 0
        }
    except Exception as e:
        logger.debug(f"健康检查失败: {e}")
        return {
            "service_status": "unknown",
            "service_response_time": 0
        }

# ==================== 心跳上报 ====================
def send_heartbeat():
    """发送心跳，并获取待执行的命令"""
    device_id = get_device_id()
    version = get_current_version()
    metrics = collect_metrics()
    
    # 收集容器状态
    container_info = collect_container_status("middleware")
    
    # 检查服务健康（只有容器运行时才检查）
    if container_info["container_status"] == "running":
        health_info = check_service_health("http://localhost:8000/api/metrics")
    else:
        health_info = {
            "service_status": "unknown",
            "service_response_time": 0
        }
    
    data = {
        "version": version,
        "agent_version": AGENT_VERSION,  # 上报 Agent 版本
        **metrics,
        **container_info,
        **health_info
    }
    
    # 确保所有字符串都是正确的UTF-8编码
    def ensure_utf8(d):
        if isinstance(d, str):
            return d.encode('utf-8', errors='replace').decode('utf-8')
        elif isinstance(d, dict):
            return {k: ensure_utf8(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [ensure_utf8(item) for item in d]
        return d
    
    data = ensure_utf8(data)
    
    try:
        resp = requests.post(
            f"{CLOUD_SERVER}/devices/{device_id}/heartbeat/",
            json=data,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            timeout=10
        )
        
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            # 设备在服务器上不存在，可能已被删除，强制重新注册
            logger.warning(f"设备不存在(404)，正在重新注册...")
            if os.path.exists(DEVICE_ID_FILE):
                os.remove(DEVICE_ID_FILE)
            # 重新注册
            new_device_id = register_device()
            logger.info(f"重新注册成功: {new_device_id}")
            return {"command": "none"}
        else:
            logger.warning(f"心跳失败: {resp.status_code}")
            return {"command": "none"}
    except Exception as e:
        logger.error(f"心跳失败: {e}")
        return {"command": "none"}

# ==================== 容器日志收集与上传 ====================
def get_container_log_path(container_name):
    """获取容器日志文件路径"""
    try:
        result = subprocess.run(
            ["docker", "inspect", container_name, "--format", "{{.LogPath}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception as e:
        logger.error(f"获取容器日志路径失败: {e}")
        return None

def collect_container_logs(container_name="middleware", lines=100):
    """
    收集容器日志 - 直接读取日志文件，避免 docker logs 命令卡住
    """
    try:
        # 方式1：直接读取日志文件（更稳定）
        log_path = get_container_log_path(container_name)
        if log_path and os.path.exists(log_path):
            try:
                # 使用 tail 命令读取最后 N 行（更快）
                result = subprocess.run(
                    ["tail", "-n", str(lines), log_path],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and result.stdout:
                    # 解析 JSON 格式的 Docker 日志
                    log_lines = []
                    for line in result.stdout.strip().split('\n'):
                        try:
                            import json
                            log_entry = json.loads(line)
                            log_content = log_entry.get('log', '').rstrip('\n')
                            if log_content:
                                log_lines.append(log_content)
                        except json.JSONDecodeError:
                            # 非 JSON 格式，直接添加
                            if line.strip():
                                log_lines.append(line.strip())
                    if log_lines:
                        return '\n'.join(log_lines)
            except subprocess.TimeoutExpired:
                logger.warning(f"读取日志文件超时: {log_path}")
            except Exception as e:
                logger.debug(f"读取日志文件失败，尝试 docker logs: {e}")
        
        # 方式2：回退到 docker logs 命令（设置更短的超时）
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container_name],
            capture_output=True,
            text=True,
            timeout=10  # 缩短超时时间
        )
        logs = result.stdout + result.stderr
        return logs.strip() if logs else ""
        
    except subprocess.TimeoutExpired:
        logger.warning(f"收集容器日志超时: {container_name}")
        return ""
    except Exception as e:
        logger.error(f"收集容器日志失败: {e}")
        return ""

def upload_container_logs(container_name="middleware"):
    """上传容器日志到服务器"""
    device_id = get_device_id()
    logs = collect_container_logs(container_name)
    
    if not logs:
        return False
    
    try:
        resp = requests.post(
            f"{CLOUD_SERVER}/devices/{device_id}/upload_logs/",
            json={
                "logs": logs,
                "container_name": container_name
            },
            timeout=30
        )
        
        if resp.status_code == 200:
            logger.debug("容器日志上传成功")
            return True
        else:
            logger.warning(f"日志上传失败: {resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"日志上传失败: {e}")
        return False

# ==================== Agent 自动更新 ====================
def check_agent_update():
    """检查 Agent 是否有新版本"""
    try:
        resp = requests.get(
            f"{CLOUD_SERVER}/agent/version/",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            latest_version = data.get('version', '')
            if latest_version and latest_version != AGENT_VERSION:
                logger.info(f"发现 Agent 新版本: {latest_version} (当前: {AGENT_VERSION})")
                return latest_version
        return None
    except Exception as e:
        logger.debug(f"检查 Agent 更新失败: {e}")
        return None

def download_new_agent():
    """下载新版本 Agent 脚本"""
    try:
        resp = requests.get(
            f"{CLOUD_SERVER}/agent/download/",
            timeout=60
        )
        if resp.status_code == 200:
            return resp.text
        else:
            logger.error(f"下载 Agent 失败: {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"下载 Agent 失败: {e}")
        return None

def apply_agent_update():
    """应用 Agent 更新：下载新版本并重启服务"""
    logger.info("开始更新 Agent...")
    
    # 1. 下载新版本
    new_script = download_new_agent()
    if not new_script:
        logger.error("下载新版本失败，取消更新")
        return False
    
    # 2. 备份当前版本
    backup_path = f"{AGENT_SCRIPT_PATH}.backup"
    try:
        if os.path.exists(AGENT_SCRIPT_PATH):
            import shutil
            shutil.copy2(AGENT_SCRIPT_PATH, backup_path)
            logger.info(f"已备份当前版本到: {backup_path}")
    except Exception as e:
        logger.warning(f"备份失败: {e}")
    
    # 3. 写入新版本
    try:
        with open(AGENT_SCRIPT_PATH, 'w') as f:
            f.write(new_script)
        logger.info("新版本已写入")
    except Exception as e:
        logger.error(f"写入新版本失败: {e}")
        # 尝试恢复备份
        if os.path.exists(backup_path):
            import shutil
            shutil.copy2(backup_path, AGENT_SCRIPT_PATH)
            logger.info("已恢复备份版本")
        return False
    
    # 4. 重启服务
    logger.info("重启 Agent 服务...")
    try:
        subprocess.run(
            ["systemctl", "restart", "device-agent"],
            timeout=30
        )
    except Exception as e:
        logger.error(f"重启服务失败: {e}")
        return False
    
    return True

# ==================== 轮询部署任务 ====================
def poll_deployment_tasks():
    """轮询待执行的部署任务"""
    device_id = get_device_id()
    
    try:
        # 首先获取设备的数据库主键
        device_resp = requests.get(
            f"{CLOUD_SERVER}/devices/{device_id}/",
            timeout=10
        )
        
        if device_resp.status_code != 200:
            logger.warning(f"获取设备信息失败: {device_resp.status_code}")
            return []
        
        device_pk = device_resp.json().get('id')
        if not device_pk:
            logger.warning("设备信息中没有主键")
            return []
        
        # 使用设备主键查询待执行的部署任务
        resp = requests.get(
            f"{CLOUD_SERVER}/deployments/",
            params={"device": device_pk, "status": "pending"},
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            tasks = data.get('results', [])
            return tasks
        else:
            logger.warning(f"轮询部署任务失败: {resp.status_code}")
            return []
    except Exception as e:
        logger.error(f"轮询部署任务失败: {e}")
        return []

# ==================== 部署任务执行 ====================
def execute_deployment(task):
    """执行部署任务"""
    task_id = task['id']
    task_type = task.get('task_type', 'deploy')
    image_info = task.get('image_info', {})
    container_name = task.get('container_name', 'middleware')
    container_config = task.get('container_config', {})
    config = task.get('config', {})
    
    # 如果是重启任务，执行简单的容器重启
    # 支持两种方式：task_type='restart' 或 config.action='restart_container'
    if task_type == 'restart' or config.get('action') == 'restart_container':
        return execute_restart(task_id, container_name)
    
    logger.info(f"开始执行部署任务 #{task_id}")
    
    # 检查镜像信息是否存在
    if not image_info:
        error_msg = "任务缺少镜像信息，无法部署"
        logger.error(error_msg)
        report_deployment_progress(task_id, status="failed", progress=0,
                                   error_message=error_msg)
        return False
    
    logger.info(f"镜像: {image_info.get('full_name', 'unknown')}")
    logger.info(f"容器名称: {container_name}")
    
    try:
        # 步骤1：更新状态为running
        report_deployment_progress(task_id, status="downloading", progress=10, 
                                   message="开始拉取镜像...")
        
        # 步骤2：拉取镜像
        full_name = image_info.get('full_name')
        if not full_name:
            raise Exception("镜像信息不完整")
        
        logger.info(f"拉取镜像: {full_name}")
        result = subprocess.run(
            ["docker", "pull", full_name],
            capture_output=True,
            text=True,
            timeout=600  # 10分钟超时
        )
        
        if result.returncode != 0:
            raise Exception(f"镜像拉取失败: {result.stderr}")
        
        logger.info("镜像拉取完成")
        report_deployment_progress(task_id, status="configuring", progress=50,
                                   message="镜像拉取完成，准备启动容器...")
        
        # 步骤3：停止并删除旧容器（如果存在）
        logger.info(f"停止旧容器: {container_name}")
        subprocess.run(["docker", "stop", container_name], 
                      capture_output=True, timeout=30)
        subprocess.run(["docker", "rm", container_name], 
                      capture_output=True, timeout=30)
        
        # 步骤4：构建docker run命令
        cmd = ["docker", "run", "-d", "--name", container_name]
        
        # 添加端口映射
        ports = container_config.get('ports', {})
        for container_port, host_port in ports.items():
            cmd.extend(["-p", f"{host_port}:{container_port.replace('/tcp', '')}"])
        
        # 添加环境变量
        environment = container_config.get('environment', {})
        for key, value in environment.items():
            cmd.extend(["-e", f"{key}={value}"])
        
        # 添加数据卷
        volumes = container_config.get('volumes', {})
        for host_path, bind_config in volumes.items():
            container_path = bind_config.get('bind', host_path)
            cmd.extend(["-v", f"{host_path}:{container_path}"])
        
        # 添加重启策略
        restart_policy = container_config.get('restart_policy', {})
        restart_name = restart_policy.get('Name', 'always')
        cmd.extend(["--restart", restart_name])
        
        # 添加镜像名称
        cmd.append(full_name)
        
        # 步骤5：启动容器
        logger.info(f"启动容器: {' '.join(cmd)}")
        report_deployment_progress(task_id, status="starting", progress=80,
                                   message="正在启动容器...")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            raise Exception(f"容器启动失败: {result.stderr}")
        
        container_id = result.stdout.strip()
        logger.info(f"容器启动成功: {container_id[:12]}")
        
        # 步骤6：等待容器运行
        time.sleep(5)
        
        # 步骤7：检查容器状态
        check_result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
            capture_output=True,
            text=True
        )
        
        if "Up" not in check_result.stdout:
            raise Exception("容器未能正常运行")
        
        # 步骤8：更新版本文件
        version = image_info.get('tag', 'unknown')
        save_version(version)
        
        # 步骤9：上报成功
        logger.info(f"部署成功: {image_info.get('name')}:{version}")
        report_deployment_progress(task_id, status="completed", progress=100,
                                   message=f"部署成功")
        return True
        
    except subprocess.TimeoutExpired:
        error_msg = "操作超时"
        logger.error(f"部署失败: {error_msg}")
        report_deployment_progress(task_id, status="failed", progress=0, 
                                   error_message=error_msg)
        return False
    except Exception as e:
        error_msg = str(e)
        logger.error(f"部署失败: {error_msg}")
        report_deployment_progress(task_id, status="failed", progress=0,
                                   error_message=error_msg)
        return False

# ==================== 重启任务执行 ====================
def execute_restart(task_id, container_name):
    """执行容器重启任务"""
    logger.info(f"开始执行重启任务 #{task_id}")
    logger.info(f"容器名称: {container_name}")
    
    try:
        # 步骤1：更新状态
        report_deployment_progress(task_id, status="running", progress=30, 
                                   message="正在重启容器...")
        
        # 步骤2：重启容器
        logger.info(f"重启容器: {container_name}")
        result = subprocess.run(
            ["docker", "restart", container_name],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise Exception(f"容器重启失败: {result.stderr}")
        
        logger.info("容器重启成功")
        report_deployment_progress(task_id, status="running", progress=70,
                                   message="等待容器就绪...")
        
        # 步骤3：等待容器运行
        time.sleep(5)
        
        # 步骤4：检查容器状态
        check_result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
            capture_output=True,
            text=True
        )
        
        if "Up" not in check_result.stdout:
            raise Exception("容器未能正常运行")
        
        # 步骤5：上报成功
        logger.info(f"重启成功: {container_name}")
        report_deployment_progress(task_id, status="completed", progress=100,
                                   message="重启成功")
        return True
        
    except subprocess.TimeoutExpired:
        error_msg = "重启操作超时"
        logger.error(f"重启失败: {error_msg}")
        report_deployment_progress(task_id, status="failed", progress=0, 
                                   error_message=error_msg)
        return False
    except Exception as e:
        error_msg = str(e)
        logger.error(f"重启失败: {error_msg}")
        report_deployment_progress(task_id, status="failed", progress=0,
                                   error_message=error_msg)
        return False

def report_deployment_progress(task_id, **kwargs):
    """上报部署进度"""
    try:
        requests.post(
            f"{CLOUD_SERVER}/deployments/{task_id}/update_progress/",
            json=kwargs,
            timeout=5
        )
        logger.debug(f"上报部署进度: {kwargs}")
    except Exception as e:
        logger.warning(f"上报部署进度失败: {e}")

# ==================== OTA更新 ====================
def execute_update(task_id, version):
    """执行OTA更新"""
    logger.info(f"开始OTA更新: {version}")
    
    try:
        # 步骤1：拉取新镜像
        logger.info("[1/3] 下载新版本...")
        report_update_progress(task_id, "downloading", 30)
        
        image = f"registry:5000/middleware:{version}"
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode != 0:
            raise Exception(f"镜像拉取失败: {result.stderr}")
        
        # 步骤2：停止旧容器
        logger.info("[2/3] 停止旧服务...")
        report_update_progress(task_id, "installing", 60)
        subprocess.run(["docker", "stop", "middleware"], capture_output=True)
        subprocess.run(["docker", "rm", "middleware"], capture_output=True)
        
        # 步骤3：启动新容器
        logger.info("[3/3] 启动新版本...")
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
        save_version(version)
        
        logger.info(f"✓ 更新成功: {version}")
        report_update_progress(task_id, "success", 100)
        return True
        
    except Exception as e:
        logger.error(f"✗ 更新失败: {e}")
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
    except Exception as e:
        logger.warning(f"上报更新进度失败: {e}")

# ==================== 项目部署 ====================
def poll_project_deployments():
    """轮询项目部署任务"""
    device_id = get_device_id()
    
    try:
        # 获取设备主键
        device_resp = requests.get(
            f"{CLOUD_SERVER}/devices/{device_id}/",
            timeout=10
        )
        
        if device_resp.status_code != 200:
            return []
        
        device_pk = device_resp.json().get('id')
        
        # 查询待执行的项目部署任务
        resp = requests.get(
            f"{CLOUD_SERVER}/project-deployments/",
            params={"device_id": device_id, "status": "pending"},
            timeout=10
        )
        
        if resp.status_code == 200:
            return resp.json().get('results', [])
        else:
            logger.warning(f"轮询项目部署任务失败: {resp.status_code}")
            return []
    except Exception as e:
        logger.error(f"轮询项目部署任务失败: {e}")
        return []

def download_and_extract_code_package(code_package_info, target_dir):
    """下载并解压代码包"""
    import zipfile
    import tarfile
    import tempfile
    import shutil
    
    pkg_id = code_package_info.get('id')
    pkg_name = code_package_info.get('name')
    pkg_version = code_package_info.get('version')
    
    logger.info(f"下载代码包: {pkg_name} ({pkg_version})")
    
    # 下载代码包
    download_url = f"{CLOUD_SERVER}/code-packages/{pkg_id}/download/"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.archive') as tmp_file:
        tmp_path = tmp_file.name
        
        try:
            resp = requests.get(download_url, timeout=300, stream=True)
            if resp.status_code != 200:
                raise Exception(f"下载失败: HTTP {resp.status_code}")
            
            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0
            
            for chunk in resp.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    progress = int((downloaded / total_size) * 100)
                    if progress % 20 == 0:
                        logger.info(f"下载进度: {progress}%")
            
            logger.info(f"代码包下载完成: {downloaded} bytes")
        except Exception as e:
            os.unlink(tmp_path)
            raise Exception(f"下载代码包失败: {e}")
    
    # 确保目标目录存在
    os.makedirs(target_dir, exist_ok=True)
    
    # 清空目标目录（保留.env配置文件）- 增强错误处理
    logger.info(f"清理目标目录: {target_dir}")
    for item in os.listdir(target_dir):
        item_path = os.path.join(target_dir, item)
        if item == '.env':  # 保留配置文件
            continue
        
        try:
            if os.path.isdir(item_path):
                # 如果是目录，使用shutil.rmtree强制删除
                shutil.rmtree(item_path, ignore_errors=True)
                # 验证是否删除成功
                if os.path.exists(item_path):
                    # 如果还存在，尝试修改权限后再删除
                    import stat
                    os.chmod(item_path, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
                    shutil.rmtree(item_path)
            else:
                os.remove(item_path)
            logger.debug(f"  已删除: {item}")
        except Exception as e:
            logger.warning(f"  删除失败 {item}: {e}，尝试继续...")
            # 不阻塞部署，继续处理其他文件
    
    # 解压代码包
    try:
        # 尝试作为zip解压
        if zipfile.is_zipfile(tmp_path):
            logger.info("解压ZIP文件...")
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
        # 尝试作为tar.gz解压
        elif tarfile.is_tarfile(tmp_path):
            logger.info("解压TAR文件...")
            with tarfile.open(tmp_path, 'r:*') as tar_ref:
                tar_ref.extractall(target_dir)
        else:
            raise Exception("不支持的压缩格式")
        
        logger.info(f"代码解压完成: {target_dir}")
    finally:
        # 清理临时文件
        os.unlink(tmp_path)
    
    return True


def execute_project_restart(deployment):
    """执行项目重启任务（ProjectDeployment 类型）"""
    deployment_id = deployment['id']
    project = deployment.get('project_info') or deployment.get('project')
    
    # 获取容器名称
    container_name = 'middleware'  # 默认值
    if project:
        container_name = project.get('container_name', container_name)
    
    logger.info(f"开始执行重启任务 #{deployment_id}")
    logger.info(f"容器名称: {container_name}")
    
    try:
        # 步骤1：更新状态
        report_project_deployment_progress(deployment_id, status="starting", progress=30, 
                                           message="正在重启容器...")
        
        # 步骤2：重启容器
        logger.info(f"重启容器: {container_name}")
        result = subprocess.run(
            ["docker", "restart", container_name],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise Exception(f"容器重启失败: {result.stderr}")
        
        logger.info("容器重启成功")
        report_project_deployment_progress(deployment_id, status="running", progress=70,
                                           message="等待容器就绪...")
        
        # 步骤3：等待容器运行
        time.sleep(5)
        
        # 步骤4：检查容器状态
        check_result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
            capture_output=True,
            text=True
        )
        
        if "Up" not in check_result.stdout:
            raise Exception("容器未能正常运行")
        
        # 步骤5：上报成功
        logger.info(f"重启成功: {container_name}")
        report_project_deployment_progress(deployment_id, status="completed", progress=100,
                                           message="重启成功")
        return True
        
    except subprocess.TimeoutExpired:
        error_msg = "重启操作超时"
        logger.error(f"重启失败: {error_msg}")
        report_project_deployment_progress(deployment_id, status="failed", progress=0, 
                                           error_message=error_msg)
        return False
    except Exception as e:
        error_msg = str(e)
        logger.error(f"重启失败: {error_msg}")
        report_project_deployment_progress(deployment_id, status="failed", progress=0,
                                           error_message=error_msg)
        return False


def execute_project_deployment(deployment):
    """执行项目部署（支持代码包 + 本地镜像 + 重启）"""
    deployment_id = deployment['id']
    task_type = deployment.get('task_type', 'deploy')
    project = deployment.get('project_info') or deployment.get('project')
    
    # ========== 处理重启任务 ==========
    if task_type == 'restart':
        return execute_project_restart(deployment)
    
    # ========== 处理部署任务 ==========
    if not project:
        logger.error(f"部署任务 #{deployment_id} 缺少项目信息")
        report_project_deployment_progress(deployment_id, status="failed", progress=0,
                                           error_message="缺少项目信息")
        return False
    
    project_name = project.get('name')
    project_version = project.get('version')
    
    logger.info(f"开始执行项目部署 #{deployment_id}")
    logger.info(f"项目: {project_name} v{project_version}")
    
    git_commit = ""
    
    try:
        # ========== 步骤1: 检查Docker镜像 ==========
        report_project_deployment_progress(deployment_id, status="pulling_image", progress=10, 
                                           message="正在检查Docker镜像...")
        
        docker_image = project.get('docker_image_info')
        # 支持直接指定本地镜像名称
        local_image_name = project.get('local_image_name', '')
        image_full_name = None
        
        if local_image_name:
            # 使用本地预装镜像（不拉取）
            image_full_name = local_image_name
            logger.info(f"使用本地镜像: {image_full_name}")
            
            # 检查镜像是否存在
            check_result = subprocess.run(
                ["docker", "images", "-q", image_full_name],
                capture_output=True, text=True
            )
            if not check_result.stdout.strip():
                raise Exception(f"本地镜像不存在: {image_full_name}")
            logger.info("本地镜像检查通过")
            
        elif docker_image:
            image_full_name = docker_image.get('full_name')
            logger.info(f"拉取镜像: {image_full_name}")
            result = subprocess.run(
                ["docker", "pull", image_full_name],
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode != 0:
                logger.warning(f"镜像拉取失败(可能本地已有): {result.stderr}")
            else:
                logger.info("镜像拉取完成")
        else:
            logger.info("未指定Docker镜像，将使用现有镜像")
        
        # ========== 步骤2: 获取代码 ==========
        report_project_deployment_progress(deployment_id, status="pulling_code", progress=30,
                                           message="正在获取项目代码...")
        
        # 宿主机上的代码目录
        code_mount_path = project.get('code_mount_path', '/opt/project-code')
        work_dir = project.get('work_dir', '/work')
        
        code_package = project.get('code_package_info')
        git_repo = project.get('git_repo')
        
        # 优先使用代码包
        if code_package:
            logger.info(f"使用代码包: {code_package.get('name')} v{code_package.get('version')}")
            download_and_extract_code_package(code_package, code_mount_path)
            git_commit = f"pkg-{code_package.get('version')}"
        
        # 备选：使用Git
        elif git_repo:
            git_branch = project.get('git_branch', 'main')
            logger.info(f"拉取代码: {git_repo} (分支: {git_branch})")
            
            os.makedirs(code_mount_path, exist_ok=True)
            
            git_dir = os.path.join(code_mount_path, '.git')
            if os.path.exists(git_dir):
                result = subprocess.run(
                    ["git", "-C", code_mount_path, "pull", "origin", git_branch],
                    capture_output=True, text=True, timeout=300
                )
            else:
                result = subprocess.run(
                    ["git", "clone", "-b", git_branch, git_repo, code_mount_path],
                    capture_output=True, text=True, timeout=300
                )
            
            if result.returncode != 0:
                raise Exception(f"代码拉取失败: {result.stderr}")
            
            commit_result = subprocess.run(
                ["git", "-C", code_mount_path, "rev-parse", "HEAD"],
                capture_output=True, text=True
            )
            git_commit = commit_result.stdout.strip()[:8] if commit_result.returncode == 0 else ""
            logger.info(f"代码拉取完成 (commit: {git_commit})")
        else:
            logger.info("未配置代码源，跳过代码获取")
        
        # ========== 步骤3: 写入配置 ==========
        report_project_deployment_progress(deployment_id, status="configuring", progress=50,
                                           message="正在写入配置...", git_commit=git_commit)
        
        # 配置目录（独立于代码）
        config_dir = "/opt/project-config"
        os.makedirs(config_dir, exist_ok=True)
        
        configs = project.get('configs', [])
        env_file = os.path.join(config_dir, '.env')
        
        with open(env_file, 'w') as f:
            f.write(f"# 项目配置 - 自动生成\n")
            f.write(f"# 项目: {project_name}\n")
            f.write(f"# 版本: {project_version}\n")
            f.write(f"# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for config in configs:
                key = config.get('key')
                value = config.get('value')
                f.write(f"{key}={value}\n")
        
        logger.info(f"配置文件已写入: {env_file} ({len(configs)}项)")
        
        # ========== 步骤4: 停止旧容器 ==========
        report_project_deployment_progress(deployment_id, status="starting", progress=70,
                                           message="正在启动项目...")
        
        container_name = project.get('container_name', 'app')
        start_command = project.get('start_command', '/start.sh')
        container_config = project.get('container_config', {})
        
        logger.info(f"停止旧容器: {container_name}")
        subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=30)
        subprocess.run(["docker", "rm", container_name], capture_output=True, timeout=30)
        
        # ========== 步骤5: 启动新容器 ==========
        if image_full_name:
            cmd = ["docker", "run", "-d", "--name", container_name]
            
            # 重启策略
            restart_policy = container_config.get('restart_policy', 'unless-stopped')
            cmd.extend(["--restart", restart_policy])
            
            # GPU支持（NVIDIA runtime）- 你的场景需要这个
            runtime = container_config.get('runtime', '')
            if runtime == 'nvidia':
                cmd.extend(["--runtime", "nvidia"])
            
            # 网络模式（支持host模式）- 你的场景需要这个
            network_mode = container_config.get('network_mode', '')
            if network_mode == 'host':
                cmd.extend(["--network", "host"])
            else:
                # 端口映射（仅在非host模式下有效）
                ports = container_config.get('ports', {})
                for container_port, host_port in ports.items():
                    port_num = str(container_port).replace('/tcp', '').replace('/udp', '')
                    cmd.extend(["-p", f"{host_port}:{port_num}"])
            
            # 挂载代码目录到 /work
            cmd.extend(["-v", f"{code_mount_path}:{work_dir}"])
            
            # 挂载配置目录
            cmd.extend(["-v", f"{config_dir}:/config"])
            
            # 环境变量
            environment = container_config.get('environment', {})
            for key, value in environment.items():
                cmd.extend(["-e", f"{key}={value}"])
            
            # 特权模式（访问摄像头、串口等硬件需要）
            if container_config.get('privileged', False):
                cmd.append("--privileged")
            
            # 设备映射（如 /dev/video0, /dev/ttyUSB0）
            devices = container_config.get('devices', [])
            for device in devices:
                cmd.extend(["--device", device])
            
            # 额外的卷挂载
            volumes = container_config.get('volumes', {})
            for host_path, container_path in volumes.items():
                cmd.extend(["-v", f"{host_path}:{container_path}"])
            
            # 镜像名称
            cmd.append(image_full_name)
            
            # 启动命令
            # 支持你的格式: /bin/bash -c "cp /work/.../start.sh /start.sh && chmod +x /start.sh && /start.sh"
            if start_command:
                # 如果启动命令包含复杂脚本，用 bash -c 执行
                if '&&' in start_command or '|' in start_command or ';' in start_command:
                    cmd.extend(["/bin/bash", "-c", start_command])
                # 如果是 .sh 脚本，用 bash 执行（避免 ZIP 解压后可执行位丢失的问题）
                elif start_command.strip().endswith('.sh'):
                    cmd.extend(["/bin/bash", start_command.strip()])
                else:
                    cmd.append(start_command)
            
            logger.info(f"启动容器: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                raise Exception(f"容器启动失败: {result.stderr}")
            
            container_id = result.stdout.strip()
            logger.info(f"容器启动成功: {container_id[:12]}")
        else:
            logger.warning("未指定镜像，无法启动容器")
        
        # ========== 步骤6: 健康检查 ==========
        report_project_deployment_progress(deployment_id, status="running", progress=90,
                                           message="检查容器状态...")
        
        time.sleep(5)
        check_result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
            capture_output=True, text=True
        )
        
        if "Up" not in check_result.stdout:
            # 获取容器日志帮助排查
            log_result = subprocess.run(
                ["docker", "logs", "--tail", "20", container_name],
                capture_output=True, text=True
            )
            raise Exception(f"容器未能正常运行。日志: {log_result.stdout or log_result.stderr}")
        
        # ========== 步骤7: 完成 ==========
        logger.info(f"项目部署成功: {project_name} v{project_version}")
        report_project_deployment_progress(deployment_id, status="completed", progress=100,
                                           message="部署完成！", git_commit=git_commit)
        
        # 更新本地版本文件
        save_version(f"{project_name}-{project_version}")
        
        return True
        
    except subprocess.TimeoutExpired:
        error_msg = "部署操作超时"
        logger.error(f"部署失败: {error_msg}")
        report_project_deployment_progress(deployment_id, status="failed", progress=0,
                                           error_message=error_msg)
        return False
    except Exception as e:
        error_msg = str(e)
        logger.error(f"部署失败: {error_msg}")
        report_project_deployment_progress(deployment_id, status="failed", progress=0,
                                           error_message=error_msg)
        return False

def report_project_deployment_progress(deployment_id, **kwargs):
    """上报项目部署进度"""
    try:
        # 确保所有字符串都是正确的UTF-8编码
        def ensure_utf8(data):
            if isinstance(data, str):
                # 确保字符串是正确的UTF-8
                return data.encode('utf-8', errors='replace').decode('utf-8')
            elif isinstance(data, dict):
                return {k: ensure_utf8(v) for k, v in data.items()}
            elif isinstance(data, list):
                return [ensure_utf8(item) for item in data]
            return data
        
        clean_kwargs = ensure_utf8(kwargs)
        
        resp = requests.post(
            f"{CLOUD_SERVER}/project-deployments/{deployment_id}/update_progress/",
            json=clean_kwargs,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            timeout=5
        )
        resp.raise_for_status()
        logger.debug(f"上报项目部署进度: {clean_kwargs}")
    except Exception as e:
        logger.warning(f"上报项目部署进度失败: {e}")

# ==================== 配置管理功能 ====================
def sanitize_config_data(config_data):
    """清洗配置数据，移除非法字符"""
    import re
    
    def clean_string(s):
        if not isinstance(s, str):
            return s
        # 移除控制字符（0x00-0x1F, 0x7F-0x9F），保留换行符和制表符
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', s)
    
    def clean_dict(d):
        if isinstance(d, dict):
            return {clean_string(k): clean_dict(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [clean_dict(item) for item in d]
        elif isinstance(d, str):
            return clean_string(d)
        else:
            return d
    
    return clean_dict(config_data)


def apply_middleware_config(config_id, config_data):
    """应用MiddlewareServer配置"""
    import re
    import shutil
    from datetime import datetime
    
    try:
        # 清洗配置数据
        config_data = sanitize_config_data(config_data)
        
        # 默认代码路径，与Project.code_mount_path一致
        code_path = "/opt/project-code/MiddlewareServer"
        backup_path = f"/opt/config-backup/{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("=" * 60)
        logger.info("开始应用配置...")
        logger.info(f"配置ID: {config_id}")
        logger.info("=" * 60)
        
        # ========== 步骤1: 备份当前配置 ==========
        logger.info("步骤1: 备份当前配置...")
        os.makedirs(backup_path, exist_ok=True)
        
        files_to_backup = [
            f"{code_path}/config/devices.yml",
            f"{code_path}/server/server/settings.py",
            f"{code_path}/frontend/vite.config.ts"
        ]
        
        for file_path in files_to_backup:
            if os.path.exists(file_path):
                filename = os.path.basename(file_path)
                shutil.copy2(file_path, f"{backup_path}/{filename}")
                logger.info(f"  已备份: {filename}")
        
        # ========== 步骤2: 生成新的配置文件 ==========
        logger.info("步骤2: 生成新的配置文件...")
        
        # 2.1 生成 devices.yml
        logger.info("  生成 devices.yml...")
        generate_devices_yml(f"{code_path}/config/devices.yml", config_data['cameras'])
        
        # 2.2 修改 settings.py 中的 SOCKET_CONFIG
        logger.info("  修改 settings.py...")
        patch_settings_py(f"{code_path}/server/server/settings.py", config_data['plc'])
        
        # 2.3 修改 vite.config.ts 中的 proxy target
        logger.info("  修改 vite.config.ts...")
        patch_vite_config(f"{code_path}/frontend/vite.config.ts", config_data['backend'])
        
        # ========== 步骤3: 重启容器 ==========
        logger.info("步骤3: 重启容器...")
        subprocess.run(["docker", "restart", "middleware"], check=True, timeout=60)
        logger.info("  容器重启命令已执行")
        
        # ========== 步骤4: 等待服务启动 ==========
        logger.info("步骤4: 等待服务启动...")
        time.sleep(15)  # 等待15秒让服务启动
        
        # ========== 步骤5: 验证服务 ==========
        logger.info("步骤5: 验证服务...")
        try:
            resp = requests.get("http://localhost:8000/", timeout=10)
            if resp.status_code == 200:
                logger.info("  ✅ 服务启动成功")
            else:
                logger.warning(f"  ⚠️ 服务响应异常: {resp.status_code}")
        except Exception as e:
            logger.warning(f"  ⚠️ 服务验证失败（可能正在启动）: {e}")
        
        logger.info("=" * 60)
        logger.info("✅ 配置应用成功")
        logger.info(f"备份位置: {backup_path}")
        logger.info("=" * 60)
        
        return {"success": True}
        
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"❌ 配置应用失败: {e}")
        logger.error("=" * 60)
        
        # 尝试回滚
        try:
            logger.info("尝试回滚配置...")
            rollback_config(backup_path, code_path)
            subprocess.run(["docker", "restart", "middleware"], timeout=60)
            logger.info("配置已回滚")
        except Exception as rollback_error:
            logger.error(f"回滚失败: {rollback_error}")
        
        return {"success": False, "error": str(e)}

def generate_devices_yml(output_path, cameras_config):
    """生成devices.yml - 使用安全的方式构建YAML内容"""
    import re
    import yaml
    
    # 相机的默认配置
    camera_defaults = {
        "样品盘": {"exposure": 11000, "frame_rate": 3, "reverse_y": False},
        "前处理": {"exposure": 5600, "frame_rate": 6, "reverse_y": True},
        "孔板传送": {"exposure": 8000, "frame_rate": 3, "reverse_y": False},
        "提取-纯化": {"exposure": 12000, "frame_rate": 3, "reverse_y": False},
        "反应体系构建": {"exposure": 5000, "frame_rate": 3, "reverse_y": False}
    }
    
    # 清洗相机名称和IP，移除非法字符
    def clean_str(s):
        if not isinstance(s, str):
            return str(s)
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', s).strip()
    
    # 构建设备配置列表
    devices = []
    for name, ip in cameras_config.items():
        clean_name = clean_str(name)
        clean_ip = clean_str(ip)
        cfg = camera_defaults.get(clean_name, {"exposure": 10000, "frame_rate": 3, "reverse_y": False})
        
        device = {
            "name": clean_name,
            "device": "devices.HiKDevice",
            "params": clean_ip,
            "config": {
                "ExposureTime": cfg['exposure'],
                "AcquisitionFrameRate": cfg['frame_rate']
            }
        }
        if cfg.get('reverse_y'):
            device['config']['ReverseY'] = True
        devices.append(device)
    
    # 使用yaml库序列化，确保格式正确
    yaml_content = "## devices.yml - Auto generated by Device Agent\n\n"
    yaml_content += yaml.dump(devices, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    # 验证生成的YAML是否有效
    try:
        yaml.safe_load(yaml_content)
        logger.info("YAML验证通过")
    except yaml.YAMLError as e:
        logger.error(f"生成的YAML无效: {e}")
        raise ValueError(f"生成的YAML无效: {e}")
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(yaml_content)
    
    logger.info(f"devices.yml 已生成: {output_path}")

def patch_settings_py(file_path, plc_config):
    """修改settings.py中的SOCKET_CONFIG - 使用安全的方式"""
    import re
    
    # 读取文件
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 构建新的 SOCKET_CONFIG（使用列表拼接避免编码问题）
    new_lines = [
        'SOCKET_CONFIG = {',
        '    "reverse": {',
        f'        "HOST": "{plc_config["host"]}",',
        f'        "PORT": {plc_config["port"]},',
        '    },',
        '}'
    ]
    new_socket_config = "\n".join(new_lines)
    
    # 正则替换 SOCKET_CONFIG (匹配多行)
    pattern = r'SOCKET_CONFIG\s*=\s*\{[^}]*"reverse"[^}]*\}[^}]*\}'
    content = re.sub(pattern, new_socket_config, content, flags=re.DOTALL)
    
    # 写入文件
    with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    
    logger.info(f"settings.py 已修改: {file_path}")

def patch_vite_config(file_path, backend_config):
    """修改vite.config.ts中的proxy target - 使用安全的方式"""
    import re
    
    # 读取文件
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 构建替换字符串
    host = str(backend_config["host"])
    port = int(backend_config["port"])
    replacement = f'target: "http://{host}:{port}"'
    
    # 替换 target 行
    pattern = r'target:\s*"http://[^"]*"'
    content = re.sub(pattern, replacement, content)
    
    # 写入文件
    with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    
    logger.info(f"vite.config.ts 已修改: {file_path}")

def rollback_config(backup_path, code_path):
    """回滚配置"""
    import shutil
    
    files_to_restore = [
        ("devices.yml", f"{code_path}/config/devices.yml"),
        ("settings.py", f"{code_path}/server/server/settings.py"),
        ("vite.config.ts", f"{code_path}/frontend/vite.config.ts")
    ]
    
    for filename, dest_path in files_to_restore:
        backup_file = f"{backup_path}/{filename}"
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, dest_path)
            logger.info(f"已恢复: {filename}")

def check_and_apply_config(device_id):
    """检查并应用待处理的配置"""
    try:
        resp = requests.get(
            f"{CLOUD_SERVER}/devices/{device_id}/pending_config/",
            timeout=10
        )
        
        if resp.status_code == 200:
            pending_config = resp.json()
            if pending_config.get('has_pending'):
                logger.info("检测到待应用的配置...")
                config_id = pending_config['config_id']
                config_data = pending_config['config_data']
                
                # 应用配置
                result = apply_middleware_config(config_id, config_data)
                
                # 上报应用结果
                requests.post(
                    f"{CLOUD_SERVER}/devices/{device_id}/config_result/",
                    json={
                        'config_id': config_id,
                        'success': result['success'],
                        'error': result.get('error', '')
                    },
                    timeout=10
                )
                
                if result['success']:
                    logger.info("✅ 配置应用成功并已上报")
                else:
                    logger.error(f"❌ 配置应用失败: {result.get('error')}")
    except Exception as e:
        logger.warning(f"检查配置时出错: {e}")

# ==================== 主循环 ====================
def main():
    device_id = get_device_id()
    logger.info("=" * 60)
    logger.info(f"Device Agent 启动")
    logger.info(f"设备ID: {device_id}")
    logger.info(f"Agent版本: {AGENT_VERSION}")
    logger.info(f"项目版本: {get_current_version()}")
    logger.info(f"云端服务器: {CLOUD_SERVER}")
    logger.info(f"心跳间隔: {HEARTBEAT_INTERVAL}秒")
    logger.info(f"任务轮询间隔: {TASK_POLL_INTERVAL}秒")
    logger.info(f"日志上传间隔: {LOG_UPLOAD_INTERVAL}秒")
    logger.info(f"更新检查间隔: {UPDATE_CHECK_INTERVAL}秒")
    logger.info("=" * 60)
    
    last_heartbeat = 0
    last_task_poll = 0
    last_log_upload = 0
    last_update_check = 0
    last_config_check = 0
    
    while True:
        try:
            current_time = time.time()
            
            # 定时发送心跳
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                logger.debug("发送心跳...")
                command = send_heartbeat()
                last_heartbeat = current_time
                
                # 处理心跳返回的命令
                cmd_type = command.get("command")
                if cmd_type == "update":
                    task_id = command.get("task_id")
                    version = command.get("version")
                    logger.info(f"收到更新命令: 版本 {version}")
                    execute_update(task_id, version)
                elif cmd_type == "update_agent":
                    # 收到服务器推送的 Agent 更新命令
                    logger.info("收到 Agent 更新命令")
                    apply_agent_update()
            
            # 定时轮询部署任务
            if current_time - last_task_poll >= TASK_POLL_INTERVAL:
                logger.debug("轮询部署任务...")
                
                # 轮询Docker镜像部署任务
                tasks = poll_deployment_tasks()
                for task in tasks:
                    logger.info(f"发现待执行的部署任务: #{task['id']}")
                    execute_deployment(task)
                
                # 轮询项目部署任务
                project_deployments = poll_project_deployments()
                for deployment in project_deployments:
                    logger.info(f"发现待执行的项目部署: #{deployment['id']}")
                    execute_project_deployment(deployment)
                
                last_task_poll = current_time
            
            # 定时检查待应用的配置
            if current_time - last_config_check >= CONFIG_CHECK_INTERVAL:
                logger.debug("检查待应用的配置...")
                check_and_apply_config(device_id)
                last_config_check = current_time
            
            # 定时上传容器日志
            if current_time - last_log_upload >= LOG_UPLOAD_INTERVAL:
                logger.debug("上传容器日志...")
                upload_container_logs("middleware")
                last_log_upload = current_time
            
            # 定时检查 Agent 更新（每小时）
            if current_time - last_update_check >= UPDATE_CHECK_INTERVAL:
                logger.debug("检查 Agent 更新...")
                new_version = check_agent_update()
                if new_version:
                    apply_agent_update()
                last_update_check = current_time
            
            # 短暂休眠，避免CPU占用过高
            time.sleep(1)
            
        except KeyboardInterrupt:
            logger.info("收到中断信号，停止Device Agent")
            break
        except Exception as e:
            logger.error(f"主循环错误: {e}", exc_info=True)
            time.sleep(10)  # 发生错误后等待10秒再继续

if __name__ == "__main__":
    main()


