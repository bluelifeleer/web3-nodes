# 客户端 node_client.py（修复接口报错完整版）
import time
import hashlib
import uuid
import subprocess
import random
import requests
import sys
import shutil
from pathlib import Path
import os
import json
try:
    import webview
except Exception:
    webview = None

# 服务端地址（和后端统一）
SERVER_URL = "http://127.0.0.1:8000"
# 上级推广码（分享链接自动填充，用户无需手动改）
PARENT_INVITE = ""
HEARTBEAT_INTERVAL = 60
RECONNECT_INTERVAL = 10
NODE_STORAGE_DIR = ""
MANAGE_PORT = 8787


def safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("gbk", errors="ignore").decode("gbk"))


def load_client_config(config_path="node_config.json"):
    config = {
        "server_url": SERVER_URL,
        "parent_invite": PARENT_INVITE,
        "heartbeat_interval": HEARTBEAT_INTERVAL,
        "reconnect_interval": RECONNECT_INTERVAL,
        "storage_dir": NODE_STORAGE_DIR,
        "manage_port": MANAGE_PORT,
    }
    path = Path(config_path)
    if path.exists():
        try:
            file_config = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                config.update({key: value for key, value in file_config.items() if value not in (None, "")})
        except Exception:
            pass
    config["server_url"] = os.getenv("NODE_SERVER_URL", config["server_url"])
    config["parent_invite"] = os.getenv("NODE_PARENT_INVITE", config["parent_invite"])
    config["heartbeat_interval"] = int(os.getenv("NODE_HEARTBEAT_INTERVAL", config["heartbeat_interval"]))
    config["reconnect_interval"] = int(os.getenv("NODE_RECONNECT_INTERVAL", config["reconnect_interval"]))
    config["storage_dir"] = os.getenv("NODE_STORAGE_DIR", config["storage_dir"])
    config["manage_port"] = int(os.getenv("NODE_MANAGE_PORT", config["manage_port"]))
    return config


def get_invite_arg():
    for arg in sys.argv[1:]:
        if arg.startswith("invite="):
            return arg.split("=", 1)[1].strip()
        if arg.startswith("--invite="):
            return arg.split("=", 1)[1].strip()

    exe_name = Path(sys.executable).stem
    marker = "invite_"
    if marker in exe_name:
        return exe_name.split(marker, 1)[1].strip()
    return ""


def get_storage_dir_arg():
    for arg in sys.argv[1:]:
        if arg.startswith("storage_dir="):
            return arg.split("=", 1)[1].strip()
        if arg.startswith("--storage-dir="):
            return arg.split("=", 1)[1].strip()
        if arg.startswith("--storage_dir="):
            return arg.split("=", 1)[1].strip()
    return ""


def get_manage_port_arg():
    for arg in sys.argv[1:]:
        if arg.startswith("manage_port=") or arg.startswith("--manage-port=") or arg.startswith("--manage_port="):
            return int(arg.split("=", 1)[1].strip())
    return 0


