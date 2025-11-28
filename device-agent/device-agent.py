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
CLOUD_SERVER = os.getenv("CLOUD_SERVER", "http://your-server.com/api")
DEVICE_ID_FILE = os.getenv("DEVICE_ID_FILE", "/etc/device-id")
VERSION_FILE = os.getenv("VERSION_FILE", "/work/.version")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))  # 心跳间隔（秒）
TASK_POLL_INTERVAL = int(os.getenv("TASK_POLL_INTERVAL", "10"))  # 任务轮询间隔（秒）
LOG_UPLOAD_INTERVAL = int(os.getenv("LOG_UPLOAD_INTERVAL", "60"))  # 日志上传间隔（秒）

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
                    uptime = f"{days}天 {hours}小时"
                elif hours > 0:
                    uptime = f"{hours}小时 {minutes}分钟"
                else:
                    uptime = f"{minutes}分钟"
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
        **metrics,
        **container_info,
        **health_info
    }
    
    try:
        resp = requests.post(
            f"{CLOUD_SERVER}/devices/{device_id}/heartbeat/",
            json=data,
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
def collect_container_logs(container_name="middleware", lines=100):
    """收集容器日志"""
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        # 合并 stdout 和 stderr
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
    
    # 清空目标目录（保留.env配置文件）
    for item in os.listdir(target_dir):
        item_path = os.path.join(target_dir, item)
        if item == '.env':  # 保留配置文件
            continue
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)
    
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
        requests.post(
            f"{CLOUD_SERVER}/project-deployments/{deployment_id}/update_progress/",
            json=kwargs,
            timeout=5
        )
        logger.debug(f"上报项目部署进度: {kwargs}")
    except Exception as e:
        logger.warning(f"上报项目部署进度失败: {e}")

# ==================== 主循环 ====================
def main():
    device_id = get_device_id()
    logger.info("=" * 60)
    logger.info(f"Device Agent 启动")
    logger.info(f"设备ID: {device_id}")
    logger.info(f"当前版本: {get_current_version()}")
    logger.info(f"云端服务器: {CLOUD_SERVER}")
    logger.info(f"心跳间隔: {HEARTBEAT_INTERVAL}秒")
    logger.info(f"任务轮询间隔: {TASK_POLL_INTERVAL}秒")
    logger.info(f"日志上传间隔: {LOG_UPLOAD_INTERVAL}秒")
    logger.info("=" * 60)
    
    last_heartbeat = 0
    last_task_poll = 0
    last_log_upload = 0
    
    while True:
        try:
            current_time = time.time()
            
            # 定时发送心跳
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                logger.debug("发送心跳...")
                command = send_heartbeat()
                last_heartbeat = current_time
                
                # 处理心跳返回的命令
                if command.get("command") == "update":
                    task_id = command.get("task_id")
                    version = command.get("version")
                    logger.info(f"收到更新命令: 版本 {version}")
                    execute_update(task_id, version)
            
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
            
            # 定时上传容器日志
            if current_time - last_log_upload >= LOG_UPLOAD_INTERVAL:
                logger.debug("上传容器日志...")
                upload_container_logs("middleware")
                last_log_upload = current_time
            
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


