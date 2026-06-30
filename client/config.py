import json
import os
import sys
from pathlib import Path


DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
DEFAULT_PARENT_INVITE = ""
DEFAULT_HEARTBEAT_INTERVAL = 60
DEFAULT_RECONNECT_INTERVAL = 10
DEFAULT_NODE_STORAGE_DIR = ""
DEFAULT_MANAGE_PORT = 8787
DEFAULT_BUSINESS_MODE = "storage_share"


def load_client_config(config_path="node_config.json"):
    storage_explicit = False
    config = {
        "server_url": DEFAULT_SERVER_URL,
        "parent_invite": DEFAULT_PARENT_INVITE,
        "heartbeat_interval": DEFAULT_HEARTBEAT_INTERVAL,
        "reconnect_interval": DEFAULT_RECONNECT_INTERVAL,
        "storage_dir": DEFAULT_NODE_STORAGE_DIR,
        "storage_explicit": False,
        "storage_quota_gb": 0,
        "manage_port": DEFAULT_MANAGE_PORT,
        "business_mode": DEFAULT_BUSINESS_MODE,
    }
    path = Path(config_path)
    if path.exists():
        try:
            file_config = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                storage_explicit = bool(str(file_config.get("storage_dir") or "").strip())
                config.update({key: value for key, value in file_config.items() if value not in (None, "")})
        except Exception:
            pass
    config["server_url"] = os.getenv("NODE_SERVER_URL", config["server_url"])
    config["parent_invite"] = os.getenv("NODE_PARENT_INVITE", config["parent_invite"])
    config["heartbeat_interval"] = int(os.getenv("NODE_HEARTBEAT_INTERVAL", config["heartbeat_interval"]))
    config["reconnect_interval"] = int(os.getenv("NODE_RECONNECT_INTERVAL", config["reconnect_interval"]))
    env_storage_dir = os.getenv("NODE_STORAGE_DIR")
    if env_storage_dir:
        storage_explicit = True
        config["storage_dir"] = env_storage_dir
    else:
        config["storage_dir"] = config["storage_dir"]
    config["storage_explicit"] = storage_explicit
    config["storage_quota_gb"] = float(os.getenv("NODE_STORAGE_QUOTA_GB", config.get("storage_quota_gb") or 0) or 0)
    config["manage_port"] = int(os.getenv("NODE_MANAGE_PORT", config["manage_port"]))
    config["business_mode"] = (
        os.getenv("NODE_BUSINESS_MODE", os.getenv("BUSINESS_MODE", config.get("business_mode", DEFAULT_BUSINESS_MODE)))
        .strip()
        or DEFAULT_BUSINESS_MODE
    )
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


def get_storage_quota_arg():
    for arg in sys.argv[1:]:
        if arg.startswith("storage_quota_gb=") or arg.startswith("--storage-quota-gb=") or arg.startswith("--storage_quota_gb="):
            return float(arg.split("=", 1)[1].strip())
    return 0
