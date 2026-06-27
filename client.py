# 客户端 node_client.py（修复接口报错完整版）
import time
import hashlib
import uuid
import subprocess
import random
import requests
import sys
import shutil
import tempfile
import threading
import secrets
from pathlib import Path
import os
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
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

CLIENT_MANAGE_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>节点控制台</title></head>
<body>
  <main>
    <h1>节点控制台</h1>
    <section id="overview">运行状态 / 服务连接 / 最后心跳</section>
    <section id="capacity">总容量 / 已使用 / 未使用 / 目录状态</section>
    <section id="storage">添加目录 / 重新检测</section>
    <section id="earnings">收益 / 提交提现 / 提现记录</section>
    <section id="controls">停止节点 / 重启节点</section>
  </main>
  <script>
    const CSRF_TOKEN = "__CSRF_TOKEN__";
    const api = (path, options = {}) => {
      const opts = {...options};
      if (opts.method && opts.method.toUpperCase() !== "GET") {
        opts.headers = {...(opts.headers || {}), "Content-Type": "application/json", "X-CSRF-Token": CSRF_TOKEN};
        if (!opts.body) opts.body = "{}";
      }
      return fetch(path, opts).then(res => res.json());
    };
    async function refreshAll(){
      await Promise.all([api("/api/status"), api("/api/earnings"), api("/api/withdrawals")]);
    }
    async function stopNode(){ if(confirm("确认停止节点？")) await api("/api/control/stop", {method:"POST"}); }
    async function restartNode(){ if(confirm("确认重启节点？")) await api("/api/control/restart", {method:"POST"}); }
  </script>
