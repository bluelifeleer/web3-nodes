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
DEFAULT_PCDN_PROVIDER = "mock"
SUPPORTED_BUSINESS_MODES = {"storage_share", "pcdn_partner"}
BASE_DIR = Path(__file__).resolve().parents[1]


def normalize_client_business_mode(value=""):
    raw = str(value or "").split("#", 1)[0].strip().lower().replace("-", "_")
    if raw in ("pcdn", "pcdn_partner", "partner_pcdn"):
        return "pcdn_partner"
    if raw in SUPPORTED_BUSINESS_MODES:
        return raw
    return DEFAULT_BUSINESS_MODE


def normalize_client_pcdn_provider(value=""):
    raw = str(value or "").split("#", 1)[0].strip().lower().replace("_", "-")
    return raw or DEFAULT_PCDN_PROVIDER


def unique_paths(paths):
    seen = set()
    result = []
    for path in paths:
        if path is None:
            continue
        try:
            resolved = Path(path).expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def client_runtime_dirs():
    dirs = [Path.cwd()]
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
    dirs.extend([BASE_DIR, BASE_DIR / "client"])
    return unique_paths(dirs)


def resolve_client_config_path(config_path="node_config.json"):
    path = Path(config_path)
    if path.is_absolute():
        return path if path.exists() else None
    for base_dir in client_runtime_dirs():
        candidate = base_dir / path
        if candidate.exists():
            return candidate
    return path if path.exists() else None


def candidate_client_env_paths(env_path=None):
    if env_path:
        return unique_paths([env_path])
    paths = [BASE_DIR / "client" / ".env", BASE_DIR / ".env", Path.cwd() / ".env"]
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / ".env")
    return unique_paths(paths)


def read_client_env_file(path):
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_client_env_values(env_path=None):
    values = {}
    for path in candidate_client_env_paths(env_path):
        values.update(read_client_env_file(path))
    return values


def load_client_config(config_path="node_config.json", env_path=None):
    env_values = {}
    if os.getenv("WEB3_NODES_SKIP_DOTENV") != "1":
        env_values = load_client_env_values(env_path)

    def config_env(primary_key, default=""):
        if primary_key in os.environ:
            return os.environ[primary_key]
        return env_values.get(primary_key, default)

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
        "pcdn_provider": DEFAULT_PCDN_PROVIDER,
    }
    path = resolve_client_config_path(config_path)
    if path and path.exists():
        try:
            file_config = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                storage_explicit = bool(str(file_config.get("storage_dir") or "").strip())
                config.update({key: value for key, value in file_config.items() if value not in (None, "")})
        except Exception:
            pass
    config["server_url"] = config_env("NODE_SERVER_URL", config["server_url"])
    config["parent_invite"] = config_env("NODE_PARENT_INVITE", config["parent_invite"])
    config["heartbeat_interval"] = int(config_env("NODE_HEARTBEAT_INTERVAL", config["heartbeat_interval"]))
    config["reconnect_interval"] = int(config_env("NODE_RECONNECT_INTERVAL", config["reconnect_interval"]))
    env_storage_dir = config_env("NODE_STORAGE_DIR", "")
    if env_storage_dir:
        storage_explicit = True
        config["storage_dir"] = env_storage_dir
    else:
        config["storage_dir"] = config["storage_dir"]
    config["storage_explicit"] = storage_explicit
    config["storage_quota_gb"] = float(config_env("NODE_STORAGE_QUOTA_GB", config.get("storage_quota_gb") or 0) or 0)
    config["manage_port"] = int(config_env("NODE_MANAGE_PORT", config["manage_port"]))
    config["business_mode"] = normalize_client_business_mode(
        config_env("NODE_BUSINESS_MODE", config_env("BUSINESS_MODE", config.get("business_mode", DEFAULT_BUSINESS_MODE)))
    )
    config["pcdn_provider"] = normalize_client_pcdn_provider(
        config_env("NODE_PCDN_PROVIDER", config_env("PCDN_PROVIDER", config.get("pcdn_provider", DEFAULT_PCDN_PROVIDER)))
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