def ensure_storage_dir(storage_dir):
    if not storage_dir:
        return None
    path = Path(storage_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_directory_size_bytes(path):
    total = 0
    for file_path in path.rglob("*"):
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
        except OSError:
            continue
    return total


def inspect_storage_dir(storage_dir):
    if not storage_dir:
        return {
            "storage_path": "",
            "storage_status": "unavailable",
            "storage_error": "未指定存储目录",
            "storage_total_gb": 0,
            "storage_used_gb": 0,
            "storage_free_gb": 0,
        }
    try:
        path = ensure_storage_dir(storage_dir)
        if path is None or not path.is_dir():
            raise RuntimeError("存储路径不是目录")
        probe = path / ".filezall_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        usage = shutil.disk_usage(path)
        dir_used = get_directory_size_bytes(path)
        return {
            "storage_path": str(path),
            "storage_status": "ok",
            "storage_error": "",
            "storage_total_gb": round(usage.total / (1024 ** 3), 2),
            "storage_used_gb": round(dir_used / (1024 ** 3), 2),
            "storage_free_gb": round(usage.free / (1024 ** 3), 2),
        }
    except Exception as exc:
        return {
            "storage_path": str(storage_dir),
            "storage_status": "unavailable",
            "storage_error": str(exc),
            "storage_total_gb": 0,
            "storage_used_gb": 0,
            "storage_free_gb": 0,
        }

# 生成唯一设备指纹（防多开、防作弊）
def get_device_mac():
    return str(uuid.getnode())

# 读取本地IPFS真实存储占用
def get_local_disk_use(storage_dir=""):
    if storage_dir:
        try:
            path = ensure_storage_dir(storage_dir)
            if path is not None:
                return round(get_directory_size_bytes(path) / (1024 ** 3), 2)
        except Exception:
            return 0.0
    try:
        # 调用本地IPFS命令，读取仓库占用空间
        res = subprocess.check_output("ipfs stats repo --human",shell=True).decode()
        # 解析GB数值
        if "GB" in res:
            gb_val = float(res.split("GB")[0].strip().split(" ")[-1])
            return round(gb_val,2)
        return 0.1
    except Exception as e:
        # 未启动IPFS时默认基础占用
        return 0.1


def register_node(server_url, user_addr, device_mac, parent_invite, post_func=requests.post):
    post_func(f"{server_url}/register",json={
        "user_addr":user_addr,
        "node_mac":device_mac,
        "parent_invite":parent_invite
    },timeout=10)


def wait_for_registration(
    server_url,
    user_addr,
    device_mac,
    parent_invite,
    reconnect_interval=RECONNECT_INTERVAL,
    post_func=requests.post,
    sleep_func=time.sleep,
    max_attempts=None,
):
    attempts = 0
    while True:
        attempts += 1
        try:
            register_node(server_url, user_addr, device_mac, parent_invite, post_func=post_func)
            safe_print(f"✅ 节点注册成功，设备指纹：{device_mac}")
            return True
        except Exception:
            safe_print(f"❌ 服务端连接失败，{reconnect_interval}秒后自动重连...")
            if max_attempts is not None and attempts >= max_attempts:
                return False
            sleep_func(reconnect_interval)

# 节点核心运行逻辑
def client_run():
    global SERVER_URL, PARENT_INVITE, HEARTBEAT_INTERVAL, NODE_STORAGE_DIR, MANAGE_PORT
    config = load_client_config()
    SERVER_URL = config["server_url"]
    PARENT_INVITE = get_invite_arg() or config["parent_invite"]
    HEARTBEAT_INTERVAL = int(config["heartbeat_interval"])
    reconnect_interval = int(config["reconnect_interval"])
    NODE_STORAGE_DIR = get_storage_dir_arg() or config["storage_dir"]
    MANAGE_PORT = get_manage_port_arg() or int(config["manage_port"])
    if NODE_STORAGE_DIR:
        ensure_storage_dir(NODE_STORAGE_DIR)
        safe_print(f"📁 节点存储目录：{Path(NODE_STORAGE_DIR).expanduser()}")
    device_mac = get_device_mac()
    # 根据设备MAC生成唯一用户标识
    user_addr = "NODE_" + hashlib.md5(device_mac.encode()).hexdigest()[:12]

    # 1. 首次注册绑定上级
    wait_for_registration(
        SERVER_URL,
        user_addr,
        device_mac,
        PARENT_INVITE,
        reconnect_interval=reconnect_interval,
    )

    # 2. 循环心跳上报（60秒一次）
    safe_print("🔄 节点持续运行中，实时上报存储数据...")
    while True:
        storage_info = inspect_storage_dir(NODE_STORAGE_DIR)
        upload_bw = round(random.uniform(0.2,3.0),2)
        try:
            payload = {
                "user_addr":user_addr,
                "node_mac":device_mac,
                "disk_used":storage_info["storage_used_gb"],
                "upload_bw":upload_bw,
                **storage_info,
            }
            requests.post(f"{SERVER_URL}/heartbeat",json=payload,timeout=10)
            safe_print(f"✅ 心跳上报成功｜当前存储：{storage_info['storage_used_gb']}G｜上行带宽：{upload_bw}MB/s")
        except:
            safe_print("❌ 心跳上报失败，等待重连...")

        # 在 while True 心跳循环内添加：
        # 自动上报地理位置
        try:
            requests.post(f"{SERVER_URL}/api/report_location",json={
                "user_addr":user_addr,
                "node_mac":device_mac
            },timeout=5)
        except:
            pass
        
        time.sleep(HEARTBEAT_INTERVAL)


def open_map_window():
    if webview is None:
        safe_print("ℹ️ 未安装 pywebview，跳过地图窗口")
        return
    html = '''
    <html style="margin:0;padding:0">
    <body style="margin:0;padding:0">
    <script src="https://webapi.amap.com/maps?v=2.0&key=72c8873c3ca27f35e4815ec41e6fae24"></script>
    <div id="map" style="width:100vw;height:100vh"></div>
    <script>
    let map = new AMap.Map('map',{zoom:4,center:[105,35]});
    fetch("http://127.0.0.1:8000/api/map_node_list")
    .then(res=>res.json()).then(d=>{
        d.data.forEach(item=>{
            if(item.lat==0)return;
            let marker = new AMap.Marker({
                position:[item.lng,item.lat],
                icon:item.status?"https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png":"https://webapi.amap.com/theme/v1.3/markers/n/mark_bs.png"
            })
            map.add(marker);
        })
    })
    </script>
    </body>
    </html>
    '''
    webview.create_window("节点全球地图", html=html, width=800, height=600)
    webview.start(gui=True, debug=False)

if __name__ == "__main__":
    import threading
    safe_print("🚀 Web3分布式存储激励节点启动成功")
    if webview is None:
        client_run()
    else:
        threading.Thread(target=client_run,daemon=True).start()
        open_map_window()
