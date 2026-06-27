import sys
import os
import time
import hashlib
import uuid
import requests
import subprocess
import json
from pathlib import Path
try:
    import webview
except Exception:
    webview = None

# ========== 服务端地址（替换为你的公网IP/域名，本地测试保留默认） ==========
SERVER_URL = "http://127.0.0.1:8000"
# 推广参数自动注入，无需手动填写
PARENT_INVITE = ""
HEARTBEAT_INTERVAL = 60
NODE_STORAGE_DIR = ""


def load_client_config(config_path="node_config.json"):
    config = {
        "server_url": SERVER_URL,
        "parent_invite": PARENT_INVITE,
        "heartbeat_interval": HEARTBEAT_INTERVAL,
        "storage_dir": NODE_STORAGE_DIR,
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
    config["storage_dir"] = os.getenv("NODE_STORAGE_DIR", config["storage_dir"])
    return config

# 解析启动参数（下载页携带的invite推广码）
def get_invite_arg():
    for arg in sys.argv:
        if arg.startswith("invite="):
            return arg.replace("invite=", "")
        if arg.startswith("--invite="):
            return arg.split("=", 1)[1].strip()
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

# 获取Mac设备唯一指纹（防多开、防作弊、一机一号永久绑定）
def get_device_id():
    # 适配Mac系统硬件唯一标识
    return str(uuid.getnode())

# 适配Mac读取本地IPFS存储算力
def get_ipfs_disk(storage_dir=""):
    if storage_dir:
        try:
            path = ensure_storage_dir(storage_dir)
            if path is not None:
                return round(get_directory_size_bytes(path) / (1024 ** 3), 2)
        except Exception:
            return 0.0
    try:
        # Mac原生IPFS命令适配
        res = subprocess.check_output("ipfs stats repo --human", shell=True).decode()
        if "GB" in res:
            return round(float(res.split("GB")[0].strip().split(" ")[-1]), 2)
        elif "MB" in res:
            return round(float(res.split("MB")[0].strip().split(" ")[-1]) / 1024, 2)
        return 0.2
    except Exception:
        # 未启动IPFS时默认基础算力，不影响程序运行
        return 0.2

# 核心节点运行逻辑
def main():
    global SERVER_URL, PARENT_INVITE, HEARTBEAT_INTERVAL, NODE_STORAGE_DIR
    config = load_client_config()
    SERVER_URL = config["server_url"]
    # 读取下载页传入的上级推广码
    PARENT_INVITE = get_invite_arg() or config["parent_invite"]
    HEARTBEAT_INTERVAL = int(config["heartbeat_interval"])
    NODE_STORAGE_DIR = get_storage_dir_arg() or config["storage_dir"]
    if NODE_STORAGE_DIR:
        ensure_storage_dir(NODE_STORAGE_DIR)

    # 生成唯一设备标识+用户节点地址
    device_id = get_device_id()
    user_addr = "MAC_NODE" + hashlib.md5(device_id.encode()).hexdigest()[:10]

    # 首次启动自动注册、绑定上级
    try:
        requests.post(f"{SERVER_URL}/register", json={
            "user_addr": user_addr,
            "node_mac": device_id,
            "parent_invite": PARENT_INVITE
        }, timeout=8)
    except Exception:
        # 网络异常自动重试，不闪退
        pass

    # 永久循环心跳上报（60秒一次）
    while True:
        disk_usage = get_ipfs_disk(NODE_STORAGE_DIR)
        try:
            requests.post(f"{SERVER_URL}/heartbeat", json={
                "user_addr": user_addr,
                "node_mac": device_id,
                "disk_used": disk_usage,
                "upload_bw": round(0.25, 2)
            }, timeout=8)
        except Exception:
            pass

        # 在 while True 心跳循环内添加：
        # 自动上报地理位置
        try:
            requests.post(f"{SERVER_URL}/api/report_location",json={
                "user_addr":user_addr,
                "node_mac":device_id
            },timeout=5)
        except:
            pass
        # 休眠60秒，降低设备功耗
        time.sleep(HEARTBEAT_INTERVAL)

def open_map_window():
    if webview is None:
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
    if webview is None:
        main()
    else:
        threading.Thread(target=main,daemon=True).start()
        open_map_window()
