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
import base64
import webbrowser
from pathlib import Path
import os
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
try:
    import webview
except Exception:
    webview = None
from client.config import (
    get_invite_arg,
    get_manage_port_arg,
    get_storage_dir_arg,
    get_storage_quota_arg,
    load_client_config,
)
from client.console import CLIENT_MANAGE_HTML, render_client_console_html

# 服务端地址（和后端统一）
SERVER_URL = "http://127.0.0.1:8000"
# 上级推广码（分享链接自动填充，用户无需手动改）
PARENT_INVITE = ""
HEARTBEAT_INTERVAL = 60
RECONNECT_INTERVAL = 10
NODE_STORAGE_DIR = ""
MANAGE_PORT = 8787
STORAGE_STORE_NAME = ".web3_nodes_store"
STORAGE_LOCK_NAME = ".web3_nodes.lock"


def safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("gbk", errors="ignore").decode("gbk"))


def ensure_storage_dir(storage_dir):
    if not storage_dir:
        return None
    path = Path(storage_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def storage_store_dir(storage_dir):
    path = Path(storage_dir).expanduser()
    return path / STORAGE_STORE_NAME


def storage_lock_path(storage_dir):
    path = Path(storage_dir).expanduser()
    return path / STORAGE_LOCK_NAME


def hide_storage_store_dir(store_dir):
    if os.name != "nt":
        return ""
    try:
        subprocess.run(
            ["attrib", "+h", "+s", str(store_dir)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return ""
    except Exception as exc:
        return str(exc)


def prepare_storage_root(storage_dir, user_addr, node_mac):
    path = ensure_storage_dir(storage_dir)
    if path is None:
        raise RuntimeError("storage directory required")
    lock_path = storage_lock_path(path)
    store_dir = storage_store_dir(path)
    if lock_path.exists():
        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"storage locked by unreadable lock: {exc}") from exc
        if (
            str(lock_data.get("user_addr") or "") != str(user_addr or "")
            or str(lock_data.get("node_mac") or "") != str(node_mac or "")
        ):
            raise RuntimeError("storage locked by another node")
    store_dir.mkdir(parents=True, exist_ok=True)
    lock_data = {
        "user_addr": user_addr,
        "node_mac": node_mac,
        "storage_dir": str(path),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "schema_version": 1,
    }
    lock_path.write_text(json.dumps(lock_data, ensure_ascii=False, indent=2), encoding="utf-8")
    hide_warning = hide_storage_store_dir(store_dir)
    return {
        "storage_dir": str(path),
        "store_dir": str(store_dir),
        "lock_path": str(lock_path),
        "hide_warning": hide_warning,
    }


def validate_file_hash_value(file_hash):
    value = str(file_hash or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("invalid file_hash")
    return value


def validate_chunk_index(chunk_index):
    try:
        value = int(chunk_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid chunk_index") from exc
    if value < 0:
        raise ValueError("invalid chunk_index")
    return value


def shard_file_path(storage_dir, file_hash, chunk_index):
    safe_hash = validate_file_hash_value(file_hash)
    safe_index = validate_chunk_index(chunk_index)
    store_dir = storage_store_dir(storage_dir)
    file_dir = (store_dir / "files" / safe_hash).resolve()
    base_dir = (store_dir / "files").resolve()
    if base_dir != file_dir and base_dir not in file_dir.parents:
        raise ValueError("invalid shard path")
    return file_dir / f"{safe_index}.part"


def manifest_file_path(storage_dir, file_hash):
    safe_hash = validate_file_hash_value(file_hash)
    manifest_dir = (storage_store_dir(storage_dir) / "manifest").resolve()
    manifest_path = (manifest_dir / f"{safe_hash}.json").resolve()
    if manifest_dir != manifest_path.parent:
        raise ValueError("invalid manifest path")
    return manifest_path


def read_local_manifest(storage_dir, file_hash):
    manifest_path = manifest_file_path(storage_dir, file_hash)
    if not manifest_path.exists():
        return {
            "file_hash": validate_file_hash_value(file_hash),
            "chunks": {},
        }
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"file_hash": validate_file_hash_value(file_hash), "chunks": {}}
    except Exception:
        return {
            "file_hash": validate_file_hash_value(file_hash),
            "chunks": {},
        }


def write_local_shard(storage_dir, user_addr, node_mac, file_hash, chunk_index, chunk_total, chunk_bytes, chunk_hash=""):
    safe_hash = validate_file_hash_value(file_hash)
    safe_index = validate_chunk_index(chunk_index)
    safe_total = int(chunk_total)
    if safe_total <= 0 or safe_index >= safe_total:
        raise ValueError("invalid chunk_total")
    if not isinstance(chunk_bytes, (bytes, bytearray)):
        raise ValueError("chunk bytes required")
    computed_hash = hashlib.sha256(bytes(chunk_bytes)).hexdigest()
    if chunk_hash and computed_hash != str(chunk_hash).lower():
        raise ValueError("chunk hash mismatch")
    prepare_storage_root(storage_dir, user_addr, node_mac)
    shard_path = shard_file_path(storage_dir, safe_hash, safe_index)
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_bytes(bytes(chunk_bytes))
    manifest = read_local_manifest(storage_dir, safe_hash)
    manifest["file_hash"] = safe_hash
    manifest["chunk_total"] = safe_total
    manifest.setdefault("chunks", {})
    manifest["chunks"][str(safe_index)] = {
        "chunk_index": safe_index,
        "chunk_total": safe_total,
        "chunk_hash": computed_hash,
        "chunk_size": len(chunk_bytes),
        "stored_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    manifest_path = manifest_file_path(storage_dir, safe_hash)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(manifest["chunks"][str(safe_index)], file_hash=safe_hash)


def read_local_shard(storage_dir, file_hash, chunk_index):
    shard_path = shard_file_path(storage_dir, file_hash, chunk_index)
    if not shard_path.exists():
        raise FileNotFoundError("shard not found")
    return shard_path.read_bytes()


def list_local_stored_files(state, max_items=50):
    entries = normalize_storage_dirs(
        state.get("storage_dir", ""),
        state.get("storage_quota_gb", 0),
        state.get("storage_dirs"),
    )
    rows = []
    for entry in entries:
        storage_dir = entry["storage_dir"]
        manifest_dir = storage_store_dir(storage_dir) / "manifest"
        if not manifest_dir.exists():
            continue
        for manifest_path in sorted(manifest_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                file_hash = validate_file_hash_value(manifest.get("file_hash") or manifest_path.stem)
                chunks = manifest.get("chunks") if isinstance(manifest.get("chunks"), dict) else {}
                storage_used_bytes = 0
                for chunk_index, chunk_meta in chunks.items():
                    if isinstance(chunk_meta, dict) and chunk_meta.get("chunk_size") is not None:
                        try:
                            storage_used_bytes += int(chunk_meta.get("chunk_size") or 0)
                            continue
                        except (TypeError, ValueError):
                            pass
                    try:
                        storage_used_bytes += shard_file_path(storage_dir, file_hash, chunk_index).stat().st_size
                    except Exception:
                        continue
                rows.append({
                    "file_hash": file_hash,
                    "chunk_count": len(chunks),
                    "chunk_total": int(manifest.get("chunk_total") or 0),
                    "storage_dir": storage_dir,
                    "storage_used_bytes": storage_used_bytes,
                    "storage_used_display": format_storage_bytes(storage_used_bytes),
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(manifest_path.stat().st_mtime)),
                })
            except Exception:
                continue
            if len(rows) >= max_items:
                return rows
    return rows


def get_directory_size_bytes(path):
    total = 0
    for file_path in path.rglob("*"):
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
        except OSError:
            continue
    return total


def format_storage_bytes(num_bytes):
    value = int(num_bytes or 0)
    if value >= 1024 ** 3:
        return f"{value / (1024 ** 3):.2f} GB"
    if value >= 1024 ** 2:
        return f"{value / (1024 ** 2):.2f} MB"
    if value >= 1024:
        return f"{value / 1024:.2f} KB"
    return f"{value} B"


def storage_bytes_from_gb(value):
    try:
        return int(float(value or 0) * (1024 ** 3))
    except (TypeError, ValueError):
        return 0


def inspect_storage_dir(storage_dir, user_addr="", node_mac="", storage_quota_gb=0):
    if not storage_dir:
        storage_used_gb = get_local_disk_use("")
        storage_used_bytes = storage_bytes_from_gb(storage_used_gb)
        return {
            "storage_path": "",
            "storage_status": "required",
            "storage_error": "未指定存储目录",
            "storage_total_gb": 0,
            "storage_used_gb": storage_used_gb,
            "storage_used_bytes": storage_used_bytes,
            "storage_used_display": format_storage_bytes(storage_used_bytes),
            "storage_free_gb": 0,
            "storage_quota_gb": 0,
            "storage_available_gb": 0,
        }
    try:
        prepared = prepare_storage_root(storage_dir, user_addr, node_mac) if user_addr or node_mac else None
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
        store_path = Path(prepared["store_dir"]) if prepared else path
        dir_used = get_directory_size_bytes(store_path)
        quota = float(storage_quota_gb or 0)
        physical_free = round(usage.free / (1024 ** 3), 2)
        used_gb = round(dir_used / (1024 ** 3), 8)
        available_gb = max(0, min(quota - used_gb, physical_free)) if quota > 0 else 0
        hide_warning = prepared.get("hide_warning", "") if prepared else ""
        return {
            "storage_path": str(path),
            "storage_status": "ok" if quota > 0 else "quota_required",
            "storage_error": hide_warning,
            "storage_total_gb": round(quota, 2) if quota > 0 else 0,
            "storage_used_gb": used_gb,
            "storage_used_bytes": dir_used,
            "storage_used_display": format_storage_bytes(dir_used),
            "storage_free_gb": round(available_gb, 2),
            "storage_quota_gb": quota,
            "storage_available_gb": round(available_gb, 2),
        }
    except Exception as exc:
        return {
            "storage_path": str(storage_dir),
            "storage_status": "locked" if "locked" in str(exc).lower() else "unavailable",
            "storage_error": str(exc),
            "storage_total_gb": 0,
            "storage_used_gb": 0,
            "storage_used_bytes": 0,
            "storage_used_display": "0 B",
            "storage_free_gb": 0,
            "storage_quota_gb": float(storage_quota_gb or 0),
            "storage_available_gb": 0,
        }


def normalize_storage_dirs(storage_dir="", storage_quota_gb=0, storage_dirs=None):
    entries = []

    def add_entry(path_value, quota_value):
        path_text = str(path_value or "").strip()
        if not path_text:
            return
        try:
            quota = float(quota_value or 0)
        except (TypeError, ValueError):
            quota = 0.0
        for entry in entries:
            if entry["storage_dir"] == path_text:
                entry["storage_quota_gb"] = quota
                return
        entries.append({"storage_dir": path_text, "storage_quota_gb": quota})

    if isinstance(storage_dirs, (list, tuple)):
        for item in storage_dirs:
            if isinstance(item, dict):
                add_entry(item.get("storage_dir") or item.get("path"), item.get("storage_quota_gb") or item.get("quota_gb"))
            else:
                add_entry(item, 0)
    add_entry(storage_dir, storage_quota_gb)
    return entries


def inspect_one_storage_dir(storage_dir, user_addr="", node_mac="", storage_quota_gb=0):
    try:
        return inspect_storage_dir(storage_dir, user_addr, node_mac, storage_quota_gb)
    except TypeError:
        return inspect_storage_dir(storage_dir)


def inspect_storage_dirs(storage_dirs, user_addr="", node_mac=""):
    entries = normalize_storage_dirs(storage_dirs=storage_dirs)
    if not entries:
        return inspect_one_storage_dir("", user_addr, node_mac, 0)
    directory_details = []
    for entry in entries:
        detail = inspect_one_storage_dir(
            entry["storage_dir"],
            user_addr,
            node_mac,
            entry.get("storage_quota_gb", 0),
        )
        detail = dict(detail)
        detail["storage_dir"] = entry["storage_dir"]
        detail["storage_quota_gb"] = float(entry.get("storage_quota_gb") or detail.get("storage_quota_gb") or 0)
        if "storage_available_gb" not in detail:
            detail["storage_available_gb"] = max(
                0,
                float(detail.get("storage_quota_gb") or 0) - float(detail.get("storage_used_gb") or 0),
            )
        if "storage_used_bytes" not in detail:
            detail["storage_used_bytes"] = storage_bytes_from_gb(detail.get("storage_used_gb"))
        if "storage_used_display" not in detail:
            detail["storage_used_display"] = format_storage_bytes(detail.get("storage_used_bytes"))
        directory_details.append(detail)
    total_quota = round(sum(float(item.get("storage_quota_gb") or 0) for item in directory_details), 2)
    total_used_bytes = sum(int(item.get("storage_used_bytes") or 0) for item in directory_details)
    total_used = round(total_used_bytes / (1024 ** 3), 8)
    total_available = round(sum(float(item.get("storage_available_gb") or item.get("storage_free_gb") or 0) for item in directory_details), 2)
    ok_count = sum(1 for item in directory_details if item.get("storage_status") == "ok")
    status = "ok" if ok_count and total_available > 0 else directory_details[0].get("storage_status", "unavailable")
    errors = [str(item.get("storage_error") or "") for item in directory_details if item.get("storage_error")]
    return {
        "storage_path": "; ".join(item["storage_dir"] for item in directory_details),
        "storage_status": status,
        "storage_error": "; ".join(errors),
        "storage_total_gb": total_quota,
        "storage_used_gb": total_used,
        "storage_used_bytes": total_used_bytes,
        "storage_used_display": format_storage_bytes(total_used_bytes),
        "storage_free_gb": total_available,
        "storage_quota_gb": total_quota,
        "storage_available_gb": total_available,
        "storage_directories": directory_details,
    }


def inspect_storage_state(storage_dir, user_addr="", node_mac="", storage_quota_gb=0, storage_dirs=None):
    if storage_dirs is not None or isinstance(storage_dir, (list, tuple)):
        return inspect_storage_dirs(storage_dirs if storage_dirs is not None else storage_dir, user_addr, node_mac)
    return inspect_one_storage_dir(storage_dir, user_addr, node_mac, storage_quota_gb)


def select_storage_dir_for_shard(state, file_hash="", chunk_index=0):
    entries = normalize_storage_dirs(
        state.get("storage_dir", ""),
        state.get("storage_quota_gb", 0),
        state.get("storage_dirs"),
    )
    if not entries:
        return state.get("storage_dir", "")
    return entries[validate_chunk_index(chunk_index) % len(entries)]["storage_dir"]


def create_client_state(server_url, user_addr, node_mac, storage_dir, manage_port, storage_quota_gb=0, storage_explicit=True, storage_dirs=None):
    normalized_dirs = normalize_storage_dirs(storage_dir, storage_quota_gb, storage_dirs)
    primary_dir = normalized_dirs[0]["storage_dir"] if normalized_dirs else storage_dir
    total_quota = round(sum(float(item.get("storage_quota_gb") or 0) for item in normalized_dirs), 2)
    return {
        "server_url": server_url,
        "user_addr": user_addr,
        "node_mac": node_mac,
        "storage_dir": primary_dir,
        "storage_dirs": normalized_dirs,
        "storage_explicit": storage_explicit,
        "storage_quota_gb": total_quota,
        "manage_port": manage_port,
        "csrf_token": secrets.token_urlsafe(24),
        "running": True,
        "heartbeat_ok": False,
        "shutdown_requested": False,
        "last_heartbeat": "",
        "last_error": "",
        "last_notice": "",
        "storage": inspect_storage_state(primary_dir, user_addr, node_mac, total_quota, normalized_dirs),
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
        "storage_dirs": state.get("storage_dirs", []),
        "storage_explicit": state.get("storage_explicit", True),
        "storage_quota_gb": state.get("storage_quota_gb", 0),
        "storage": state["storage"],
        "stored_files": list_local_stored_files(state),
    }


def build_heartbeat_payload(state, upload_bw):
    storage_info = inspect_storage_state(
        state["storage_dir"],
        state.get("user_addr", ""),
        state.get("node_mac", ""),
        state.get("storage_quota_gb", 0),
        state.get("storage_dirs"),
    )
    state["storage"] = storage_info
    return {
        "user_addr": state["user_addr"],
        "node_mac": state["node_mac"],
        "disk_used": storage_info["storage_used_gb"],
        "upload_bw": upload_bw,
        "storage_api_url": f"http://127.0.0.1:{int(state.get('manage_port') or MANAGE_PORT)}",
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


def build_node_identity_export(state):
    storage_entries = normalize_storage_dirs(
        state.get("storage_dir", ""),
        state.get("storage_quota_gb", 0),
        state.get("storage_dirs"),
    )
    program_path = str(Path(sys.executable).resolve())
    return {
        "schema": "web3-node-identity",
        "schema_version": 1,
        "user_addr": state.get("user_addr", ""),
        "node_mac": state.get("node_mac", ""),
        "server_url": state.get("server_url", ""),
        "storage_dir": state.get("storage_dir", ""),
        "storage_dirs": storage_entries,
        "storage_quota_gb": state.get("storage_quota_gb", 0),
        "manage_port": int(state.get("manage_port") or MANAGE_PORT),
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "program": {
            "path": program_path,
            "dir": str(Path(program_path).parent),
            "packaged": bool(getattr(sys, "frozen", False)),
            "platform": os.name,
        },
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
    state["last_notice"] = "开发模式暂不支持自动重启，请手动重新运行 python -m client.main"
    return {
        "ok": True,
        "message": "开发模式暂不支持自动重启，请手动重新运行 python -m client.main",
        "data": client_status_payload(state),
    }


def numeric_value(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def node_earnings_are_unprocessed(summary):
    return (
        numeric_value(summary.get("available_earnings") or summary.get("available_amount")) > 0
        or numeric_value(summary.get("pending_withdrawals") or summary.get("pending_amount")) > 0
        or numeric_value(summary.get("locked_withdrawals") or summary.get("locked_amount")) > 0
    )


def remove_node_storage_data(state):
    removed = []
    skipped = []
    entries = normalize_storage_dirs(
        state.get("storage_dir", ""),
        state.get("storage_quota_gb", 0),
        state.get("storage_dirs"),
    )
    seen_roots = set()
    for entry in entries:
        root = Path(entry["storage_dir"]).expanduser().resolve()
        if str(root) in seen_roots:
            continue
        seen_roots.add(str(root))
        store_dir = storage_store_dir(root).resolve()
        lock_path = storage_lock_path(root).resolve()
        try:
            if store_dir.exists():
                if root != store_dir and root in store_dir.parents:
                    shutil.rmtree(store_dir)
                    removed.append(str(store_dir))
                else:
                    skipped.append(str(store_dir))
            if lock_path.exists():
                if root == lock_path.parent:
                    lock_path.unlink()
                    removed.append(str(lock_path))
                else:
                    skipped.append(str(lock_path))
            if root.exists() and root.is_dir():
                try:
                    next(root.iterdir())
                    skipped.append(str(root))
                except StopIteration:
                    root.rmdir()
                    removed.append(str(root))
        except Exception as exc:
            raise RuntimeError(f"删除节点存储数据失败：{exc}") from exc
    return {"removed_paths": removed, "skipped_paths": skipped}


def build_self_uninstall_script(program_path=None, pid=None, temp_dir=None, platform_name=None):
    platform_name = platform_name or os.name
    target_exe = Path(program_path or sys.executable).expanduser().resolve()
    target_dir = target_exe.parent
    process_id = int(pid or os.getpid())
    temp_root = Path(temp_dir or tempfile.gettempdir()).expanduser().resolve()
    suffix = "cmd" if platform_name == "nt" else "sh"
    script_path = temp_root / f"web3-node-uninstall-{process_id}.{suffix}"
    if platform_name == "nt":
        content = "\n".join([
            "@echo off",
            "setlocal",
            f"set \"PID={process_id}\"",
            f"set \"TARGET_EXE={target_exe}\"",
            f"set \"TARGET_DIR={target_dir}\"",
            ":wait_for_exit",
            f"tasklist /FI \"PID eq {process_id}\" | find \"{process_id}\" >nul",
            "if not errorlevel 1 (",
            "  timeout /t 1 /nobreak >nul",
            "  goto wait_for_exit",
            ")",
            "if exist \"%TARGET_EXE%\" del /f /q \"%TARGET_EXE%\"",
            "if exist \"%TARGET_DIR%\" rmdir /s /q \"%TARGET_DIR%\"",
            "del /f /q \"%~f0\"",
            "",
        ])
    else:
        content = "\n".join([
            "#!/bin/sh",
            f"PID={process_id}",
            f"TARGET_DIR='{target_dir}'",
            "while kill -0 \"$PID\" 2>/dev/null; do sleep 1; done",
            "rm -rf \"$TARGET_DIR\"",
            "rm -f \"$0\"",
            "",
        ])
    return {
        "script_path": str(script_path),
        "target_exe": str(target_exe),
        "target_dir": str(target_dir),
        "content": content,
    }


def packaged_self_uninstall_is_allowed(program_path=None):
    if not getattr(sys, "frozen", False):
        return False, "开发模式不会删除源码目录；打包后的客户端会在退出后删除程序目录"
    target_exe = Path(program_path or sys.executable).expanduser().resolve()
    target_dir = target_exe.parent
    project_root = Path(__file__).resolve().parents[1]
    if target_dir == project_root or target_dir in project_root.parents or project_root in target_dir.parents:
        return False, "检测到程序位于源码目录内，已阻止删除源码"
    return True, ""


def schedule_self_uninstall(popen_func=None, timer_factory=None):
    allowed, reason = packaged_self_uninstall_is_allowed()
    if not allowed:
        return {"scheduled": False, "reason": reason}
    script = build_self_uninstall_script()
    script_path = Path(script["script_path"])
    script_path.write_text(script["content"], encoding="utf-8")
    popen_func = popen_func or subprocess.Popen
    if os.name == "nt":
        popen_func(["cmd", "/c", str(script_path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        script_path.chmod(0o700)
        popen_func(["/bin/sh", str(script_path)])
    if os.getenv("WEB3_NODES_DISABLE_SELF_EXIT", "").strip().lower() not in ("1", "true", "yes", "on"):
        timer_factory = timer_factory or threading.Timer
        timer = timer_factory(1.5, lambda: os._exit(0))
        timer.daemon = True
        timer.start()
    return {
        "scheduled": True,
        "script_path": str(script_path),
        "target_dir": script["target_dir"],
    }


def uninstall_client_from_console(state, earnings_get_func=None, self_uninstall_func=None):
    status_code, earnings_payload = proxy_node_get(state, "/api/node/earnings", get_func=earnings_get_func)
    if status_code >= 400 or not earnings_payload.get("ok", False):
        return {
            "ok": False,
            "code": "earnings_check_failed",
            "error": earnings_payload.get("error") or earnings_payload.get("msg") or "无法确认节点收益状态，请稍后重试",
            "data": {"earnings": earnings_payload.get("data")},
        }
    earnings = earnings_payload.get("data") or {}
    if node_earnings_are_unprocessed(earnings):
        return {
            "ok": False,
            "code": "earnings_unprocessed",
            "error": "当前节点仍有未处理收益或处理中提现，请先提现并等待处理完成后再卸载节点服务",
            "data": {"earnings": earnings},
        }
    identity_export = build_node_identity_export(state)
    removal = remove_node_storage_data(state)
    self_uninstall = (self_uninstall_func or schedule_self_uninstall)()
    state["running"] = False
    state["shutdown_requested"] = True
    state["heartbeat_ok"] = False
    state["storage_dir"] = ""
    state["storage_dirs"] = []
    state["storage_explicit"] = False
    state["storage_quota_gb"] = 0
    state["storage"] = inspect_storage_state("", state.get("user_addr", ""), state.get("node_mac", ""), 0, [])
    state["last_notice"] = "节点服务已卸载，本地加密分片、manifest 和目录锁已删除"
    self_delete_note = "；客户端程序将在当前进程退出后自动删除" if self_uninstall.get("scheduled") else f"；{self_uninstall.get('reason', '当前环境未安排删除客户端程序')}"
    return {
        "ok": True,
        "message": "节点服务已卸载，本地加密分片、manifest 和目录锁已删除" + self_delete_note,
        "data": {
            **client_status_payload(state),
            **removal,
            "identity_export": identity_export,
            "self_uninstall": self_uninstall,
        },
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
            self._discard_request_body()
            self._send_json({"ok": False, "error": "invalid host"}, status=403)
            return False

        def _validate_mutation_source(self):
            for header_name in ("Origin", "Referer"):
                if not self._is_allowed_url_header(self.headers.get(header_name, "")):
                    self._discard_request_body()
                    self._send_json({"ok": False, "error": "invalid request origin"}, status=403)
                    return False
            return True

        def _discard_request_body(self):
            try:
                remaining = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                return
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)

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

        def _read_mutation_json(self, require_csrf=True):
            if not self._validate_mutation_source():
                return None
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._discard_request_body()
                self._send_json({"ok": False, "error": "content type must be application/json"}, status=400)
                return None
            data = self._read_json()
            if data is None:
                return None
            if require_csrf:
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
                self._send_html(render_client_console_html(state["csrf_token"]))
            elif path == "/api/status":
                self._send_json({"ok": True, "data": client_status_payload(state)})
            elif path == "/api/node/identity":
                self._send_json({"ok": True, "data": build_node_identity_export(state)})
            elif path.startswith("/api/node/storage/shards/"):
                parts = path.strip("/").split("/")
                if len(parts) != 6:
                    self._send_json({"ok": False, "error": "invalid shard path"}, status=400)
                    return
                try:
                    file_hash = parts[4]
                    chunk_index = parts[5]
                    chunk = None
                    for entry in normalize_storage_dirs(
                        state.get("storage_dir", ""),
                        state.get("storage_quota_gb", 0),
                        state.get("storage_dirs"),
                    ):
                        try:
                            chunk = read_local_shard(entry["storage_dir"], file_hash, chunk_index)
                            break
                        except FileNotFoundError:
                            continue
                    if chunk is None:
                        raise FileNotFoundError("shard not found")
                    chunk_hash = hashlib.sha256(chunk).hexdigest()
                    self._send_json({
                        "ok": True,
                        "data": {
                            "file_hash": validate_file_hash_value(file_hash),
                            "chunk_index": validate_chunk_index(chunk_index),
                            "chunk_hash": chunk_hash,
                            "chunk_b64": base64.b64encode(chunk).decode("ascii"),
                        },
                    })
                except FileNotFoundError:
                    self._send_json({"ok": False, "error": "shard not found"}, status=404)
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
            elif path.startswith("/api/node/storage/files/") and path.endswith("/manifest"):
                parts = path.strip("/").split("/")
                if len(parts) != 6:
                    self._send_json({"ok": False, "error": "invalid manifest path"}, status=400)
                    return
                try:
                    merged = {"file_hash": validate_file_hash_value(parts[4]), "chunks": {}}
                    for entry in normalize_storage_dirs(
                        state.get("storage_dir", ""),
                        state.get("storage_quota_gb", 0),
                        state.get("storage_dirs"),
                    ):
                        manifest = read_local_manifest(entry["storage_dir"], parts[4])
                        merged["chunk_total"] = manifest.get("chunk_total", merged.get("chunk_total", 0))
                        merged.setdefault("chunks", {}).update(manifest.get("chunks") or {})
                    self._send_json({"ok": True, "data": merged})
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
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
            data = self._read_mutation_json(require_csrf=path != "/api/node/storage/shards")
            if data is None:
                return
            if path == "/api/node/storage/shards":
                try:
                    chunk_bytes = base64.b64decode(str(data.get("chunk_b64") or ""), validate=True)
                    target_storage_dir = select_storage_dir_for_shard(state, data.get("file_hash"), data.get("chunk_index"))
                    metadata = write_local_shard(
                        target_storage_dir,
                        state["user_addr"],
                        state["node_mac"],
                        data.get("file_hash"),
                        data.get("chunk_index"),
                        data.get("chunk_total"),
                        chunk_bytes,
                        data.get("chunk_hash") or "",
                    )
                    state["storage"] = inspect_storage_state(
                        state["storage_dir"],
                        state.get("user_addr", ""),
                        state.get("node_mac", ""),
                        state.get("storage_quota_gb", 0),
                        state.get("storage_dirs"),
                    )
                    self._send_json({"ok": True, "data": metadata})
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
            elif path == "/api/storage":
                storage_dir = str(data.get("storage_dir") or data.get("path") or "").strip()
                try:
                    storage_quota_gb = float(data.get("storage_quota_gb") or data.get("quota_gb") or 0)
                except (TypeError, ValueError):
                    storage_quota_gb = 0
                if not storage_dir:
                    self._send_json({"ok": False, "error": "请指定存储目录"}, status=400)
                    return
                if storage_quota_gb <= 0:
                    self._send_json({"ok": False, "error": "请设置目录可用容量"}, status=400)
                    return
                existing_dirs = [
                    item for item in state.get("storage_dirs", [])
                    if float(item.get("storage_quota_gb") or 0) > 0
                ]
                state["storage_dirs"] = normalize_storage_dirs(
                    storage_dir,
                    storage_quota_gb,
                    existing_dirs,
                )
                state["storage_dir"] = state["storage_dirs"][0]["storage_dir"] if state["storage_dirs"] else storage_dir
                state["storage_quota_gb"] = round(sum(item["storage_quota_gb"] for item in state["storage_dirs"]), 2)
                state["storage_explicit"] = True
                state["storage"] = inspect_storage_state(
                    state["storage_dir"],
                    state.get("user_addr", ""),
                    state.get("node_mac", ""),
                    state.get("storage_quota_gb", 0),
                    state.get("storage_dirs"),
                )
                self._send_json({"ok": True, "data": client_status_payload(state)})
            elif path == "/api/refresh":
                state["storage"] = inspect_storage_state(
                    state["storage_dir"],
                    state.get("user_addr", ""),
                    state.get("node_mac", ""),
                    state.get("storage_quota_gb", 0),
                    state.get("storage_dirs"),
                )
                self._send_json({"ok": True, "data": client_status_payload(state)})
            elif path == "/api/control/stop":
                self._send_json(stop_client_from_console(state))
            elif path == "/api/control/restart":
                self._send_json(restart_client_from_console(state))
            elif path == "/api/control/uninstall":
                payload = uninstall_client_from_console(state)
                self._send_json(payload, status=200 if payload.get("ok") else 409)
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


def should_open_client_console():
    return os.getenv("NODE_OPEN_CLIENT_CONSOLE", "1").strip().lower() not in ("0", "false", "no", "off")


def open_client_console(manage_port, open_func=None):
    url = f"http://127.0.0.1:{int(manage_port)}/"
    opener = open_func or webbrowser.open_new_tab
    try:
        opener(url)
        safe_print(f"🌐 已自动打开节点管理页：{url}")
        return True
    except Exception as exc:
        safe_print(f"⚠️ 自动打开节点管理页失败：{exc}｜请手动访问 {url}")
        return False

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
    storage_dir_arg = get_storage_dir_arg()
    NODE_STORAGE_DIR = storage_dir_arg or config["storage_dir"]
    storage_explicit = bool(storage_dir_arg or config.get("storage_explicit"))
    storage_quota_gb = get_storage_quota_arg() or float(config.get("storage_quota_gb") or 0)
    MANAGE_PORT = get_manage_port_arg() or int(config["manage_port"])
    if NODE_STORAGE_DIR:
        safe_print(f"📁 节点存储目录：{Path(NODE_STORAGE_DIR).expanduser()}")
    if storage_quota_gb:
        safe_print(f"📦 节点可用存储额度：{storage_quota_gb} GB")
    device_mac = get_device_mac()
    # 根据设备MAC生成唯一用户标识
    user_addr = "NODE_" + hashlib.md5(device_mac.encode()).hexdigest()[:12]
    state = create_client_state(
        SERVER_URL,
        user_addr,
        device_mac,
        NODE_STORAGE_DIR,
        MANAGE_PORT,
        storage_quota_gb,
        storage_explicit,
    )
    manage_server = None
    try:
        manage_server = start_manage_server(state)
        safe_print(f"🌐 节点管理页：http://127.0.0.1:{MANAGE_PORT}")
        if should_open_client_console():
            open_client_console(MANAGE_PORT)
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
    amap_web_key = os.getenv("AMAP_WEB_KEY", "").strip()
    amap_security_jscode = os.getenv("AMAP_SECURITY_JSCODE", "").strip()
    if not amap_web_key or not amap_security_jscode:
        html = '''
    <html style="margin:0;padding:0">
    <body style="margin:0;padding:24px;font-family:Arial,'Microsoft YaHei',sans-serif;background:#f8fafc;color:#155e63">
    <h2>地图未启用</h2>
    <p>未完整配置 AMAP_WEB_KEY / AMAP_SECURITY_JSCODE，客户端已跳过高德地图 SDK 加载。</p>
    <p>节点仍会继续运行，后台可使用节点分布看板查看数据。</p>
    </body>
    </html>
    '''
    else:
        html = '''
    <html style="margin:0;padding:0">
    <body style="margin:0;padding:0">
    <script>window._AMapSecurityConfig = { securityJsCode: __AMAP_SECURITY_JSCODE__ };</script>
    <script src="https://webapi.amap.com/maps?v=2.0&key=__AMAP_WEB_KEY__"></script>
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
        html = html.replace("__AMAP_SECURITY_JSCODE__", json.dumps(amap_security_jscode))
        html = html.replace("__AMAP_WEB_KEY__", amap_web_key)
    webview.create_window("节点全球地图", html=html, width=800, height=600)
    webview.start(gui=True, debug=False)

def should_open_map_window():
    return webview is not None and os.getenv("NODE_OPEN_MAP_WINDOW", "").strip().lower() in ("1", "true", "yes", "on")


def main():
    import threading

    safe_print("🚀 Web3分布式存储激励节点启动成功")
    if should_open_map_window():
        threading.Thread(target=client_run, daemon=True).start()
        open_map_window()
    else:
        if webview is not None:
            safe_print("ℹ️ 默认不自动打开 pywebview 地图窗口；如需地图请设置 NODE_OPEN_MAP_WINDOW=1")
        client_run()


if __name__ == "__main__":
    main()