</body>
</html>
"""


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
        storage_used_gb = get_local_disk_use("")
        return {
            "storage_path": "",
            "storage_status": "unavailable",
            "storage_error": "未指定存储目录",
            "storage_total_gb": 0,
            "storage_used_gb": storage_used_gb,
            "storage_free_gb": 0,
        }
    try:
        path = ensure_storage_dir(storage_dir)
        if path is None or not path.is_dir():
            raise RuntimeError("存储路径不是目录")
        probe_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".filezall_write_probe_",
                dir=path,
                delete=False,
            ) as probe:
                probe_path = Path(probe.name)
                probe.write("ok")
        finally:
            if probe_path is not None:
                probe_path.unlink(missing_ok=True)
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


def create_client_state(server_url, user_addr, node_mac, storage_dir, manage_port):
    return {
        "server_url": server_url,
        "user_addr": user_addr,
        "node_mac": node_mac,
        "storage_dir": storage_dir,
        "manage_port": manage_port,
        "csrf_token": secrets.token_urlsafe(24),
        "running": True,
        "last_heartbeat": "",
        "last_error": "",
        "storage": inspect_storage_dir(storage_dir),
    }


def client_status_payload(state):
    return {
        "server_url": state["server_url"],
        "user_addr": state["user_addr"],
        "node_mac": state["node_mac"],
        "running": state["running"],
        "last_heartbeat": state["last_heartbeat"],
        "last_error": state["last_error"],
        "storage": state["storage"],
    }


def build_heartbeat_payload(state, upload_bw):
    storage_info = inspect_storage_dir(state["storage_dir"])
    state["storage"] = storage_info
    return {
        "user_addr": state["user_addr"],
        "node_mac": state["node_mac"],
        "disk_used": storage_info["storage_used_gb"],
        "upload_bw": upload_bw,
        **storage_info,
    }


def ensure_success_response(response):
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
        return
    status_code = int(getattr(response, "status_code", 200) or 200)
    if status_code >= 400:
        raise RuntimeError(f"heartbeat failed with HTTP {status_code}")


def report_heartbeat(state, upload_bw, post_func=requests.post):
    payload = build_heartbeat_payload(state, upload_bw)
    try:
        response = post_func(f"{state['server_url']}/heartbeat", json=payload, timeout=10)
        ensure_success_response(response)
        state["running"] = True
        state["last_heartbeat"] = time.strftime("%Y-%m-%d %H:%M:%S")
        state["last_error"] = ""
        return True, payload
    except Exception as exc:
        state["running"] = False
        state["last_error"] = str(exc)
        return False, payload


def make_manage_handler(state):
    class ManageHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _route_path(self):
            return urlparse(self.path).path

        def _is_allowed_host(self, value):
            if not value:
                return False
            host = value.strip().lower()
            allowed_names = {"127.0.0.1", "localhost", "::1"}
            allowed_ports = {"", str(state.get("manage_port", "")), str(getattr(self.server, "server_port", ""))}
            if host == "::1":
                return True
            if host.startswith("[::1]"):
                port = ""
                if host.startswith("[::1]:"):
                    port = host[len("[::1]:"):]
                return port in allowed_ports
            if ":" in host:
                name, port = host.rsplit(":", 1)
            else:
                name, port = host, ""
            return name in allowed_names and port in allowed_ports

        def _is_allowed_url_header(self, value):
            if not value:
                return True
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return False
            return self._is_allowed_host(parsed.netloc)

        def _validate_host(self):
            if self._is_allowed_host(self.headers.get("Host", "")):
                return True
            self._send_json({"ok": False, "error": "invalid host"}, status=403)
            return False

        def _validate_mutation_source(self):
            for header_name in ("Origin", "Referer"):
                if not self._is_allowed_url_header(self.headers.get(header_name, "")):
                    self._send_json({"ok": False, "error": "invalid request origin"}, status=403)
                    return False
            return True

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                self._send_json({"ok": False, "error": "invalid content length"}, status=400)
                return None
            if length < 0:
                self._send_json({"ok": False, "error": "invalid content length"}, status=400)
                return None
            if length <= 0:
                return {}
            try:
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body)
                if not isinstance(data, dict):
                    self._send_json({"ok": False, "error": "json body must be an object"}, status=400)
                    return None
                return data
            except Exception:
                self._send_json({"ok": False, "error": "invalid json body"}, status=400)
                return None

        def _read_mutation_json(self):
            if not self._validate_mutation_source():
                return None
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_json({"ok": False, "error": "content type must be application/json"}, status=400)
                return None
            data = self._read_json()
            if data is None:
                return None
            token = self.headers.get("X-CSRF-Token") or data.get("csrf_token")
            if token != state.get("csrf_token"):
                self._send_json({"ok": False, "error": "invalid csrf token"}, status=403)
                return None
            return data

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._validate_host():
                return
            path = self._route_path()
            if path == "/":
                self._send_html(CLIENT_MANAGE_HTML.replace("__CSRF_TOKEN__", state["csrf_token"]))
            elif path == "/api/status":
                self._send_json({"ok": True, "data": client_status_payload(state)})
            elif path == "/api/earnings":
                self._send_json({"ok": True, "data": [], "message": "收益接口将在后续任务完成"})
            elif path == "/api/withdrawals":
                self._send_json({"ok": True, "data": [], "message": "提现接口将在后续任务完成"})
            else:
                self._send_json({"ok": False, "error": "not found"}, status=404)

        def do_POST(self):
            if not self._validate_host():
                return
            path = self._route_path()
            data = self._read_mutation_json()
            if data is None:
                return
            if path == "/api/storage":
                storage_dir = str(data.get("storage_dir") or data.get("path") or "").strip()
                if storage_dir:
                    state["storage_dir"] = storage_dir
                state["storage"] = inspect_storage_dir(state["storage_dir"])
                self._send_json({"ok": True, "data": client_status_payload(state)})
            elif path == "/api/refresh":
                state["storage"] = inspect_storage_dir(state["storage_dir"])
                self._send_json({"ok": True, "data": client_status_payload(state)})
            elif path == "/api/control/stop":
                self._send_json({"ok": True, "message": "停止节点将在后续任务完成"})
            elif path == "/api/control/restart":
                self._send_json({"ok": True, "message": "重启节点将在后续任务完成"})
            elif path == "/api/withdrawals":
                self._send_json({"ok": True, "message": "提交提现将在后续任务完成"})
            else:
                self._send_json({"ok": False, "error": "not found"}, status=404)

    return ManageHandler


def start_manage_server(state):
    server = ThreadingHTTPServer(("127.0.0.1", int(state["manage_port"])), make_manage_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

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
        safe_print(f"📁 节点存储目录：{Path(NODE_STORAGE_DIR).expanduser()}")
    device_mac = get_device_mac()
    # 根据设备MAC生成唯一用户标识
    user_addr = "NODE_" + hashlib.md5(device_mac.encode()).hexdigest()[:12]
    state = create_client_state(SERVER_URL, user_addr, device_mac, NODE_STORAGE_DIR, MANAGE_PORT)
    manage_server = None
    try:
        manage_server = start_manage_server(state)
        safe_print(f"🌐 节点管理页：http://127.0.0.1:{MANAGE_PORT}")
    except Exception as exc:
        state["last_error"] = f"管理页启动失败：{exc}"
        safe_print(f"❌ 管理页启动失败：{exc}")

    try:
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
            upload_bw = round(random.uniform(0.2,3.0),2)
            heartbeat_ok, payload = report_heartbeat(state, upload_bw)
            if heartbeat_ok:
                safe_print(f"✅ 心跳上报成功｜当前存储：{payload['storage_used_gb']}G｜上行带宽：{upload_bw}MB/s")
            else:
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
    finally:
        if manage_server is not None:
            manage_server.shutdown()
            manage_server.server_close()


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
