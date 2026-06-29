import os
import secrets
from pathlib import Path


RUNTIME_SECRET_KEYS = ("ADMIN_API_TOKEN", "SESSION_SECRET", "AES_KEY")


def parse_env_file_values(env_path):
    path = Path(env_path)
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def generate_runtime_secret(key):
    if key == "AES_KEY":
        return secrets.token_hex(8)
    if key == "SESSION_SECRET":
        return secrets.token_urlsafe(48)
    return secrets.token_urlsafe(32)


def ensure_runtime_secrets(env_path=None, environ=None, print_func=print):
    from db import BASE_DIR

    path = Path(env_path) if env_path else BASE_DIR / ".env"
    target_environ = environ if environ is not None else os.environ
    env_values = parse_env_file_values(path)
    generated = {}
    for key in RUNTIME_SECRET_KEYS:
        existing = target_environ.get(key) or env_values.get(key)
        if existing:
            target_environ[key] = existing
            continue
        value = generate_runtime_secret(key)
        target_environ[key] = value
        generated[key] = value

    if generated:
        if path.exists():
            existing_text = path.read_text(encoding="utf-8")
            prefix = "" if existing_text.endswith(("\n", "\r\n")) or not existing_text else "\n"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            prefix = ""
        with path.open("a", encoding="utf-8") as handle:
            if prefix:
                handle.write(prefix)
            handle.write("# Auto-generated runtime secrets\n")
            for key, value in generated.items():
                handle.write(f"{key}={value}\n")
        print_func("已自动生成运行密钥，并写入 .env：")
        for key, value in generated.items():
            print_func(f"{key}={value}")
        print_func("后台登录地址：http://127.0.0.1:8000/admin/login")
    return generated
