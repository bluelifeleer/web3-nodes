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
  <style>
    :root {
      color-scheme: light;
      font-family: "Segoe UI", Arial, sans-serif;
      background: #f4f7fb;
      color: #14213d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #f7f9fc 0%, #edf3fb 100%);
      color: #14213d;
    }
    main {
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: 30px;
    }
    p.subhead {
      margin: 0 0 24px;
      color: #4f5d75;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }
    section {
      background: #ffffff;
      border: 1px solid #d8e2ef;
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(20, 33, 61, 0.06);
    }
    section.wide {
      grid-column: 1 / -1;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 18px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .stat {
      border: 1px solid #e3e9f3;
      border-radius: 8px;
      padding: 12px;
      background: #f9fbff;
      min-height: 86px;
    }
    .label {
      display: block;
      font-size: 12px;
      color: #6b7a90;
      margin-bottom: 8px;
    }
    .value {
      font-size: 22px;
      font-weight: 600;
      word-break: break-word;
    }
    .muted {
      color: #6b7a90;
      font-size: 13px;
    }
    .status-pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
      background: #d9f5e8;
      color: #166534;
    }
    .status-pill.offline {
      background: #fde2e1;
      color: #b42318;
    }
    .toolbar, form {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    input, select, button {
      min-height: 40px;
      border-radius: 8px;
      border: 1px solid #c7d3e3;
      padding: 0 12px;
      font: inherit;
    }
    input, select {
      flex: 1 1 180px;
      background: #fff;
    }
    button {
      cursor: pointer;
      background: #1769ff;
      color: #fff;
      border: 0;
      min-width: 120px;
      font-weight: 600;
    }
    button.secondary {
      background: #eef3fb;
      color: #17325c;
      border: 1px solid #c7d3e3;
    }
    button.danger {
      background: #d92d20;
    }
    button:disabled {
      opacity: 0.6;
      cursor: wait;
    }
    .list {
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
    }
    .list li {
      border-top: 1px solid #eef2f7;
      padding: 12px 0;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }
    .list li:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .message {
      min-height: 22px;
      margin-top: 12px;
      font-size: 14px;
      color: #17325c;
    }
    .message.error {
      color: #b42318;
    }
    .mono {
      font-family: Consolas, "Courier New", monospace;
      word-break: break-all;
    }
    @media (max-width: 720px) {
      main { padding: 16px; }
      h1 { font-size: 26px; }
      .list li {
        flex-direction: column;
        align-items: stretch;
      }
      button {
        width: 100%;
      }
    }
  </style>
  <main>
    <h1>节点控制台</h1>
    <p class="subhead">本地管理页只访问本机接口，不直接暴露服务端地址。</p>

    <div class="grid">
      <section>
        <h2>运行概览</h2>
        <div class="stats">
          <div class="stat">
            <span class="label">运行状态</span>
            <div id="runningState" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">服务端连接</span>
            <div id="serverUrl" class="value muted mono">-</div>
          </div>
          <div class="stat">
            <span class="label">最后心跳</span>
            <div id="lastHeartbeat" class="value muted">-</div>
          </div>
          <div class="stat">
            <span class="label">最近状态</span>
            <div id="lastMessage" class="value muted">-</div>
          </div>
        </div>
      </section>

      <section>
        <h2>目录健康与容量</h2>
        <div class="stats">
          <div class="stat">
            <span class="label">目录状态</span>
            <div id="storageState" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">总容量</span>
            <div id="storageTotal" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">已使用</span>
            <div id="storageUsed" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">可用容量</span>
            <div id="storageFree" class="value">-</div>
          </div>
        </div>
        <div class="muted mono" id="storagePath">-</div>
      </section>

      <section class="wide">
        <h2>存储目录管理</h2>
        <form id="storageForm">
          <input id="storageDirInput" name="storage_dir" placeholder="输入新的本地存储目录，例如 D:\\web3-node-data" />
          <button type="submit">添加目录 / 更新目录</button>
          <button class="secondary" id="refreshButton" type="button">重新检测</button>
        </form>
        <div id="storageMessage" class="message"></div>
      </section>

      <section>
        <h2>收益概览</h2>
        <div class="stats">
          <div class="stat">
            <span class="label">累计收益</span>
            <div id="totalEarnings" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">已提现</span>
            <div id="withdrawnAmount" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">审核中</span>
            <div id="pendingAmount" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">可提现</span>
            <div id="availableAmount" class="value">-</div>
          </div>
        </div>
        <div id="earningsMessage" class="message"></div>
      </section>

      <section>
        <h2>提交提现</h2>
        <form id="withdrawalForm">
          <input id="withdrawalAmount" name="amount" placeholder="提现金额" />
          <input id="walletAddress" name="wallet_address" placeholder="钱包地址" />
          <select id="withdrawalChannel" name="withdrawal_channel">
            <option value="wallet">wallet</option>
            <option value="bank">bank</option>
            <option value="alipay">alipay</option>
          </select>
          <input id="withdrawalAccount" name="withdrawal_account" placeholder="提现账号，默认等于钱包地址" />
          <button type="submit">提交提现</button>
        </form>
        <div id="withdrawalMessage" class="message"></div>
      </section>

      <section class="wide">
        <h2>提现记录</h2>
        <ul id="withdrawalList" class="list">
          <li><span class="muted">加载中...</span></li>
        </ul>
      </section>

      <section class="wide">
        <h2>控制操作</h2>
        <div class="toolbar">
          <button class="danger" id="stopButton" type="button">停止节点</button>
          <button class="secondary" id="restartButton" type="button">重启节点</button>
          <span id="controlState" class="status-pill">待加载</span>
        </div>
        <div id="controlMessage" class="message"></div>
      </section>
    </div>
  </main>
  <script>
    const CSRF_TOKEN = "__CSRF_TOKEN__";
    const formatAmount = (value) => {
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    };
    const setMessage = (id, text, isError = false) => {
      const node = document.getElementById(id);
      node.textContent = text || "";
      node.className = "message" + (isError ? " error" : "");
    };
    const api = async (path, options = {}) => {
      const opts = {...options};
      if (opts.method && opts.method.toUpperCase() !== "GET") {
        opts.headers = {...(opts.headers || {}), "Content-Type": "application/json", "X-CSRF-Token": CSRF_TOKEN};
        if (!opts.body) opts.body = "{}";
      }
      try {
        const res = await fetch(path, opts);
        const payload = await res.json().catch(() => ({ok:false, error:"响应解析失败"}));
        if (!res.ok && payload && payload.ok === undefined) payload.ok = false;
        return payload;
      } catch (error) {
        return {ok:false, error:error.message || "请求失败"};
      }
    };
    const applyStatus = (payload) => {
      if (!payload || !payload.ok) {
        setMessage("controlMessage", payload && payload.error ? payload.error : "状态加载失败", true);
        return;
      }
      const data = payload.data || {};
      const storage = data.storage || {};
      const isRunning = !!data.running;
      const heartbeatOk = !!data.heartbeat_ok;
      document.getElementById("runningState").textContent = isRunning ? "运行中" : "已停止";
      document.getElementById("serverUrl").textContent = data.server_configured ? (heartbeatOk ? "连接正常" : "等待心跳") : "-";
      document.getElementById("lastHeartbeat").textContent = data.last_heartbeat || "-";
      document.getElementById("lastMessage").textContent = data.last_notice || data.last_error || "-";
      document.getElementById("storageState").textContent = storage.storage_status || "-";
      document.getElementById("storageTotal").textContent = formatAmount(storage.storage_total_gb) + " GB";
      document.getElementById("storageUsed").textContent = formatAmount(storage.storage_used_gb) + " GB";
      document.getElementById("storageFree").textContent = formatAmount(storage.storage_free_gb) + " GB";
      document.getElementById("storagePath").textContent = storage.storage_path || data.storage_dir || "-";
      document.getElementById("storageDirInput").value = data.storage_dir || "";
      const pill = document.getElementById("controlState");
      pill.textContent = isRunning ? (heartbeatOk ? "运行中" : "重连中") : "已停止";
      pill.className = "status-pill" + (isRunning ? "" : " offline");
      document.getElementById("stopButton").disabled = !isRunning;
    };
    const applyEarnings = (payload) => {
      if (!payload || !payload.ok) {
        setMessage("earningsMessage", payload && payload.error ? payload.error : "收益加载失败", true);
        return;
      }
      const data = payload.data || {};
      document.getElementById("totalEarnings").textContent = formatAmount(data.total_amount || data.total_earnings || data.total_income || "0");
      document.getElementById("withdrawnAmount").textContent = formatAmount(data.withdrawn_amount || data.withdrawn_earnings || "0");
      document.getElementById("pendingAmount").textContent = formatAmount(data.pending_amount || data.pending_withdrawals || "0");
      document.getElementById("availableAmount").textContent = formatAmount(data.available_amount || data.available_earnings || "0");
      setMessage("earningsMessage", payload.message || "收益数据已更新");
    };
    const applyWithdrawals = (payload) => {
      const list = document.getElementById("withdrawalList");
      list.innerHTML = "";
      if (!payload || !payload.ok) {
        setMessage("withdrawalMessage", payload && payload.error ? payload.error : "提现记录加载失败", true);
        list.innerHTML = '<li><span class="muted">暂时无法读取提现记录</span></li>';
        return;
      }
      const rows = Array.isArray(payload.data) ? payload.data : (payload.data && payload.data.items) || [];
      if (!rows.length) {
        list.innerHTML = '<li><span class="muted">暂无提现记录</span></li>';
      } else {
        for (const item of rows) {
          const li = document.createElement("li");
          const left = document.createElement("div");
          const amount = document.createElement("strong");
          amount.textContent = formatAmount(item.amount);
          const wallet = document.createElement("div");
          wallet.className = "muted mono";
          wallet.textContent = item.wallet_address || item.withdrawal_account || "-";
          left.appendChild(amount);
          left.appendChild(wallet);
          const right = document.createElement("div");
          const status = document.createElement("div");
          status.textContent = item.status || "-";
          const created = document.createElement("div");
          created.className = "muted";
          created.textContent = item.created_at || item.created_time || "";
          right.appendChild(status);
          right.appendChild(created);
          li.appendChild(left);
          li.appendChild(right);
          list.appendChild(li);
        }
      }
      setMessage("withdrawalMessage", payload.message || "提现记录已更新");
    };
    async function refreshStatus() {
      applyStatus(await api("/api/status"));
    }
    async function refreshEarnings() {
      applyEarnings(await api("/api/earnings"));
    }
    async function refreshWithdrawals() {
      applyWithdrawals(await api("/api/withdrawals"));
    }
    async function refreshAll(){
      await Promise.all([refreshStatus(), refreshEarnings(), refreshWithdrawals()]);
    }
    async function updateStorage(event){
      event.preventDefault();
      const storageDir = document.getElementById("storageDirInput").value.trim();
      const payload = await api("/api/storage", {method:"POST", body: JSON.stringify({storage_dir: storageDir})});
      if (payload.ok) {
        applyStatus(payload);
        setMessage("storageMessage", "存储目录已更新并重新检测");
      } else {
        setMessage("storageMessage", payload.error || "存储目录更新失败", true);
      }
    }
    async function recheckStorage(){
      const payload = await api("/api/refresh", {method:"POST", body:"{}"});
      if (payload.ok) {
        applyStatus(payload);
        setMessage("storageMessage", "已重新检测本地目录");
      } else {
        setMessage("storageMessage", payload.error || "重新检测失败", true);
      }
    }
    async function submitWithdrawal(event){
      event.preventDefault();
      const walletAddress = document.getElementById("walletAddress").value.trim();
      const channel = document.getElementById("withdrawalChannel").value.trim() || "wallet";
      const accountInput = document.getElementById("withdrawalAccount").value.trim();
      const payload = await api("/api/withdrawals", {
        method:"POST",
        body: JSON.stringify({
          amount: document.getElementById("withdrawalAmount").value.trim(),
          wallet_address: walletAddress,
          withdrawal_channel: channel,
          withdrawal_account: accountInput || walletAddress
        })
      });
      if (payload.ok) {
        setMessage("withdrawalMessage", payload.message || "提现申请已提交");
        await Promise.all([refreshEarnings(), refreshWithdrawals()]);
      } else {
        setMessage("withdrawalMessage", payload.error || "提现申请失败", true);
      }
    }
    async function stopNode(){
      if (!confirm("确认停止节点？")) return;
      const payload = await api("/api/control/stop", {method:"POST", body:"{}"});
      if (payload.ok) {
        setMessage("controlMessage", payload.message || "节点停止请求已提交");
        applyStatus(payload);
      } else {
        setMessage("controlMessage", payload.error || "停止节点失败", true);
      }
    }
    async function restartNode(){
      if (!confirm("确认重启节点？")) return;
      const payload = await api("/api/control/restart", {method:"POST", body:"{}"});
      setMessage("controlMessage", payload.message || payload.error || "重启请求已处理", !payload.ok);
      if (payload.data) applyStatus(payload);
    }
    window.addEventListener("load", () => {
      document.getElementById("storageForm").addEventListener("submit", updateStorage);
      document.getElementById("refreshButton").addEventListener("click", recheckStorage);
      document.getElementById("withdrawalForm").addEventListener("submit", submitWithdrawal);
      document.getElementById("stopButton").addEventListener("click", stopNode);
      document.getElementById("restartButton").addEventListener("click", restartNode);
      refreshAll();
    });
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
        "heartbeat_ok": False,
        "shutdown_requested": False,
        "last_heartbeat": "",
        "last_error": "",
        "last_notice": "",
        "storage": inspect_storage_dir(storage_dir),
    }


def client_status_payload(state):
    return {
        "running": state["running"],
        "heartbeat_ok": state.get("heartbeat_ok", False),
        "server_configured": bool(state.get("server_url")),
        "shutdown_requested": state.get("shutdown_requested", False),
        "last_heartbeat": state["last_heartbeat"],
        "last_error": state["last_error"],
        "last_notice": state.get("last_notice", ""),
        "storage_dir": state["storage_dir"],
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


def build_node_identity_payload(state):
    return {
        "user_addr": state["user_addr"],
        "node_mac": state["node_mac"],
    }


def normalize_proxy_response(response):
    status_code = int(getattr(response, "status_code", 200) or 200)
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        result = dict(payload)
    elif payload is None:
        result = {"ok": status_code < 400, "data": None}
    else:
        result = {"ok": status_code < 400, "data": payload}
    if "ok" not in result and "code" in result:
        try:
            result["ok"] = int(result.get("code") or 0) == 200 and status_code < 400
        except (TypeError, ValueError):
            result["ok"] = status_code < 400
    if "error" not in result and result.get("msg") and not result.get("ok", status_code < 400):
        result["error"] = result.get("msg")
    if status_code >= 400 and "ok" not in result:
        result["ok"] = False
    return status_code, result


def proxy_node_get(state, endpoint, get_func=None):
    if get_func is None:
        get_func = requests.get
    try:
        response = get_func(
            f"{state['server_url']}{endpoint}",
            params=build_node_identity_payload(state),
            timeout=10,
        )
        return normalize_proxy_response(response)
    except Exception as exc:
        return 502, {"ok": False, "error": f"服务端不可达：{exc}"}


def build_withdrawal_request_payload(state, data):
    wallet_address = str(data.get("wallet_address") or "").strip()
    withdrawal_channel = str(data.get("withdrawal_channel") or "wallet").strip() or "wallet"
    withdrawal_account = str(data.get("withdrawal_account") or wallet_address).strip() or wallet_address
    payload = build_node_identity_payload(state)
    payload.update(
        {
            "amount": data.get("amount"),
            "wallet_address": wallet_address,
            "withdrawal_channel": withdrawal_channel,
            "withdrawal_account": withdrawal_account,
        }
    )
    return payload


def proxy_node_withdrawal_create(state, data, post_func=None):
    if post_func is None:
        post_func = requests.post
    try:
        response = post_func(
            f"{state['server_url']}/api/node/withdrawals",
            json=build_withdrawal_request_payload(state, data),
            timeout=10,
        )
        return normalize_proxy_response(response)
    except Exception as exc:
        return 502, {"ok": False, "error": f"服务端不可达：{exc}"}


def stop_client_from_console(state):
    state["running"] = False
    state["shutdown_requested"] = True
    state["last_notice"] = "已从本地控制台请求停止节点"
    return {
        "ok": True,
        "message": "已停止节点心跳循环；开发模式不会直接退出当前进程",
        "data": client_status_payload(state),
    }


def restart_client_from_console(state):
    state["last_notice"] = "开发模式暂不支持自动重启，请手动重新运行 client.py"
    return {
        "ok": True,
        "message": "开发模式暂不支持自动重启，请手动重新运行 client.py",
        "data": client_status_payload(state),
    }


def report_heartbeat(state, upload_bw, post_func=requests.post):
    payload = build_heartbeat_payload(state, upload_bw)
    try:
        response = post_func(f"{state['server_url']}/heartbeat", json=payload, timeout=10)
        ensure_success_response(response)
        state["heartbeat_ok"] = True
        state["last_notice"] = ""
        state["last_heartbeat"] = time.strftime("%Y-%m-%d %H:%M:%S")
        state["last_error"] = ""
        return True, payload
    except Exception as exc:
        state["heartbeat_ok"] = False
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
            if host == "[::1]" or host.startswith("[::1]:"):
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
            try:
                parsed = urlparse(value)
            except ValueError:
                return False
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
                status_code, payload = proxy_node_get(state, "/api/node/earnings")
                self._send_json(payload, status=status_code)
            elif path == "/api/withdrawals":
                status_code, payload = proxy_node_get(state, "/api/node/withdrawals")
                self._send_json(payload, status=status_code)
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
                self._send_json(stop_client_from_console(state))
            elif path == "/api/control/restart":
                self._send_json(restart_client_from_console(state))
            elif path == "/api/withdrawals":
                status_code, payload = proxy_node_withdrawal_create(state, data)
                self._send_json(payload, status=status_code)
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
    state=None,
):
    attempts = 0
    while True:
        if state is not None and state.get("shutdown_requested"):
            safe_print("ℹ️ 节点停止请求已收到，取消注册重试")
            return False
        attempts += 1
        try:
            register_node(server_url, user_addr, device_mac, parent_invite, post_func=post_func)
            safe_print(f"✅ 节点注册成功，设备指纹：{device_mac}")
            return True
        except Exception:
            safe_print(f"❌ 服务端连接失败，{reconnect_interval}秒后自动重连...")
            if max_attempts is not None and attempts >= max_attempts:
                return False
            if state is not None and state.get("shutdown_requested"):
                safe_print("ℹ️ 节点停止请求已收到，取消注册重试")
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
            state=state,
        )

        # 2. 循环心跳上报（60秒一次）
        safe_print("🔄 节点持续运行中，实时上报存储数据...")
        while not state.get("shutdown_requested"):
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
