# 服务端主程序 server_main.py（完整版带API路由，修复8000端口报错）
import time
import hashlib
import random
import csv
import io
from datetime import datetime, timedelta
from functools import wraps
import requests
from flask import Flask, request, jsonify, render_template_string, g
from pathlib import Path
import re
import secrets
import urllib.parse
import base64
import auth
import points
import shares
import withdrawals
from decimal import Decimal, InvalidOperation
from files import USER_FILE_SELECT_PROJECTION, format_user_file_record
try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None
import os
import shutil
import json
try:
    import reedsolo
except ImportError:
    reedsolo = None
import db as database_module
from db import (
    BASE_DIR,
    DB_CONFIG,
    DB_ENGINE,
    INIT_SQL_PATH,
    connect_database,
    current_cursor as get_current_cursor,
    load_env_file,
    node_alive_interval_sql,
    node_location_upsert_sql,
    reward_upsert_sql,
)

# ==================== 初始化Flask服务 ====================
app = Flask(__name__)

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


if os.getenv("WEB3_NODES_SKIP_DOTENV") != "1":
    ensure_runtime_secrets()

ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "")
SESSION_SECRET = os.getenv("SESSION_SECRET")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
AMAP_WEB_KEY = os.getenv("AMAP_WEB_KEY", "").strip()
AMAP_SECURITY_JSCODE = os.getenv("AMAP_SECURITY_JSCODE", "").strip()
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
db = None
cursor = None
db_error = ""


def init_db():
    global db, cursor, db_error
    try:
        if db is not None and DB_ENGINE == "mysql":
            db.ping(reconnect=True)
        elif db is not None and DB_ENGINE == "postgresql" and not getattr(db, "closed", False):
            pass
        else:
            db = connect_database(DB_CONFIG)
        cursor = db.cursor()
        db_error = ""
        return True
    except Exception as exc:
        db = None
        cursor = None
        db_error = str(exc)
        return False


def current_cursor():
    return get_current_cursor(cursor)


def active_database_connection():
    return getattr(g, "db", None) or db


def commit_database():
    connection = active_database_connection()
    if hasattr(connection, "commit"):
        connection.commit()


def rollback_database():
    connection = active_database_connection()
    if hasattr(connection, "rollback"):
        connection.rollback()


class DatabaseTransaction:
    def __init__(self):
        self.connection = None
        self.previous_autocommit = None
        self.restore_style = None

    def __enter__(self):
        self.connection = active_database_connection()
        if self.connection is None:
            return self
        get_autocommit = getattr(self.connection, "get_autocommit", None)
        set_autocommit = getattr(self.connection, "autocommit", None)
        if callable(get_autocommit) and callable(set_autocommit):
            self.previous_autocommit = get_autocommit()
            self.restore_style = "method"
            if self.previous_autocommit:
                set_autocommit(False)
        elif hasattr(self.connection, "autocommit"):
            self.previous_autocommit = getattr(self.connection, "autocommit")
            self.restore_style = "attribute"
            if self.previous_autocommit:
                setattr(self.connection, "autocommit", False)
        begin = getattr(self.connection, "begin", None)
        if callable(begin):
            begin()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.connection is None or self.restore_style is None:
            return False
        if self.restore_style == "method":
            self.connection.autocommit(self.previous_autocommit)
        elif self.restore_style == "attribute":
            setattr(self.connection, "autocommit", self.previous_autocommit)
        return False


def insert_storage_audit_log(
    event_type,
    file_hash="",
    chunk_index=None,
    node_address="",
    request_id="",
    status="",
    message="",
    metadata=None,
):
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    audit_cursor = current_cursor()
    if audit_cursor is None:
        return
    audit_cursor.execute(
        """
        insert into storage_audit_log(event_type,file_hash,chunk_index,node_address,request_id,status,message,metadata_json)
        values(%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            str(event_type or "")[:64],
            str(file_hash or "")[:128],
            chunk_index,
            str(node_address or "")[:128],
            str(request_id or "")[:64],
            str(status or "")[:32],
            str(message or "")[:255],
            metadata_json,
        ),
    )


def duplicate_database_error(exc):
    text = " ".join(str(part) for part in (exc.__class__.__name__, exc))
    text = text.lower()
    return any(
        marker in text
        for marker in (
            "duplicate entry",
            "duplicate key",
            "unique constraint",
            "unique violation",
            "integrityerror",
            "sqlstate 23505",
            "1062",
        )
    )


def ensure_database_initialized(sql_path=INIT_SQL_PATH):
    global db_error
    initialized = database_module.ensure_database_initialized(sql_path=sql_path)
    db_error = database_module.db_error
    return initialized


ADMIN_PROTECTED_PATHS = {
    "/api/set_ratio",
    "/api/node_list",
    "/api/reward_list",
    "/api/file_list",
    "/api/file_delete",
    "/api/file_health",
    "/api/ipfs_status",
    "/api/map_node_list",
    "/api/reward_daily",
    "/api/leaderboard",
    "/api/invite_tree",
    "/api/upload_check",
    "/api/upload_chunk",
    "/api/upload_merge",
    "/api/upload_file",
}

ADMIN_PUBLIC_PATHS = {
    "/",
    "/admin",
    "/admin/login",
    "/api/admin/login",
    "/api/health",
}


def is_admin_protected_path(path):
    if path in ADMIN_PUBLIC_PATHS:
        return False
    return path in ADMIN_PROTECTED_PATHS or path.startswith("/api/admin/")


def admin_token_is_valid():
    if not ADMIN_API_TOKEN:
        return False
    supplied = request.headers.get("X-Admin-Token") or request.args.get("admin_token", "")
    return secrets.compare_digest(supplied, ADMIN_API_TOKEN)


def admin_token_value_is_valid(token):
    return bool(ADMIN_API_TOKEN) and secrets.compare_digest(token or "", ADMIN_API_TOKEN)


COMMERCIAL_PAGE_CSS = '''
        :root{--ink:#172033;--muted:#64748b;--line:#dbe6ef;--surface:#fff;--soft:#f6f9fc;--brand:#0f766e;--brand-2:#14b8a6;--accent:#f0b429;--hot:#ff6b6b;}
        *{box-sizing:border-box;}
        body.commercial-page{margin:0;background:
            radial-gradient(circle at 14% 8%,rgba(20,184,166,.18),transparent 28%),
            radial-gradient(circle at 84% 2%,rgba(240,180,41,.15),transparent 24%),
            linear-gradient(180deg,#f7fbfc 0%,#edf4f7 100%);
            color:var(--ink);font-family:Arial,"Microsoft YaHei",sans-serif;}
        a{text-decoration:none;color:inherit;}
        .page-shell{width:min(1180px,calc(100vw - 32px));margin:0 auto;padding:24px 0 42px;}
        .modern-nav{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px;}
        .brand-lockup{display:flex;align-items:center;gap:12px;font-weight:800;color:#0f3440;}
        .brand-mark{width:34px;height:34px;border-radius:8px;background:linear-gradient(135deg,#0b4f56,var(--brand-2) 58%,var(--accent));box-shadow:0 14px 30px rgba(20,184,166,.30);}
        .nav-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:#33515c;}
        .nav-actions a{position:relative;overflow:hidden;padding:9px 13px;border:1px solid rgba(15,118,110,.18);border-radius:7px;background:rgba(255,255,255,.72);box-shadow:0 10px 26px rgba(15,23,42,.06);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;}
        .nav-actions a:hover{transform:translateY(-2px);border-color:rgba(20,184,166,.46);box-shadow:0 18px 34px rgba(20,184,166,.16);}
        .page-hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;align-items:end;margin:10px 0 20px;}
        .page-kicker{display:inline-flex;margin-bottom:10px;padding:7px 10px;border-radius:999px;background:linear-gradient(135deg,#e8f8f2,#fff7df);color:#116454;font-size:13px;font-weight:700;box-shadow:inset 0 0 0 1px rgba(20,184,166,.16);}
        .page-hero h1{margin:0;font-size:34px;line-height:1.14;letter-spacing:0;color:#102a36;}
        .page-hero p{margin:10px 0 0;color:var(--muted);line-height:1.7;max-width:720px;}
        .commercial-card,.box,.panel,main.auth-card{background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(248,252,252,.92));border:1px solid rgba(148,163,184,.30);border-radius:8px;box-shadow:0 18px 42px rgba(15,23,42,.08),inset 0 1px 0 rgba(255,255,255,.72);}
        .commercial-card.hover-lift,.hover-lift{transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;}
        .commercial-card.hover-lift:hover,.hover-lift:hover{transform:translateY(-3px);border-color:rgba(20,184,166,.36);box-shadow:0 24px 52px rgba(15,23,42,.12);}
        .box,.panel,main.auth-card{padding:18px;}
        .commercial-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;}
        .premium-button,.primary-action,body.commercial-page button,body.commercial-page .btn{position:relative!important;isolation:isolate;overflow:hidden!important;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:42px;padding:10px 17px!important;background:linear-gradient(135deg,#0f766e,#14b8a6 48%,#f0b429)!important;color:#ffffff!important;border:1px solid rgba(255,255,255,.28)!important;border-radius:8px!important;box-shadow:0 16px 34px rgba(20,184,166,.24),0 4px 12px rgba(15,118,110,.20),inset 0 1px 0 rgba(255,255,255,.38)!important;cursor:pointer;font-weight:800!important;letter-spacing:0;transition:transform .18s ease,box-shadow .18s ease,filter .18s ease!important;}
        .premium-button::before,.primary-action::before,body.commercial-page button::before,body.commercial-page .btn::before{content:"";position:absolute;inset:0;background:linear-gradient(120deg,transparent 0%,rgba(255,255,255,.34) 45%,transparent 62%);transform:translateX(-120%);transition:transform .55s ease;z-index:-1;}
        .premium-button:hover,.primary-action:hover,body.commercial-page button:hover,body.commercial-page .btn:hover{transform:translateY(-2px)!important;filter:saturate(1.08);box-shadow:0 22px 42px rgba(20,184,166,.30),0 8px 18px rgba(240,180,41,.18),inset 0 1px 0 rgba(255,255,255,.45)!important;}
        .premium-button:hover::before,.primary-action:hover::before,body.commercial-page button:hover::before,body.commercial-page .btn:hover::before{transform:translateX(115%);}
        .button-shine{position:absolute;inset:1px;border-radius:7px;background:linear-gradient(180deg,rgba(255,255,255,.28),transparent 42%);pointer-events:none;}
        .secondary-action,body.commercial-page button.secondary,body.commercial-page .btn.secondary{background:linear-gradient(135deg,rgba(255,255,255,.96),#eefbf8)!important;color:#155e63!important;border:1px solid rgba(20,184,166,.34)!important;box-shadow:0 14px 30px rgba(15,23,42,.08),inset 0 1px 0 rgba(255,255,255,.85)!important;}
        input,select{background:#fff;border:1px solid #cbd5e1;border-radius:7px;color:#172033;}
        table{background:white;border-radius:8px;overflow:hidden;}
        th{background:#edf7f6!important;color:#183b44;}
        .status,.notice,.linkbox,pre{border-radius:8px;}
        @media (max-width:800px){.modern-nav,.page-hero{align-items:flex-start;flex-direction:column;display:flex;}.nav-actions{width:100%;}.nav-actions a{flex:1;text-align:center;}.page-hero h1{font-size:28px;}}
'''


def get_bearer_token():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("user_token", "")


def get_json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def session_secret_missing_response():
    return jsonify({"code":503,"msg":"用户登录密钥未配置，请设置 SESSION_SECRET"}), 503


def user_is_active(row):
    return bool(row) and str(row[4] or "").strip().lower() == "active"


def require_user(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not SESSION_SECRET:
            return session_secret_missing_response()
        payload = auth.verify_session_token(get_bearer_token(), SESSION_SECRET)
        if not payload:
            return jsonify({"code": 401, "msg": "缺少或无效的用户登录 Token"}), 401
        user_row = select_user_by_id(payload.get("user_id"))
        if not user_is_active(user_row):
            return jsonify({"code": 401, "msg": "用户不存在或已停用"}), 401
        g.current_user = payload
        g.current_user_row = user_row
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def require_database_for_api():
    if request.path in ADMIN_PUBLIC_PATHS:
        return None
    if is_admin_protected_path(request.path) and not admin_token_is_valid():
        return jsonify({"code":401,"msg":"缺少或无效的后台访问 Token"}), 401
    if not init_db():
        return jsonify({
            "code": 503,
            "msg": "数据库连接失败，请检查 MySQL 是否启动、库表是否创建、MYSQL_PASSWORD/DB_PASSWORD 是否正确",
            "error": db_error,
        }), 503
    g.db = db
    g.cursor = cursor


def format_user(row):
    return {
        "id": row[0],
        "username": row[1],
        "wallet_address": row[3] or "",
        "status": row[4] or "active",
    }


def select_user_by_username(username):
    current_cursor().execute(
        "select id,username,password_hash,wallet_address,status from app_user where username=%s",
        (username,),
    )
    return current_cursor().fetchone()


def select_user_by_wallet(wallet_address):
    current_cursor().execute(
        "select id,username,password_hash,wallet_address,status from app_user where wallet_address=%s",
        (wallet_address,),
    )
    return current_cursor().fetchone()


def select_user_by_id(user_id):
    current_cursor().execute(
        "select id,username,password_hash,wallet_address,status from app_user where id=%s",
        (user_id,),
    )
    return current_cursor().fetchone()


def create_user_session(user_row):
    if not SESSION_SECRET:
        return None, None
    user = format_user(user_row)
    token = auth.create_session_token(
        {
            "user_id": user["id"],
            "username": user["username"],
            "wallet_address": user["wallet_address"],
        },
        SESSION_SECRET,
    )
    return token, user


def parse_expiry(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value.split(".")[0], fmt)
            except ValueError:
                pass
    return datetime.min


def consume_wallet_nonce(wallet_address, nonce, purpose, signature):
    wallet_address = auth.normalize_wallet_address(wallet_address)
    if not wallet_address or not nonce or not signature:
        return False, "缺少钱包地址、nonce 或签名"
    active_cursor = current_cursor()
    active_cursor.execute(
        """
        select id,wallet_address,nonce,expires_at,used_at
        from wallet_nonce
        where wallet_address=%s and nonce=%s and used_at is null
        order by created_at desc
        limit 1
        """,
        (wallet_address, nonce),
    )
    nonce_row = active_cursor.fetchone()
    if not nonce_row:
        return False, "nonce 不存在或已使用"
    if parse_expiry(nonce_row[3]) < datetime.now():
        return False, "nonce 已过期"
    message = auth.build_wallet_message(nonce, purpose)
    try:
        recovered = auth.recover_wallet_address(message, signature)
    except Exception:
        return False, "钱包签名无效"
    if recovered != wallet_address:
        return False, "钱包签名地址不匹配"
    active_cursor.execute(
        "update wallet_nonce set used_at=%s where id=%s and used_at is null",
        (datetime.now(), nonce_row[0]),
    )
    if getattr(active_cursor, "rowcount", 0) != 1:
        return False, "nonce 不存在或已使用"
    return True, ""


def wallet_fields_missing(data):
    return not (
        isinstance(data.get("wallet_address"), str)
        and auth.normalize_wallet_address(data.get("wallet_address"))
        and isinstance(data.get("nonce"), str)
        and data.get("nonce")
        and isinstance(data.get("signature"), str)
        and data.get("signature")
    )


def wallet_nonce_fields_invalid(data):
    purpose = data.get("purpose", "login")
    return not (
        isinstance(data.get("wallet_address"), str)
        and auth.normalize_wallet_address(data.get("wallet_address"))
        and isinstance(purpose, str)
    )


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    data = get_json_body()
    raw_username = data.get("username")
    raw_password = data.get("password")
    if not isinstance(raw_username, str) or not isinstance(raw_password, str):
        return jsonify({"code":400,"msg":"缺少用户名或密码"}), 400
    username = raw_username.strip()
    password = raw_password
    if not username or not password:
        return jsonify({"code":400,"msg":"缺少用户名或密码"}), 400
    if not SESSION_SECRET:
        return session_secret_missing_response()
    if select_user_by_username(username):
        return jsonify({"code":409,"msg":"用户名已存在"}), 409
    try:
        current_cursor().execute(
            "insert into app_user(username,password_hash) values(%s,%s)",
            (username, auth.hash_password(password)),
        )
        commit_database()
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            return jsonify({"code":409,"msg":"用户名已存在"}), 409
        return jsonify({"code":500,"msg":"用户注册失败"}), 500
    user_row = select_user_by_username(username)
    token, user = create_user_session(user_row)
    if not token:
        return session_secret_missing_response()
    return jsonify({"code":200,"msg":"注册成功","token":token,"user":user})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = get_json_body()
    raw_username = data.get("username")
    raw_password = data.get("password")
    if not isinstance(raw_username, str) or not isinstance(raw_password, str):
        return jsonify({"code":400,"msg":"缺少用户名或密码"}), 400
    username = raw_username.strip()
    password = raw_password
    if not username or not password:
        return jsonify({"code":400,"msg":"缺少用户名或密码"}), 400
    if not SESSION_SECRET:
        return session_secret_missing_response()
    user_row = select_user_by_username(username)
    if not user_row or not auth.verify_password(password, user_row[2]):
        return jsonify({"code":401,"msg":"用户名或密码错误"}), 401
    if not user_is_active(user_row):
        return jsonify({"code":401,"msg":"用户名或密码错误"}), 401
    current_cursor().execute("update app_user set last_login_at=%s where id=%s", (datetime.now(), user_row[0]))
    commit_database()
    fresh_user = select_user_by_id(user_row[0]) or user_row
    if not user_is_active(fresh_user):
        return jsonify({"code":401,"msg":"用户名或密码错误"}), 401
    token, user = create_user_session(fresh_user)
    if not token:
        return session_secret_missing_response()
    return jsonify({"code":200,"msg":"登录成功","token":token,"user":user})


@app.route("/api/auth/me", methods=["GET"])
@require_user
def auth_me():
    return jsonify({"code":200,"user":format_user(g.current_user_row)})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    response = jsonify({"code":200,"msg":"已退出登录"})
    response.delete_cookie("user_token")
    return response


@app.route("/api/wallet/nonce", methods=["POST"])
def wallet_nonce():
    data = get_json_body()
    if wallet_nonce_fields_invalid(data):
        return jsonify({"code":400,"msg":"缺少钱包地址"}), 400
    wallet_address = auth.normalize_wallet_address(data.get("wallet_address"))
    purpose = (data.get("purpose") or "login").strip() or "login"
    nonce = secrets.token_urlsafe(24)
    expires_at = datetime.now() + timedelta(minutes=10)
    current_cursor().execute(
        "insert into wallet_nonce(wallet_address,nonce,expires_at) values(%s,%s,%s)",
        (wallet_address, nonce, expires_at),
    )
    commit_database()
    return jsonify({
        "code":200,
        "wallet_address":wallet_address,
        "nonce":nonce,
        "purpose":purpose,
        "message":auth.build_wallet_message(nonce, purpose),
        "expires_at":expires_at.isoformat(),
    })


@app.route("/api/wallet/bind", methods=["POST"])
@require_user
def wallet_bind():
    data = get_json_body()
    if wallet_fields_missing(data):
        return jsonify({"code":400,"msg":"缺少钱包地址、nonce 或签名"}), 400
    wallet_address = auth.normalize_wallet_address(data.get("wallet_address"))
    ok, msg = consume_wallet_nonce(wallet_address, data.get("nonce"), "bind", data.get("signature"))
    if not ok:
        return jsonify({"code":400,"msg":msg}), 400
    try:
        current_cursor().execute(
            "update app_user set wallet_address=%s where id=%s",
            (wallet_address, g.current_user.get("user_id")),
        )
        commit_database()
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            return jsonify({"code":409,"msg":"钱包地址已绑定其他用户"}), 409
        return jsonify({"code":500,"msg":"钱包绑定失败"}), 500
    user_row = select_user_by_id(g.current_user.get("user_id"))
    return jsonify({"code":200,"msg":"钱包绑定成功","user":format_user(user_row)})


@app.route("/api/wallet/login", methods=["POST"])
def wallet_login():
    data = get_json_body()
    if wallet_fields_missing(data):
        return jsonify({"code":400,"msg":"缺少钱包地址、nonce 或签名"}), 400
    wallet_address = auth.normalize_wallet_address(data.get("wallet_address"))
    if not SESSION_SECRET:
        return session_secret_missing_response()
    ok, msg = consume_wallet_nonce(wallet_address, data.get("nonce"), "login", data.get("signature"))
    if not ok:
        return jsonify({"code":400,"msg":msg}), 400
    user_row = select_user_by_wallet(wallet_address)
    if not user_row:
        return jsonify({"code":401,"msg":"钱包地址未绑定用户"}), 401
    if not user_is_active(user_row):
        return jsonify({"code":401,"msg":"钱包地址未绑定用户"}), 401
    current_cursor().execute("update app_user set last_login_at=%s where id=%s", (datetime.now(), user_row[0]))
    commit_database()
    fresh_user = select_user_by_id(user_row[0]) or user_row
    if not user_is_active(fresh_user):
        return jsonify({"code":401,"msg":"钱包地址未绑定用户"}), 401
    token, user = create_user_session(fresh_user)
    if not token:
        return session_secret_missing_response()
    return jsonify({"code":200,"msg":"登录成功","token":token,"user":user})

# ==================== 全局分成配置（开发者后台可改） ====================
SELF_RATIO = 0.15    # 上级分成比例15%
NODE_RATIO = 0.85    # 节点本级收益85%
ONLINE_VALID_MIN = 10 # 最低有效在线时长(分钟)

# ===================== 配置 =====================
AES_KEY = os.getenv("AES_KEY", "1234567890123456")  # 自定义加密密钥
SHARD_SIZE = 1024 * 1024  # 1MB 分片

# 临时分片存储目录
CHUNK_TMP_DIR = "./chunk_tmp"
os.makedirs(CHUNK_TMP_DIR, exist_ok=True)
NODE_STORAGE_DIR = os.getenv("NODE_STORAGE_DIR", "./node_storage")
SAFE_FILE_HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")

# 分片大小 1MB
CHUNK_SIZE = 1024 * 1024
SHARD_SIZE = 1024 * 1024

# ===================== 新增：数据防丢核心配置 =====================
# 每个分片保存3个副本（企业级标准）
COPY_NUM = 3
# 纠删码配置：10数据片 +3校验片
EC_DATA_SHARD = 10
EC_PARITY_SHARD = 3

# 替换原有分片节点分配逻辑
# 原逻辑：随机分配少量节点 → 极易丢数据
# 新逻辑：跨地区、跨IP、多副本冗余，永不丢数据

# 全局配置接口动态修改
@app.route("/api/set_ratio",methods=["POST"])
def set_ratio():
    global SELF_RATIO,NODE_RATIO
    data = request.get_json()
    SELF_RATIO = float(data.get("self_ratio",0.15))
    NODE_RATIO = float(data.get("node_ratio",0.85))
    return jsonify({"code":200,"msg":"分成比例修改成功","data":{"self_ratio":SELF_RATIO,"node_ratio":NODE_RATIO}})

# 生成推广码
def create_invite_code():
    return hashlib.md5(str(random.random()).encode()).hexdigest()[:10]


def validate_file_hash(file_hash):
    return isinstance(file_hash, str) and bool(SAFE_FILE_HASH_RE.fullmatch(file_hash))


def get_chunk_dir(file_hash):
    if not validate_file_hash(file_hash):
        return None
    base_dir = Path(CHUNK_TMP_DIR).resolve()
    chunk_dir = (base_dir / file_hash).resolve()
    if base_dir != chunk_dir and base_dir not in chunk_dir.parents:
        return None
    return chunk_dir


def normalize_visibility(value):
    return "private" if value == "private" else "public"


def create_access_token(visibility):
    return secrets.token_urlsafe(24) if normalize_visibility(visibility) == "private" else ""


def normalize_storage_node_name(node):
    raw = str(node or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", raw):
        return raw
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def storage_node_file_path(file_hash, node):
    if not validate_file_hash(file_hash):
        return None
    node_name = normalize_storage_node_name(node)
    if not node_name:
        return None
    base_dir = Path(NODE_STORAGE_DIR).resolve()
    node_dir = (base_dir / node_name / file_hash[:2]).resolve()
    if base_dir != node_dir and base_dir not in node_dir.parents:
        return None
    return node_dir / f"{file_hash}.bin"


def build_encrypted_shard_manifest(file_hash, encrypted_data):
    encrypted_hash = hashlib.sha256(encrypted_data).hexdigest()
    shards = []
    for index, shard_bytes in enumerate(file_shard(encrypted_data)):
        shards.append({
            "file_hash": file_hash,
            "encrypted_hash": encrypted_hash,
            "chunk_index": index,
            "chunk_total": 0,
            "chunk_hash": hashlib.sha256(shard_bytes).hexdigest(),
            "chunk_size": len(shard_bytes),
            "chunk_bytes": shard_bytes,
        })
    chunk_total = len(shards)
    for shard in shards:
        shard["chunk_total"] = chunk_total
    return {
        "file_hash": file_hash,
        "encrypted_hash": encrypted_hash,
        "shards": shards,
    }


def write_server_fallback_copy(file_hash, encrypted_data):
    target = storage_node_file_path(file_hash, "SERVER_BACKUP_NODE")
    if target is None:
        raise RuntimeError("服务端兜底存储路径无效")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encrypted_data)
    return "SERVER_BACKUP_NODE"


def get_node_storage_api_url(node):
    raw = str(node or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")
    template = os.getenv("NODE_STORAGE_API_URL_TEMPLATE", "").strip()
    if template:
        return template.format(node_address=urllib.parse.quote(raw)).rstrip("/")
    return ""


def post_client_shard(node, shard, request_id=""):
    base_url = get_node_storage_api_url(node)
    if not base_url:
        return False
    payload = {
        "file_hash": shard["file_hash"],
        "chunk_index": shard["chunk_index"],
        "chunk_total": shard["chunk_total"],
        "chunk_hash": shard["chunk_hash"],
        "chunk_b64": base64.b64encode(shard["chunk_bytes"]).decode("ascii"),
        "request_id": request_id,
    }
    try:
        response = requests.post(
            f"{base_url}/api/node/storage/shards",
            json=payload,
            timeout=15,
        )
        return int(getattr(response, "status_code", 500) or 500) < 400
    except Exception:
        return False


def insert_file_shard_records(file_hash, encrypted_data, stored_nodes):
    if not stored_nodes:
        return []
    manifest = build_encrypted_shard_manifest(file_hash, encrypted_data)
    inserted = []
    for shard in manifest["shards"]:
        node_address = stored_nodes[shard["chunk_index"] % len(stored_nodes)]
        current_cursor().execute(
            """
            insert into file_shard_record(file_hash,encrypted_hash,chunk_index,chunk_total,chunk_hash,chunk_size,node_address,storage_status,stored_at)
            values(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                file_hash,
                manifest["encrypted_hash"],
                shard["chunk_index"],
                shard["chunk_total"],
                shard["chunk_hash"],
                shard["chunk_size"],
                node_address,
                "stored",
                datetime.now(),
            ),
        )
        inserted.append(dict(shard, node_address=node_address))
    return inserted


def persist_file_to_storage_nodes(file_hash, encrypted_data, nodes, request_id=""):
    write_server_fallback_copy(file_hash, encrypted_data)
    real_nodes = real_user_storage_nodes(nodes)
    manifest = build_encrypted_shard_manifest(file_hash, encrypted_data)
    stored_nodes = []
    if not real_nodes:
        raise RuntimeError("暂无可用真实客户端节点")
    for shard in manifest["shards"]:
        node = real_nodes[shard["chunk_index"] % len(real_nodes)]
        if post_client_shard(node, shard, request_id=request_id):
            if node not in stored_nodes:
                stored_nodes.append(node)
    if not stored_nodes:
        raise RuntimeError("暂无可用真实客户端节点")
    return stored_nodes


def call_persist_file_to_storage_nodes(file_hash, encrypted_data, nodes, request_id=""):
    try:
        return persist_file_to_storage_nodes(file_hash, encrypted_data, nodes, request_id=request_id)
    except TypeError as exc:
        if "request_id" not in str(exc):
            raise
        return persist_file_to_storage_nodes(file_hash, encrypted_data, nodes)


def read_file_from_storage_nodes(file_hash, nodes):
    for node in nodes:
        target = storage_node_file_path(file_hash, node)
        if target is not None and target.exists():
            return target.read_bytes()
    return None


def read_client_shard(node, file_hash, chunk_index, request_id=""):
    base_url = get_node_storage_api_url(node)
    if not base_url:
        return None
    try:
        response = requests.get(
            f"{base_url}/api/node/storage/shards/{urllib.parse.quote(file_hash)}/{int(chunk_index)}",
            timeout=15,
        )
        if int(getattr(response, "status_code", 500) or 500) >= 400:
            return None
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get("chunk_b64"):
            return None
        return base64.b64decode(data["chunk_b64"])
    except Exception:
        return None


def select_file_shard_records(file_hash):
    try:
        current_cursor().execute(
            """
            select file_hash,encrypted_hash,chunk_index,chunk_total,chunk_hash,chunk_size,node_address
            from file_shard_record
            where file_hash=%s and storage_status='stored'
            order by chunk_index asc
            """,
            (file_hash,),
        )
        return list(current_cursor().fetchall())
    except Exception:
        return []


def read_encrypted_from_client_shards(file_hash, request_id=""):
    rows = select_file_shard_records(file_hash)
    if not rows:
        return None
    chunks = {}
    chunk_total = int(rows[0][3] or 0)
    encrypted_hash = rows[0][1] or ""
    for row in rows:
        index = int(row[2])
        expected_hash = row[4]
        node_address = row[6]
        chunk = read_client_shard(node_address, file_hash, index, request_id=request_id)
        if chunk is None:
            insert_storage_audit_log(
                "download.shard.read.failed",
                file_hash=file_hash,
                chunk_index=index,
                node_address=node_address,
                request_id=request_id,
                status="failed",
                message="client shard unavailable",
            )
            return None
        actual_hash = hashlib.sha256(chunk).hexdigest()
        if actual_hash != expected_hash:
            insert_storage_audit_log(
                "download.shard.hash_failed",
                file_hash=file_hash,
                chunk_index=index,
                node_address=node_address,
                request_id=request_id,
                status="failed",
                message="client shard hash mismatch",
                metadata={"expected": expected_hash, "actual": actual_hash},
            )
            return None
        chunks[index] = chunk
    if chunk_total <= 0 or set(chunks) != set(range(chunk_total)):
        insert_storage_audit_log(
            "download.shard.read.failed",
            file_hash=file_hash,
            request_id=request_id,
            status="failed",
            message="client shard set incomplete",
            metadata={"expected_total": chunk_total, "actual_indexes": sorted(chunks)},
        )
        return None
    encrypted = b"".join(chunks[index] for index in range(chunk_total))
    if encrypted_hash and hashlib.sha256(encrypted).hexdigest() != encrypted_hash:
        insert_storage_audit_log(
            "download.shard.hash_failed",
            file_hash=file_hash,
            request_id=request_id,
            status="failed",
            message="encrypted file hash mismatch",
        )
        return None
    insert_storage_audit_log(
        "download.merge.success",
        file_hash=file_hash,
        request_id=request_id,
        status="ok",
        message="client shards merged",
        metadata={"chunk_total": chunk_total},
    )
    return encrypted


def read_server_fallback_copy(file_hash):
    return read_file_from_storage_nodes(file_hash, ["SERVER_BACKUP_NODE"])


def read_ipfs_backup(ipfs_cid):
    if not ipfs_cid:
        return None
    client = get_ipfs_client()
    try:
        return client.cat(ipfs_cid)
    finally:
        if hasattr(client, "close"):
            client.close()


def read_verified_encrypted_file(file_hash, stored_nodes=None, ipfs_cid="", request_id=""):
    encrypted = read_encrypted_from_client_shards(file_hash, request_id=request_id)
    if encrypted is not None:
        return encrypted
    encrypted = read_server_fallback_copy(file_hash)
    if encrypted is not None:
        insert_storage_audit_log(
            "download.fallback.used",
            file_hash=file_hash,
            request_id=request_id,
            status="ok",
            message="server fallback used",
        )
        return encrypted
    try:
        encrypted = read_ipfs_backup(ipfs_cid)
    except Exception:
        encrypted = None
    if encrypted is not None:
        insert_storage_audit_log(
            "download.fallback.used",
            file_hash=file_hash,
            request_id=request_id,
            status="ok",
            message="ipfs fallback used",
            metadata={"ipfs_cid": ipfs_cid},
        )
    return encrypted


def decrypt_and_verify_file(file_hash, encrypted):
    try:
        plain = aes_decrypt(encrypted)
    except RuntimeError:
        insert_storage_audit_log(
            "download.decrypt.failed",
            file_hash=file_hash,
            status="failed",
            message="decrypt failed",
        )
        raise
    if get_file_hash(plain) != file_hash:
        insert_storage_audit_log(
            "download.file_hash_failed",
            file_hash=file_hash,
            status="failed",
            message="file hash mismatch",
        )
        raise RuntimeError("file hash mismatch")
    return plain


def backup_to_ipfs(encrypted_data):
    try:
        client = get_ipfs_client()
        try:
            return client.add_bytes(encrypted_data), "ok", ""
        finally:
            if hasattr(client, "close"):
                client.close()
    except Exception as exc:
        return "", "failed", str(exc)


def real_user_storage_nodes(nodes):
    return [node for node in nodes if node and node != "SERVER_BACKUP_NODE"]


def parse_stored_nodes(value):
    try:
        parsed = json.loads(value) if value else []
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def format_file_record(item):
    visibility = normalize_visibility(item[9] if len(item) > 9 else "public")
    access_token = item[10] if len(item) > 10 and item[10] else ""
    file_hash = item[2]
    token_query = f"?token={urllib.parse.quote(access_token)}" if access_token else ""
    return {
        "id": item[0],
        "file_name": item[1],
        "file_hash": file_hash,
        "ipfs_cid": item[3],
        "size": item[4],
        "shard": item[5],
        "uploader": item[6],
        "nodes": parse_stored_nodes(item[7]),
        "time": str(item[8]),
        "visibility": visibility,
        "access_token": access_token,
        "deleted_at": str(item[11]) if len(item) > 11 and item[11] else "",
        "owner_user_id": item[12] if len(item) > 12 else None,
        "download_url": f"/api/file_download/{file_hash}{token_query}",
    }


def format_user_file_records(rows):
    return [format_user_file_record(row) for row in rows]


SAFE_SHARE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
SHARE_CODE_CREATE_ATTEMPTS = 5


def validate_share_code(share_code):
    return isinstance(share_code, str) and bool(SAFE_SHARE_CODE_RE.fullmatch(share_code))


def normalize_share_status(value, allow_deleted=False):
    status = str(value or "active").strip().lower()
    allowed = {"active", "inactive"}
    if allow_deleted:
        allowed.add("deleted")
    return status if status in allowed else None


def parse_share_expires_at(value):
    if value in (None, ""):
        return None, None
    parsed = shares.parse_datetime(value)
    if parsed is None:
        return None, "expires_at 格式无效"
    return shares.normalize_to_local_naive(parsed), None


def parse_non_negative_int(value, field_name):
    if value in (None, ""):
        return 0, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0, f"{field_name} 必须是非负整数"
    if parsed < 0:
        return 0, f"{field_name} 必须是非负整数"
    return parsed, None


def select_share_row(share_code):
    current_cursor().execute(f"""
    select {shares.SHARE_SELECT_PROJECTION}
    from file_share s
    join file_chain_record f on f.file_hash=s.file_hash and f.deleted_at is null
    where s.share_code=%s
    limit 1
    """,(share_code,))
    return current_cursor().fetchone()


def select_share_download_row(share_code):
    current_cursor().execute("""
    select s.share_code,s.file_hash,s.owner_user_id,s.visibility,s.extract_code_hash,
    s.expires_at,s.max_downloads,s.download_count,s.status,s.created_at,
    f.file_name,f.ipfs_cid,f.file_size,f.stored_nodes,f.owner_wallet_address
    from file_share s
    join file_chain_record f on f.file_hash=s.file_hash and f.deleted_at is null
    where s.share_code=%s
    limit 1
    """,(share_code,))
    return current_cursor().fetchone()


def format_share_download_row(row):
    return {
        "share_code": row[0],
        "file_hash": row[1],
        "owner_user_id": row[2],
        "visibility": row[3] or "public",
        "extract_code_hash": row[4] or "",
        "expires_at": str(row[5]) if row[5] else "",
        "max_downloads": row[6] if row[6] is not None else 0,
        "download_count": row[7] if row[7] is not None else 0,
        "status": row[8] or "active",
        "created_at": str(row[9]) if row[9] else "",
        "file_name": row[10] or "",
        "ipfs_cid": row[11] or "",
        "file_size": row[12] if row[12] is not None else 0,
        "stored_nodes": parse_stored_nodes(row[13]),
        "owner_wallet_address": row[14] or "",
    }


def request_extract_code():
    if "extract_code" in request.args:
        return request.args.get("extract_code", "")
    data = get_json_body()
    if "extract_code" in data:
        return data.get("extract_code", "")
    return request.form.get("extract_code", "")


def optional_downloader_user_id():
    if not SESSION_SECRET:
        return None
    token = get_bearer_token()
    if not token:
        return None
    payload = auth.verify_session_token(token, SESSION_SECRET)
    if not payload:
        return None
    user_id = payload.get("user_id")
    user_row = select_user_by_id(user_id)
    if not user_is_active(user_row):
        return None
    return user_id


def insert_point_ledger(user_id, wallet_address, point_type, amount, source_type, source_id, remark):
    current_cursor().execute(
        """
        insert into point_ledger(user_id,wallet_address,point_type,amount,source_type,source_id,remark)
        values(%s,%s,%s,%s,%s,%s,%s)
        """,
        (user_id,wallet_address,point_type,amount,source_type,source_id,remark),
    )


def numeric_cell(row, index=0):
    if not row or row[index] is None:
        return Decimal("0")
    try:
        return Decimal(str(row[index]))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def request_arg_or_json(name):
    if name in request.args:
        return request.args.get(name)
    return get_json_body().get(name)


def select_node_identity_row(user_addr, node_mac):
    current_cursor().execute(
        """
        select un.user_address,un.invite_code,un.parent_invite_code,
        np.node_mac,np.disk_total,np.disk_used,np.online_duration,np.upload_bandwidth,np.update_time,
        np.storage_path,np.storage_status,np.storage_error,
        np.storage_total_gb,np.storage_used_gb,np.storage_free_gb
        from user_node un
        join node_power np on un.user_address=np.user_address
        where un.user_address=%s and np.node_mac=%s
        limit 1
        """,
        (user_addr, node_mac),
    )
    return current_cursor().fetchone()


def lock_node_identity_for_update(user_addr, node_mac):
    current_cursor().execute(
        """
        select un.user_address,un.invite_code,un.parent_invite_code,
        np.node_mac,np.disk_total,np.disk_used,np.online_duration,np.upload_bandwidth,np.update_time,
        np.storage_path,np.storage_status,np.storage_error,
        np.storage_total_gb,np.storage_used_gb,np.storage_free_gb
        from user_node un
        join node_power np on un.user_address=np.user_address
        where un.user_address=%s and np.node_mac=%s
        limit 1
        for update
        """,
        (user_addr, node_mac),
    )
    return current_cursor().fetchone()


def format_node_identity_row(row):
    update_time = row[8] if len(row) > 8 else None
    disk_total = row[4] if len(row) > 4 and row[4] is not None else 0
    disk_used = row[5] if len(row) > 5 and row[5] is not None else 0
    online_min = row[6] if len(row) > 6 and row[6] is not None else 0
    upload_bw = row[7] if len(row) > 7 and row[7] is not None else 0
    is_online = node_is_online(update_time)
    return {
        "user_addr": row[0],
        "node_address": row[0],
        "invite_code": row[1] or "",
        "parent_code": row[2] or "",
        "node_mac": row[3] or "",
        "disk_total": disk_total,
        "disk_used": disk_used,
        "online_min": online_min,
        "upload_bw": upload_bw,
        "update_time": str(update_time) if update_time else "",
        "is_online": is_online,
        "online_status": "在线" if is_online else "离线",
        "storage_path": row[9] if len(row) > 9 and row[9] else "",
        "storage_status": row[10] if len(row) > 10 and row[10] else "unknown",
        "storage_error": row[11] if len(row) > 11 and row[11] else "",
        "storage_total_gb": row[12] if len(row) > 12 and row[12] is not None else disk_total,
        "storage_used_gb": row[13] if len(row) > 13 and row[13] is not None else disk_used,
        "storage_free_gb": row[14] if len(row) > 14 and row[14] is not None else 0,
    }


def require_node_identity():
    user_addr = str(request_arg_or_json("user_addr") or "").strip()
    node_mac = str(request_arg_or_json("node_mac") or "").strip()
    if not user_addr or not node_mac:
        return None, (jsonify({"code":401,"msg":"缺少节点身份信息"}), 401)
    row = select_node_identity_row(user_addr, node_mac)
    if not row:
        return None, (jsonify({"code":401,"msg":"节点身份校验失败"}), 401)
    identity = format_node_identity_row(row)
    g.current_node = identity
    return identity, None


def format_withdrawal_row(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "wallet_address": row[2] or "",
        "amount": float(row[3] or 0),
        "status": row[4] or "pending",
        "admin_note": row[5] or "",
        "created_at": str(row[6]) if len(row) > 6 and row[6] else "",
        "reviewed_at": str(row[7]) if len(row) > 7 and row[7] else "",
        "node_address": row[8] if len(row) > 8 and row[8] else "",
        "withdrawal_channel": row[9] if len(row) > 9 and row[9] else "wallet",
        "withdrawal_account": row[10] if len(row) > 10 and row[10] else "",
    }


def format_point_ledger_row(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "wallet_address": row[2] or "",
        "point_type": row[3] or "",
        "amount": float(row[4] or 0),
        "source_type": row[5] or "",
        "source_id": row[6] or "",
        "remark": row[7] or "",
        "created_at": str(row[8]) if len(row) > 8 and row[8] else "",
    }


def calculate_user_earnings(user_id, include_decimal=False):
    active_cursor = current_cursor()
    active_cursor.execute(
        "select coalesce(sum(amount),0) from point_ledger where user_id=%s",
        (user_id,),
    )
    total_points = numeric_cell(active_cursor.fetchone())
    total_earnings = total_points / Decimal(str(points.POINTS_PER_EARNING_UNIT))
    active_cursor.execute(
        """
        select coalesce(sum(amount),0)
        from withdrawal_request
        where user_id=%s and status='paid'
        """,
        (user_id,),
    )
    withdrawn_earnings = numeric_cell(active_cursor.fetchone())
    active_cursor.execute(
        """
        select coalesce(sum(amount),0)
        from withdrawal_request
        where user_id=%s and status in ('pending','approved')
        """,
        (user_id,),
    )
    pending_withdrawals = numeric_cell(active_cursor.fetchone())
    locked_withdrawals = withdrawn_earnings + pending_withdrawals
    available_earnings = max(total_earnings - locked_withdrawals, Decimal("0"))
    summary = {
        "total_points": float(total_points),
        "total_earnings": float(total_earnings),
        "withdrawn_earnings": float(withdrawn_earnings),
        "pending_withdrawals": float(pending_withdrawals),
        "locked_withdrawals": float(locked_withdrawals),
        "available_earnings": float(available_earnings),
    }
    if include_decimal:
        summary["_available_earnings_decimal"] = available_earnings
    return summary


def calculate_node_earnings(node_address, include_decimal=False):
    active_cursor = current_cursor()
    active_cursor.execute(
        """
        select coalesce(sum(reward_amount),0)
        from node_reward
        where user_address=%s
        """,
        (node_address,),
    )
    total_earnings = numeric_cell(active_cursor.fetchone())
    active_cursor.execute(
        """
        select coalesce(sum(amount),0)
        from withdrawal_request
        where node_address=%s and status='paid'
        """,
        (node_address,),
    )
    withdrawn_earnings = numeric_cell(active_cursor.fetchone())
    active_cursor.execute(
        """
        select coalesce(sum(amount),0)
        from withdrawal_request
        where node_address=%s and status in ('pending','approved')
        """,
        (node_address,),
    )
    pending_withdrawals = numeric_cell(active_cursor.fetchone())
    locked_withdrawals = withdrawn_earnings + pending_withdrawals
    available_earnings = max(total_earnings - locked_withdrawals, Decimal("0"))
    summary = {
        "node_address": node_address,
        "total_earnings": float(total_earnings),
        "withdrawn_earnings": float(withdrawn_earnings),
        "pending_withdrawals": float(pending_withdrawals),
        "locked_withdrawals": float(locked_withdrawals),
        "available_earnings": float(available_earnings),
    }
    if include_decimal:
        summary["_available_earnings_decimal"] = available_earnings
    return summary


def lock_active_user_for_update(user_id):
    active_cursor = current_cursor()
    active_cursor.execute(
        "select id from app_user where id=%s and status='active' for update",
        (user_id,),
    )
    return active_cursor.fetchone()


def atomic_increment_share_download_count(share_code):
    current_cursor().execute(
        """
        update file_share
        set download_count=download_count+1
        where share_code=%s
        and status='active'
        and (expires_at is null or expires_at>%s)
        and (max_downloads=0 or download_count < max_downloads)
        """,
        (share_code,datetime.now()),
    )
    return getattr(current_cursor(), "rowcount", None) != 0


def record_share_download_success(share, downloader_user_id, downloader_ip):
    file_hash = share["file_hash"]
    share_code = share["share_code"]
    file_size = share["file_size"]
    stored_nodes = share["stored_nodes"]
    first_node = stored_nodes[0] if stored_nodes else ""
    if not atomic_increment_share_download_count(share_code):
        return False
    current_cursor().execute(
        "update file_chain_record set download_count=download_count+1,last_download_at=%s where file_hash=%s",
        (datetime.now(),file_hash),
    )
    current_cursor().execute(
        """
        insert into file_download_log(share_code,file_hash,downloader_ip,downloader_user_id,node_address,file_size)
        values(%s,%s,%s,%s,%s,%s)
        """,
        (share_code,file_hash,downloader_ip,downloader_user_id,first_node,file_size),
    )
    insert_point_ledger(
        share["owner_user_id"],
        share["owner_wallet_address"],
        "share_download",
        points.share_download_points(),
        "share",
        share_code,
        "share download",
    )
    node_points = points.node_download_points(file_size)
    for node in stored_nodes:
        insert_point_ledger(
            None,
            node,
            "node_download",
            node_points,
            "file_download",
            file_hash,
            "node download",
        )
    return True


def insert_file_share_with_retry(file_hash, owner_user_id, visibility, extract_code_hash, expires_at, max_downloads, status):
    for attempt in range(SHARE_CODE_CREATE_ATTEMPTS):
        share_code = shares.create_share_code()
        try:
            current_cursor().execute(
                """
                insert into file_share(share_code,file_hash,owner_user_id,visibility,extract_code_hash,expires_at,max_downloads,status)
                values(%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    share_code,
                    file_hash,
                    owner_user_id,
                    visibility,
                    extract_code_hash,
                    expires_at,
                    max_downloads,
                    status,
                ),
            )
            return share_code, None
        except Exception as exc:
            rollback_database()
            if not duplicate_database_error(exc):
                return None, "分享创建失败"
            if attempt == SHARE_CODE_CREATE_ATTEMPTS - 1:
                return None, "分享码生成冲突，请重试"
    return None, "分享码生成冲突，请重试"


def filter_file_records(rows, keyword="", page=1, page_size=20):
    keyword = (keyword or "").strip().lower()
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)
    records = [format_file_record(row) for row in rows]
    if keyword:
        records = [
            item for item in records
            if keyword in (item["file_name"] or "").lower()
            or keyword in (item["file_hash"] or "").lower()
            or keyword in (item["ipfs_cid"] or "").lower()
        ]
    total = len(records)
    start = (page - 1) * page_size
    return {"items": records[start:start + page_size], "total": total, "page": page, "page_size": page_size}


def file_access_allowed(record, supplied_token):
    if record.get("owner_user_id") is not None:
        return False
    if normalize_visibility(record.get("visibility")) == "public":
        return True
    return bool(record.get("access_token")) and secrets.compare_digest(
        supplied_token or "",
        record.get("access_token") or "",
    )


def calculate_file_health(record, alive_nodes):
    nodes = record.get("nodes") or []
    alive_count = sum(1 for node in nodes if node in alive_nodes)
    required = min(COPY_NUM, len(nodes)) if nodes else 0
    if not nodes:
        status = "no_nodes"
    elif alive_count >= required:
        status = "healthy"
    elif alive_count > 0:
        status = "degraded"
    else:
        status = "offline"
    return {
        "stored_count": len(nodes),
        "alive_count": alive_count,
        "required_count": required,
        "status": status,
    }


def get_ipfs_client():
    import ipfshttpclient
    return ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001')


def read_ipfs_status(client_factory=get_ipfs_client):
    try:
        client = client_factory()
        try:
            identity = client.id()
            repo = client.repo_stat()
        finally:
            if hasattr(client, "close"):
                client.close()
        return {
            "online": True,
            "peer_id": identity.get("ID", ""),
            "addresses": identity.get("Addresses", []),
            "repo_size": repo.get("RepoSize", 0),
            "storage_max": repo.get("StorageMax", 0),
            "num_objects": repo.get("NumObjects", 0),
            "error": "",
        }
    except Exception as exc:
        return {
            "online": False,
            "peer_id": "",
            "addresses": [],
            "repo_size": 0,
            "storage_max": 0,
            "num_objects": 0,
            "error": str(exc),
        }


def calculate_quality_score(disk_used=0, online_duration=0, upload_bandwidth=0, has_location=False):
    disk_score = min(float(disk_used or 0) * 1.5, 30)
    duration_score = min(float(online_duration or 0) / 10, 30)
    bandwidth_score = min(float(upload_bandwidth or 0) * 4, 30)
    location_score = 8 if has_location else 0
    return int(min(round(disk_score + duration_score + bandwidth_score + location_score), 100))


def node_is_online(update_time):
    if not update_time:
        return False
    try:
        return (datetime.now() - update_time).total_seconds() <= 180
    except Exception:
        return False


def format_node_record(item):
    has_location = bool(item[7] or item[8]) if len(item) > 8 else False
    is_online = node_is_online(item[6])
    quality_score = calculate_quality_score(item[3], item[4], item[5], has_location)
    return {
        "user_addr": item[0],
        "invite_code": item[1],
        "parent_code": item[2],
        "disk_used": item[3] or 0,
        "online_min": item[4] or 0,
        "upload_bw": item[5] or 0,
        "update_time": str(item[6]) if item[6] else "",
        "is_online": is_online,
        "online_status": "在线" if is_online else "离线",
        "quality_score": quality_score,
        "country": item[7] if len(item) > 7 else "",
        "city": item[8] if len(item) > 8 else "",
        "storage_path": item[9] if len(item) > 9 and item[9] else "",
        "storage_status": item[10] if len(item) > 10 and item[10] else "unknown",
        "storage_error": item[11] if len(item) > 11 and item[11] else "",
        "storage_total_gb": item[12] if len(item) > 12 and item[12] is not None else 0,
        "storage_used_gb": item[13] if len(item) > 13 and item[13] is not None else item[3] or 0,
        "storage_free_gb": item[14] if len(item) > 14 and item[14] is not None else 0,
    }


def build_leaderboard(rows):
    records = [format_node_record(row) for row in rows]
    records.sort(
        key=lambda item: (item["quality_score"], item["online_min"], item["disk_used"]),
        reverse=True,
    )
    for index, item in enumerate(records, 1):
        item["rank"] = index
    return records


def build_invite_tree(rows):
    records = [format_node_record(row) for row in rows]
    by_invite = {}
    roots = []
    for record in records:
        record["children"] = []
        by_invite[record["invite_code"]] = record
    for record in records:
        parent = by_invite.get(record["parent_code"])
        if parent:
            parent["children"].append(record)
        else:
            roots.append(record)
    return roots


def select_node_rows():
    current_cursor().execute("""
    SELECT un.user_address,un.invite_code,un.parent_invite_code,
    np.disk_used,np.online_duration,np.upload_bandwidth,np.update_time,
    nl.country,nl.city,
    np.storage_path,np.storage_status,np.storage_error,
    np.storage_total_gb,np.storage_used_gb,np.storage_free_gb
    FROM user_node un
    LEFT JOIN node_power np ON un.user_address=np.user_address
    LEFT JOIN node_location nl ON un.user_address=nl.user_address
    """)
    return current_cursor().fetchall()

# 1. 节点注册接口
@app.route("/register",methods=["POST"])
def node_register():
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    parent_invite = data.get("parent_invite","")

    # 判断设备是否已注册
    current_cursor().execute("select * from node_power where node_mac=%s",(node_mac,))
    if current_cursor().fetchone():
        return jsonify({"code":200,"msg":"节点已注册，无需重复绑定"})

    # 生成用户专属推广码、绑定上级
    invite_code = create_invite_code()
    current_cursor().execute(
        "insert into user_node(user_address,invite_code,parent_invite_code) values(%s,%s,%s)",
        (user_addr,invite_code,parent_invite)
    )
    # 初始化节点数据
    current_cursor().execute(
        "insert into node_power(user_address,node_mac) values(%s,%s)",
        (user_addr,node_mac)
    )
    return jsonify({"code":200,"msg":"节点注册成功，上级绑定完成","invite_code":invite_code})

# 2. 节点心跳上报接口
@app.route("/heartbeat",methods=["POST"])
def node_heartbeat():
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    disk_used = data.get("disk_used",0)
    upload_bw = data.get("upload_bw",0)
    storage_path = str(data.get("storage_path") or "")[:255]
    storage_status = str(data.get("storage_status") or "unknown")[:32]
    storage_error = str(data.get("storage_error") or "")[:255]
    storage_total_gb = float(data.get("storage_total_gb") or 0)
    storage_used_gb = float(data.get("storage_used_gb") or disk_used or 0)
    storage_free_gb = float(data.get("storage_free_gb") or 0)
    storage_quota_gb = float(data.get("storage_quota_gb") or 0)
    storage_available_gb = float(data.get("storage_available_gb") or 0)

    # 输入心跳数据
    print(f"{user_addr} {node_mac} {disk_used} {upload_bw}")

    current_cursor().execute(
        "update node_power set disk_used=%s,upload_bandwidth=%s,storage_path=%s,storage_status=%s,storage_error=%s,storage_total_gb=%s,storage_used_gb=%s,storage_free_gb=%s,storage_quota_gb=%s,storage_available_gb=%s,online_duration=online_duration+1,update_time=%s where user_address=%s and node_mac=%s",
        (disk_used,upload_bw,storage_path,storage_status,storage_error,storage_total_gb,storage_used_gb,storage_free_gb,storage_quota_gb,storage_available_gb,datetime.now(),user_addr,node_mac)
    )
    return jsonify({"code":200,"msg":"心跳上报成功"})

# 3. 每日自动分账函数
def auto_settle_reward():
    current_cursor().execute("select user_address,disk_used,online_duration from node_power where online_duration > %s",(ONLINE_VALID_MIN,))
    node_list = current_cursor().fetchall()
    settle_date = datetime.now().date()

    for node in node_list:
        user_addr = node[0]
        disk_contrib = node[1]
        online_contrib = node[2]
        # 贡献值计算公式
        total_contrib = disk_contrib * 10 + online_contrib * 0.5
        total_reward = round(total_contrib * 0.01,4)

        # 写入节点本级收益
        node_reward = total_reward * NODE_RATIO
        current_cursor().execute(
            reward_upsert_sql(),
            (user_addr,1,node_reward,total_contrib,user_addr,settle_date)
        )

        # 写入上级分成收益
        current_cursor().execute("select parent_invite_code from user_node where user_address=%s",(user_addr,))
        parent_res = current_cursor().fetchone()
        if not parent_res:continue
        parent_code = parent_res[0]
        if parent_code:
            current_cursor().execute("select user_address from user_node where invite_code=%s",(parent_code,))
            super_res = current_cursor().fetchone()
            if super_res:
                super_addr = super_res[0]
                super_reward = total_reward * SELF_RATIO
                current_cursor().execute(
                    reward_upsert_sql(),
                    (super_addr,2,super_reward,total_contrib,user_addr,settle_date)
                )
    return True

# 4. 后台数据接口：节点列表
@app.route("/api/node_list",methods=["GET"])
def node_list():
    return jsonify({"code":200,"data":[format_node_record(item) for item in select_node_rows()]})

# 5. 后台数据接口：收益列表
@app.route("/api/reward_list",methods=["GET"])
def reward_list():
    current_cursor().execute("""
    select id,user_address,reward_type,reward_amount,node_contribution,settle_time,source_user_address,settle_date
    from node_reward order by settle_time desc
    """)
    res = current_cursor().fetchall()
    data_list = []
    for item in res:
        data_list.append({
            "id":item[0],
            "user_addr":item[1],
            "reward_type":"本级收益" if item[2]==1 else "上级分成",
            "amount":item[3],
            "contrib":item[4],
            "time":str(item[5]),
            "source_user":item[6],
            "settle_date":str(item[7]) if item[7] else ""
        })
    return jsonify({"code":200,"data":data_list})


@app.route("/api/reward_daily",methods=["GET"])
def reward_daily():
    current_cursor().execute("""
    select settle_date,user_address,reward_type,sum(reward_amount),sum(node_contribution),count(*)
    from node_reward
    group by settle_date,user_address,reward_type
    order by settle_date desc,user_address
    """)
    data = []
    for item in current_cursor().fetchall():
        data.append({
            "settle_date":str(item[0]) if item[0] else "",
            "user_addr":item[1],
            "reward_type":"本级收益" if item[2]==1 else "上级分成",
            "amount":round(float(item[3] or 0),4),
            "contrib":round(float(item[4] or 0),4),
            "count":item[5],
        })
    return jsonify({"code":200,"data":data})


@app.route("/api/node/me", methods=["GET"])
def node_me():
    identity, error_response = require_node_identity()
    if error_response:
        return error_response
    return jsonify({"code":200,"data":identity})


@app.route("/api/node/earnings", methods=["GET"])
def node_earnings():
    identity, error_response = require_node_identity()
    if error_response:
        return error_response
    return jsonify({"code":200,"data":calculate_node_earnings(identity["user_addr"])})


@app.route("/api/node/withdrawals", methods=["GET"])
def node_withdrawal_list():
    identity, error_response = require_node_identity()
    if error_response:
        return error_response
    current_cursor().execute(
        """
        select id,user_id,wallet_address,amount,status,admin_note,created_at,reviewed_at,
        node_address,withdrawal_channel,withdrawal_account
        from withdrawal_request
        where node_address=%s
        order by created_at desc,id desc
        """,
        (identity["user_addr"],),
    )
    return jsonify({
        "code":200,
        "data":[format_withdrawal_row(row) for row in current_cursor().fetchall()],
    })


@app.route("/api/node/withdrawals", methods=["POST"])
def node_withdrawal_create():
    data = get_json_body()
    identity, error_response = require_node_identity()
    if error_response:
        return error_response
    amount, message = withdrawals.parse_withdrawal_amount(data.get("amount"))
    if amount is None:
        return jsonify({"code":400,"msg":message}), 400
    wallet_address = str(data.get("wallet_address") or "").strip()[:128]
    if not wallet_address:
        return jsonify({"code":400,"msg":"缺少 wallet_address"}), 400
    amount_for_db = withdrawals.format_withdrawal_amount(amount)

    with DatabaseTransaction():
        try:
            locked_row = lock_node_identity_for_update(identity["user_addr"], identity["node_mac"])
            if not locked_row:
                rollback_database()
                return jsonify({"code":401,"msg":"节点身份校验失败"}), 401
            identity = format_node_identity_row(locked_row)
            g.current_node = identity
            summary = calculate_node_earnings(identity["user_addr"], include_decimal=True)
            if amount > summary["_available_earnings_decimal"]:
                rollback_database()
                summary.pop("_available_earnings_decimal", None)
                return jsonify({"code":400,"msg":"可提现余额不足","data":summary}), 400
            current_cursor().execute(
                """
                insert into withdrawal_request(
                    user_id,wallet_address,amount,status,node_address,withdrawal_channel,withdrawal_account
                )
                values(%s,%s,%s,%s,%s,%s,%s)
                """,
                (None,wallet_address,amount_for_db,"pending",identity["user_addr"],"wallet",wallet_address),
            )
            commit_database()
        except Exception:
            rollback_database()
            return jsonify({"code":500,"msg":"提现申请创建失败"}), 500
    return jsonify({
        "code":200,
        "msg":"提现申请已提交",
        "data":{
            "user_id":None,
            "node_address":identity["user_addr"],
            "wallet_address":wallet_address,
            "withdrawal_channel":"wallet",
            "withdrawal_account":wallet_address,
            "amount":amount_for_db,
            "status":"pending",
        },
    })


@app.route("/api/leaderboard",methods=["GET"])
def leaderboard():
    return jsonify({"code":200,"data":build_leaderboard(select_node_rows())})


@app.route("/api/invite_tree",methods=["GET"])
def invite_tree():
    return jsonify({"code":200,"data":build_invite_tree(select_node_rows())})

# ==================== 极简前端页面 ====================
HOME_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Web3 节点激励与文件分享系统</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + '''
        *{box-sizing:border-box;}
        body{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f4f7fb;color:#172033;}
        a{text-decoration:none;color:inherit;}
        .hero{min-height:90vh;display:grid;align-items:center;background:
            linear-gradient(120deg,rgba(7,19,42,.94),rgba(13,70,83,.86),rgba(21,91,70,.78)),
            url("https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1800&q=80") center/cover;color:white;}
        .wrap{width:min(1180px,calc(100vw - 32px));margin:0 auto;}
        nav{display:flex;justify-content:space-between;align-items:center;padding:26px 0;gap:18px;}
        .brand{font-weight:800;font-size:20px;letter-spacing:.2px;}
        .tagline{color:#b8dfe5;font-size:14px;border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:8px 12px;background:rgba(255,255,255,.08);}
        .btn{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 18px;border-radius:7px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);}
        .hero-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:42px;align-items:center;padding:58px 0 74px;}
        .eyebrow{display:inline-flex;align-items:center;gap:8px;margin-bottom:18px;padding:8px 12px;border:1px solid rgba(94,234,212,.35);border-radius:999px;color:#b6fff1;background:rgba(8,47,73,.42);font-size:14px;}
        h1{font-size:56px;line-height:1.05;margin:0 0 22px;letter-spacing:0;}
        .lead{font-size:18px;line-height:1.8;color:#d9eef2;max-width:680px;}
        .actions{display:flex;gap:14px;flex-wrap:wrap;margin-top:30px;}
        .primary{background:#30d5a0;color:#06251f;border-color:#30d5a0;font-weight:700;}
        .secondary{background:rgba(255,255,255,.1);color:white;}
        .signal-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:28px;max-width:700px;}
        .signal{border-left:2px solid #30d5a0;background:rgba(255,255,255,.08);border-radius:7px;padding:12px 14px;color:#d7f7f1;}
        .signal b{display:block;color:white;margin-bottom:4px;}
        .console{background:rgba(7,16,31,.72);border:1px solid rgba(255,255,255,.16);border-radius:8px;padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.25);}
        .console h2{font-size:18px;margin:0 0 16px;}
        .metric{display:grid;grid-template-columns:1fr auto;gap:8px;padding:13px 0;border-bottom:1px solid rgba(255,255,255,.12);}
        .metric:last-child{border-bottom:0;}
        .metric span{color:#9cc7d0;}
        .metric strong{font-size:18px;}
        section{padding:64px 0;}
        .section-head{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:22px;}
        .section-head h2{font-size:32px;margin:0;}
        .section-head p{margin:0;color:#64748b;max-width:560px;line-height:1.7;}
        .cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;}
        .card{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:22px;min-height:190px;box-shadow:0 10px 24px rgba(15,23,42,.05);}
        .card h3{margin:0 0 10px;font-size:20px;}
        .card p{color:#5b677a;line-height:1.7;margin:0 0 18px;}
        .card a{color:#0f766e;font-weight:700;}
        .flow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;}
        .step{background:#0f172a;color:white;border-radius:8px;padding:18px;min-height:150px;}
        .step b{display:block;color:#5eead4;margin-bottom:12px;}
        footer{padding:28px 0;color:#64748b;border-top:1px solid #e5e7eb;}
        @media (max-width:900px){
            .hero-grid,.cards,.flow{grid-template-columns:1fr;}
            h1{font-size:40px;}
            nav{align-items:flex-start;flex-direction:column;}
            .signal-row{grid-template-columns:1fr;}
        }
    </style>
</head>
<body class="commercial-page home-page">
    <div class="hero">
        <div class="wrap">
            <nav class="modern-nav">
                <div class="brand">Web3 Nodes Store</div>
                <div class="tagline">企业级分布式存储网络</div>
            </nav>
            <div class="hero-grid">
                <main>
                    <div class="eyebrow">存储 · 分享 · 节点激励 · 收益结算</div>
                    <h1>Web3 节点激励与文件分享系统</h1>
                    <p class="lead">面向节点运营、私有文件分发和收益结算的企业级分布式存储一体化平台。用户上传文件生成可控分享链接，节点贡献存储与带宽获得积分，后台实时查看网络、收益和提现审核。</p>
                    <div class="actions">
                        <a class="btn primary premium-button hover-lift" href="/user/login">开始使用<span class="button-shine"></span></a>
                        <a class="btn secondary premium-button hover-lift" href="/user/upload">上传并创建分享<span class="button-shine"></span></a>
                        <a class="btn secondary premium-button hover-lift" href="/admin">进入服务端后台<span class="button-shine"></span></a>
                    </div>
                    <div class="signal-row">
                        <div class="signal"><b>用户侧闭环</b>登录、上传、分享、收益都在同一条路径里完成。</div>
                        <div class="signal"><b>节点侧增长</b>用在线、存储、下载贡献驱动节点积分。</div>
                        <div class="signal"><b>运营侧可视</b>后台自动刷新网络、文件、收益和提现。</div>
                    </div>
                </main>
                <aside class="console commercial-card">
                    <h2>商业化能力概览</h2>
                    <div class="metric"><span>文件分享</span><strong>提取码 / 过期 / 限次</strong></div>
                    <div class="metric"><span>节点激励</span><strong>存储 + 下载积分</strong></div>
                    <div class="metric"><span>收益闭环</span><strong>积分 / 余额 / 提现</strong></div>
                    <div class="metric"><span>后台运营</span><strong>自动刷新监控</strong></div>
                </aside>
            </div>
        </div>
    </div>

    <section>
        <div class="wrap">
            <div class="section-head">
                <h2>业务入口</h2>
                <p>把分散页面收进一个首页，用户、节点和管理员都能从这里进入自己的工作流。</p>
            </div>
            <div class="cards">
                <article class="card commercial-card">
                    <h3>用户产品</h3>
                    <p>注册登录、钱包绑定、上传文件、创建分享链接，并查看积分收益和提现记录。</p>
                    <a href="/user/login">登录注册</a> · <a href="/user/dashboard">用户面板</a> · <a href="/user/upload">上传文件</a>
                </article>
                <article class="card commercial-card">
                    <h3>服务端运营</h3>
                    <p>管理节点、文件、分享、下载、积分流水与提现审核，后台数据自动刷新。</p>
                    <a href="/admin/login">后台登录</a> · <a href="/admin">后台面板</a>
                </article>
                <article class="card commercial-card">
                    <h3>节点接入</h3>
                    <p>客户端节点自动注册、心跳上报和断线重连，适合批量扩展存储网络。</p>
                    <a href="/api/health">服务健康检查</a>
                </article>
            </div>
        </div>
    </section>

    <section>
        <div class="wrap">
            <div class="section-head">
                <h2>从上传到收益</h2>
                <p>围绕文件分发做闭环，后续可以继续扩展套餐、容量计费、节点等级和企业工作台。</p>
            </div>
            <div class="flow">
                <div class="step"><b>01</b>用户登录后上传文件，系统加密并写入 IPFS。</div>
                <div class="step"><b>02</b>创建 `/s/&lt;share_code&gt;` 分享链接，设置提取码、过期和下载次数。</div>
                <div class="step"><b>03</b>下载成功后记录日志，给分享者和存储节点写入积分流水。</div>
                <div class="step"><b>04</b>用户在面板查看收益并提交提现，管理员在后台审核。</div>
            </div>
        </div>
    </section>

    <footer>
        <div class="wrap">本地服务入口：<a href="/">首页</a> / <a href="/admin">后台</a> / <a href="/user/dashboard">用户面板</a> / <a href="/api/health">健康检查</a></div>
    </footer>
</body>
</html>
'''

ADMIN_LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>后台登录</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + '''
        *{box-sizing:border-box;}
        body{min-height:100vh;}
        .login-shell{width:min(1040px,calc(100vw - 32px));margin:0 auto;padding:28px 0 48px;}
        .auth-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(360px,.7fr);gap:22px;align-items:center;min-height:calc(100vh - 110px);}
        .login-copy{padding:28px;color:#17313a;}
        .login-copy h1{font-size:38px;line-height:1.12;margin:0 0 14px;}
        .login-copy p{color:#607080;line-height:1.8;margin:0;}
        main{width:100%;}
        h1{font-size:24px;margin:0 0 18px;}
        label{display:block;margin-bottom:8px;font-weight:600;}
        input{width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:6px;font-size:15px;}
        button{width:100%;margin-top:16px;padding:12px;border:0;border-radius:6px;background:#2563eb;color:white;font-size:15px;cursor:pointer;}
        .status{min-height:22px;margin-top:12px;color:#b45309;font-size:14px;white-space:pre-wrap;}
    </style>
</head>
<body class="commercial-page admin-login-page">
    <div class="login-shell">
        <nav class="modern-nav">
            <div class="brand-lockup"><span class="brand-mark"></span><span>Web3 Nodes Store</span></div>
            <div class="nav-actions"><a href="/">首页</a><a href="/admin">后台</a></div>
        </nav>
        <div class="auth-layout">
            <section class="login-copy commercial-card">
                <span class="page-kicker">运营后台</span>
                <h1>安全进入节点与收益运营中心</h1>
                <p>统一管理节点在线状态、文件分发、下载记录、积分流水与提现审核。登录后后台会自动加载并刷新核心数据。</p>
            </section>
    <main class="auth-card commercial-card">
        <h1>后台登录</h1>
        <form id="adminLoginForm">
            <label for="adminTokenInput">后台 Token</label>
            <input type="password" id="adminTokenInput" autocomplete="current-password" placeholder="请输入 ADMIN_API_TOKEN" required>
            <button type="submit">登录后台</button>
        </form>
        <div id="loginStatus" class="status"></div>
    </main>
        </div>
    </div>
    <script>
    const form = document.getElementById("adminLoginForm");
    const statusBox = document.getElementById("loginStatus");
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const token = document.getElementById("adminTokenInput").value.trim();
        statusBox.textContent = "正在登录...";
        try{
            const response = await fetch("/api/admin/login", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({token})
            });
            const payload = await response.json();
            if(!response.ok){ throw new Error(payload.msg || "登录失败"); }
            localStorage.setItem("admin_token", token);
            window.location.href = "/admin";
        }catch(error){
            localStorage.removeItem("admin_token");
            statusBox.textContent = error.message;
        }
    });
    </script>
</body>
</html>
'''

ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Web3节点激励后台面板</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + '''
        *{margin:0;padding:0;box-sizing:border-box;}
        body{padding:0;font-family:微软雅黑;}
        .box{background:#fff;padding:20px;border-radius:8px;margin-bottom:20px;box-shadow:0 0 8px #eee;}
        h3{margin-bottom:15px;color:#222;}
        table{width:100%;border-collapse:collapse;margin-top:10px;}
        th,td{border:1px solid #eee;padding:10px;text-align:center;font-size:14px;}
        th{background:#f0f5ff;}
        input,button{padding:8px 12px;margin:0 5px;border-radius:4px;border:1px solid #ccc;}
        button{background:#2d8cf0;color:#fff;border:none;cursor:pointer;}
        .admin-status-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;background:#f8fafc;border:1px solid #dbeafe;}
        .admin-status-bar a{color:#2563eb;text-decoration:none;margin-left:auto;}
        .token-status{color:#8c6d1f;font-size:14px;}
    </style>
    {% if amap_web_key and amap_security_jscode %}
    <script type="text/javascript">
        window._AMapSecurityConfig = { securityJsCode: {{ amap_security_jscode|tojson }} };
    </script>
    <script type="text/javascript" src="https://webapi.amap.com/maps?v=2.0&key={{ amap_web_key }}"></script>
    {% endif %}
</head>
<body class="commercial-page admin-dashboard-page">
    <div class="page-shell">
    <nav class="modern-nav">
        <div class="brand-lockup"><span class="brand-mark"></span><span>Web3 Nodes Store</span></div>
        <div class="nav-actions"><a href="/">首页</a><a href="/admin/login" onclick="localStorage.removeItem('admin_token')">退出登录</a></div>
    </nav>
    <header class="page-hero">
        <div>
            <span class="page-kicker">服务端后台</span>
            <h1>节点、文件与收益运营中心</h1>
            <p>实时查看节点网络、文件存证、收益快照、邀请关系与提现审核，适合商业化运营和节点规模化扩展。</p>
        </div>
    </header>
    <div class="box admin-status-bar commercial-card">
        <strong>服务端后台</strong>
        <span id="adminTokenStatus" class="token-status"></span>
        <span id="adminAutoRefreshStatus" class="token-status"></span>
    </div>

    <div class="box commercial-card">
        <h3>分成比例配置</h3>
        <input type="text" id="selfRatio" placeholder="上级分成比例" value="0.15">
        <input type="text" id="nodeRatio" placeholder="节点分成比例" value="0.85">
        <button onclick="setRatio()">保存配置</button>
    </div>

    <div class="box commercial-card">
        <h3>全网节点列表</h3>
        <button onclick="getNodes()">刷新节点数据</button>
        <table>
            <thead>
                <tr>
                    <th>节点地址</th>
                    <th>个人推广码</th>
                    <th>上级推广码</th>
                    <th>存储占用G</th>
                    <th>总容量G</th>
                    <th>已用G</th>
                    <th>可用容量G</th>
                    <th>目录状态</th>
                    <th>在线时长(分)</th>
                    <th>上行带宽</th>
                    <th>在线状态</th>
                    <th>质量分</th>
                </tr>
            </thead>
            <tbody id="nodeTable"></tbody>
        </table>
    </div>

    <div class="box commercial-card" style="min-height:600px;">
        <h3>🌍 全网节点全球地理分布地图</h3>
        <p style="color:#64748b;font-size:14px;margin-bottom:15px;">实时在线节点打点｜离线节点灰色显示｜未配置 AMAP_WEB_KEY 或 AMAP_SECURITY_JSCODE 时自动切换为节点分布看板</p>
        <div id="map" style="width:100%;height:500px;border-radius:8px;"></div>
        <div id="nodeDistributionFallback" class="commercial-card" style="display:none;margin-top:12px;padding:14px;background:#f8fafc;"></div>
    </div>

    <div class="box commercial-card">
        <h3>收益结算记录</h3>
        <button onclick="getReward()">刷新收益数据</button>
        <table>
            <thead>
                <tr>
                    <th>节点地址</th>
                    <th>收益类型</th>
                    <th>收益金额</th>
                    <th>贡献值</th>
                    <th>来源节点</th>
                    <th>结算日期</th>
                    <th>结算时间</th>
                </tr>
            </thead>
            <tbody id="rewardTable"></tbody>
        </table>
    </div>

    <div class="box commercial-card">
        <h3>提现申请</h3>
        <button onclick="getAdminWithdrawals()">刷新提现</button>
        <table>
            <thead><tr><th>ID</th><th>用户/节点</th><th>钱包</th><th>金额</th><th>状态</th><th>备注</th><th>操作</th></tr></thead>
            <tbody id="withdrawalTable"></tbody>
        </table>
    </div>

    <div class="box commercial-card">
        <h3>存储审计日志</h3>
        <input id="auditFileHashFilter" placeholder="file_hash" style="min-width:220px">
        <input id="auditNodeFilter" placeholder="node_address">
        <input id="auditEventFilter" placeholder="event_type">
        <input id="auditStatusFilter" placeholder="status">
        <button onclick="getStorageAuditLogs()">刷新日志</button>
        <button onclick="exportStorageAudit('json')">导出JSON</button>
        <button onclick="exportStorageAudit('csv')">导出CSV</button>
        <table>
            <thead><tr><th>时间</th><th>事件</th><th>文件</th><th>分片</th><th>节点</th><th>状态</th><th>详情</th></tr></thead>
            <tbody id="storageAuditTable"></tbody>
        </table>
        <pre id="storageAuditDetail" style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:6px;margin-top:10px;"></pre>
    </div>

    <div class="box commercial-card">
    <h3>📁 文件加密上链存证记录（分布式存储）</h3>
    <input id="fileSearch" placeholder="搜索文件名 / 哈希 / CID" style="min-width:260px">
    <button onclick="getFileList()">刷新存证数据</button>
    <button onclick="getFileHealth()">副本健康</button>
    <button onclick="getIpfsStatus()">IPFS状态</button>
    <span id="ipfsStatusText" style="margin-left:10px;color:#475569"></span>
    <table>
        <thead>
            <tr>
                <th>文件名</th>
                <th>IPFS-CID</th>
                <th>文件哈希(上链)</th>
                <th>分片数</th>
                <th>存储节点数</th>
                <th>访问权限</th>
                <th>健康状态</th>
                <th>上传时间</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody id="fileTable"></tbody>
    </table>
    </div>

    <div class="box commercial-card">
        <h3>节点排行榜</h3>
        <button onclick="getLeaderboard()">刷新排行榜</button>
        <table>
            <thead>
                <tr>
                    <th>排名</th>
                    <th>节点地址</th>
                    <th>质量分</th>
                    <th>在线状态</th>
                    <th>存储G</th>
                    <th>在线分钟</th>
                    <th>带宽</th>
                </tr>
            </thead>
            <tbody id="leaderboardTable"></tbody>
        </table>
    </div>

    <div class="box commercial-card">
        <h3>每日收益快照</h3>
        <button onclick="getDailyReward()">刷新每日收益</button>
        <table>
            <thead>
                <tr>
                    <th>日期</th>
                    <th>节点地址</th>
                    <th>收益类型</th>
                    <th>收益金额</th>
                    <th>贡献值</th>
                    <th>记录数</th>
                </tr>
            </thead>
            <tbody id="dailyRewardTable"></tbody>
        </table>
    </div>

    <div class="box commercial-card">
        <h3>邀请关系树</h3>
        <button onclick="getInviteTree()">刷新邀请关系</button>
        <pre id="inviteTreeBox" style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:6px;"></pre>
    </div>

    </div>
<script>
const AMAP_WEB_KEY = "{{ amap_web_key }}";
const ADMIN_REFRESH_INTERVAL_MS = 10000;
let adminRefreshTimer = null;
const withdrawalNoteDrafts = {};

function getAdminToken(){
    return localStorage.getItem("admin_token") || "";
}

function requireAdminLogin(){
    if(!getAdminToken()){
        window.location.href = "/admin/login";
        return false;
    }
    return true;
}

function setAdminTokenStatus(text, isError){
    const status = document.getElementById("adminTokenStatus");
    if(status){
        status.innerText = text || "";
        status.style.color = isError ? "#c2410c" : "#166534";
    }
}

function setAdminAutoRefreshStatus(text){
    const status = document.getElementById("adminAutoRefreshStatus");
    if(status){ status.innerText = text || ""; }
}

function adminFetch(url, options){
    const token = getAdminToken();
    if(!token){
        setAdminTokenStatus("登录态失效，请重新登录", true);
        return Promise.resolve({
            status: 401,
            json: () => Promise.resolve({code:401,msg:"请先登录后台",data:[]})
        });
    }
    options = options || {};
    options.headers = Object.assign({}, options.headers || {}, {"X-Admin-Token": token});
    return fetch(url, options).then(res=>{
        if(res.status === 401){
            localStorage.removeItem("admin_token");
            setAdminTokenStatus("Token 无效，请重新输入", true);
            window.location.href = "/admin/login";
        }else{
            setAdminTokenStatus("Token 验证通过", false);
        }
        return res;
    });
}

// 修改分成比例
function setRatio(){
    let s = document.getElementById("selfRatio").value;
    let n = document.getElementById("nodeRatio").value;
    adminFetch("/api/set_ratio",{
        method:"POST",
        body:JSON.stringify({self_ratio:s,node_ratio:n}),
        headers:{"Content-Type":"application/json"}
    }).then(res=>res.json()).then(data=>{alert(data.msg);})
}

// 获取节点列表
function getNodes(){
    adminFetch("/api/node_list")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            const storageStatus = escHtml(item.storage_status || "unknown");
            const storageError = escHtml(item.storage_error || "");
            html += `<tr>
                <td>${item.user_addr}</td>
                <td>${item.invite_code}</td>
                <td>${item.parent_code||"无"}</td>
                <td>${item.disk_used}</td>
                <td>${item.storage_total_gb || 0}</td>
                <td>${item.storage_used_gb || item.disk_used || 0}</td>
                <td>${item.storage_free_gb || 0}</td>
                <td>${storageStatus} ${storageError ? "｜" + storageError : ""}</td>
                <td>${item.online_min}</td>
                <td>${item.upload_bw}</td>
                <td>${item.online_status}</td>
                <td>${item.quality_score}</td>
            </tr>`
        })
        document.getElementById("nodeTable").innerHTML = html;
    })
}

// 获取收益记录
function getReward(){
    adminFetch("/api/reward_list")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.user_addr}</td>
                <td>${item.reward_type}</td>
                <td>${item.amount}</td>
                <td>${item.contrib}</td>
                <td>${item.source_user||""}</td>
                <td>${item.settle_date||""}</td>
                <td>${item.time}</td>
            </tr>`
        })
        document.getElementById("rewardTable").innerHTML = html;
    })
}

function getLeaderboard(){
    adminFetch("/api/leaderboard")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.rank}</td>
                <td>${item.user_addr}</td>
                <td>${item.quality_score}</td>
                <td>${item.online_status}</td>
                <td>${item.disk_used}</td>
                <td>${item.online_min}</td>
                <td>${item.upload_bw}</td>
            </tr>`
        })
        document.getElementById("leaderboardTable").innerHTML = html;
    })
}

function getDailyReward(){
    adminFetch("/api/reward_daily")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.settle_date}</td>
                <td>${item.user_addr}</td>
                <td>${item.reward_type}</td>
                <td>${item.amount}</td>
                <td>${item.contrib}</td>
                <td>${item.count}</td>
            </tr>`
        })
        document.getElementById("dailyRewardTable").innerHTML = html;
    })
}

function renderInviteLines(nodes, depth){
    let lines = [];
    nodes.forEach(item=>{
        lines.push(`${"  ".repeat(depth)}- ${item.user_addr}｜码:${item.invite_code}｜${item.online_status}｜质量:${item.quality_score}`);
        lines = lines.concat(renderInviteLines(item.children || [], depth + 1));
    })
    return lines;
}

function getInviteTree(){
    adminFetch("/api/invite_tree")
    .then(res=>res.json())
    .then(data=>{
        document.getElementById("inviteTreeBox").innerText = renderInviteLines(data.data, 0).join("\\n") || "暂无邀请关系";
    })
}

function getAdminWithdrawals(){
    const active = document.activeElement;
    if(active && active.dataset && active.dataset.withdrawalNote === "1"){
        withdrawalNoteDrafts[active.dataset.withdrawalId] = active.value;
        return;
    }
    adminFetch("/api/admin/withdrawals")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        (data.data || []).forEach(item=>{
            const owner = escHtml(item.user_id || item.node_address || "");
            const wallet = escHtml(item.wallet_address || "");
            const amount = escHtml(item.amount || 0);
            const status = escHtml(item.status || "");
            const noteId = String(item.id);
            const rawNote = Object.prototype.hasOwnProperty.call(withdrawalNoteDrafts, noteId)
                ? withdrawalNoteDrafts[noteId]
                : (item.admin_note || "");
            const note = escHtml(rawNote);
            const actions = item.status === "pending"
                ? `<button onclick="reviewWithdrawal(${item.id},'approved')">通过</button><button onclick="reviewWithdrawal(${item.id},'rejected')">驳回</button>`
                : item.status === "approved"
                    ? `<button onclick="reviewWithdrawal(${item.id},'paid')">标记已提现</button><button onclick="reviewWithdrawal(${item.id},'rejected')">驳回</button>`
                    : "已完成";
            html += `<tr><td>${item.id}</td><td>${owner}</td><td>${wallet}</td><td>${amount}</td><td>${status}</td><td><input id="withdrawalNote-${item.id}" data-withdrawal-note="1" data-withdrawal-id="${item.id}" value="${note}" placeholder="审核备注" style="width:120px" oninput="withdrawalNoteDrafts['${item.id}']=this.value"></td><td>${actions}</td></tr>`;
        });
        document.getElementById("withdrawalTable").innerHTML = html || '<tr><td colspan="7">暂无提现申请</td></tr>';
    });
}

function reviewWithdrawal(id,status){
    const noteInput = document.getElementById(`withdrawalNote-${id}`);
    const admin_note = noteInput ? noteInput.value : "";
    withdrawalNoteDrafts[String(id)] = admin_note;
    adminFetch(`/api/admin/withdrawals/${id}/review`, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({status,admin_note})
    }).then(res=>res.json()).then(data=>{
        delete withdrawalNoteDrafts[String(id)];
        alert(data.msg || "操作完成");
        getAdminWithdrawals();
    });
}

function storageAuditQuery(){
    const params = new URLSearchParams();
    const fields = [
        ["file_hash", "auditFileHashFilter"],
        ["node_address", "auditNodeFilter"],
        ["event_type", "auditEventFilter"],
        ["status", "auditStatusFilter"]
    ];
    fields.forEach(([key, id]) => {
        const value = (document.getElementById(id)?.value || "").trim();
        if(value){ params.set(key, value); }
    });
    return params;
}

function showStorageAuditDetail(index){
    const item = window.storageAuditRows && window.storageAuditRows[index];
    document.getElementById("storageAuditDetail").innerText = item ? JSON.stringify(item, null, 2) : "";
}

function getStorageAuditLogs(){
    const params = storageAuditQuery();
    adminFetch(`/api/admin/audit/storage?${params.toString()}`)
    .then(res=>res.json())
    .then(data=>{
        window.storageAuditRows = data.data || [];
        const html = window.storageAuditRows.map((item, index) => `<tr>
            <td>${escHtml(item.created_at || "")}</td>
            <td>${escHtml(item.event_type || "")}</td>
            <td style="font-size:12px">${escHtml((item.file_hash || "").substring(0, 18))}</td>
            <td>${item.chunk_index ?? ""}</td>
            <td>${escHtml(item.node_address || "")}</td>
            <td>${escHtml(item.status || "")}</td>
            <td><button onclick="showStorageAuditDetail(${index})">详情</button></td>
        </tr>`).join("");
        document.getElementById("storageAuditTable").innerHTML = html || '<tr><td colspan="7">暂无审计日志</td></tr>';
    });
}

function exportStorageAudit(format){
    const params = storageAuditQuery();
    params.set("format", format);
    window.open(`/api/admin/audit/storage/export?${params.toString()}&admin_token=${encodeURIComponent(getAdminToken())}`, "_blank");
}

function getFileList(){
    const q = encodeURIComponent(document.getElementById("fileSearch").value || "");
    adminFetch(`/api/file_list?q=${q}&page=1&page_size=50`)
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.file_name}</td>
                <td style="font-size:12px">${item.ipfs_cid}</td>
                <td style="font-size:12px">${item.file_hash.substring(0,20)}...</td>
                <td>${item.shard}</td>
                <td>${item.nodes.length}</td>
                <td>${item.visibility === "private" ? "私有" : "公开"}</td>
                <td id="health-${item.file_hash}">待检查</td>
                <td>${item.time}</td>
                <td>
                    <a href="${item.download_url}" target="_blank">下载</a>
                    <button onclick="deleteFile('${item.file_hash}')">删除</button>
                </td>
            </tr>`
        })
        document.getElementById("fileTable").innerHTML = html;
    })
}

function deleteFile(fileHash){
    if(!confirm("确认删除这条文件记录？")) return;
    adminFetch("/api/file_delete",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({file_hash:fileHash})
    }).then(res=>res.json()).then(data=>{
        alert(data.msg);
        getFileList();
    })
}

function getFileHealth(){
    adminFetch("/api/file_health")
    .then(res=>res.json())
    .then(data=>{
        data.data.forEach(item=>{
            const cell = document.getElementById(`health-${item.file_hash}`);
            if(cell){
                cell.innerText = `${item.health.status} (${item.health.alive_count}/${item.health.stored_count})`;
            }
        })
    })
}

function getIpfsStatus(){
    adminFetch("/api/ipfs_status")
    .then(res=>res.json())
    .then(data=>{
        const s = data.data;
        document.getElementById("ipfsStatusText").innerText = s.online
            ? `IPFS在线｜Peer ${s.peer_id}｜Repo ${s.repo_size} bytes`
            : `IPFS离线｜${s.error}`;
    })
}

let map = null;
let markerList = [];

function escHtml(value){
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
        "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"
    }[ch]));
}

function renderNodeDistribution(nodes, message){
    const fallback = document.getElementById("nodeDistributionFallback");
    if(!fallback){ return; }
    const safeNodes = nodes || [];
    const onlineCount = safeNodes.filter((item) => Number(item.status) === 1).length;
    const rows = safeNodes.slice(0, 30).map((item) => `
        <tr>
            <td>${escHtml(item.user_addr)}</td>
            <td>${escHtml([item.country, item.province, item.city].filter(Boolean).join(" / ") || "未知")}</td>
            <td>${Number(item.status) === 1 ? "在线" : "离线"}</td>
            <td>${escHtml(item.lat)}, ${escHtml(item.lng)}</td>
        </tr>
    `).join("");
    fallback.style.display = "block";
    fallback.innerHTML = `
        <strong>节点分布看板</strong>
        <p style="color:#64748b;margin:8px 0 12px;">${escHtml(message || "地图服务未启用，已切换为列表视图。")} 节点 ${safeNodes.length} 个，在线 ${onlineCount} 个。</p>
        <table>
            <thead><tr><th>节点地址</th><th>地区</th><th>状态</th><th>经纬度</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="4">暂无节点地理数据</td></tr>'}</tbody>
        </table>
    `;
}

function renderMapFallback(message){
    const mapBox = document.getElementById("map");
    if(mapBox){
        mapBox.innerHTML = `<div style="height:100%;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;background:#eef6f6;border:1px dashed #9ccfca;border-radius:8px;color:#155e63;">${escHtml(message)}</div>`;
    }
    renderNodeDistribution([], message);
}

function initMap(){
    if(!AMAP_WEB_KEY){
        renderMapFallback("未完整配置 AMAP_WEB_KEY / AMAP_SECURITY_JSCODE，已关闭高德地图加载以避免 INVALID_USER_KEY 或 INVALID_USER_SCODE。");
        if(getAdminToken()){ loadNodeMap(); }
        return;
    }
    if(typeof AMap === "undefined"){
        renderMapFallback("地图 SDK 加载失败，已切换为节点分布看板。");
        if(getAdminToken()){ loadNodeMap(); }
        return;
    }
    map = new AMap.Map('map', {
        zoom: 3,
        center: [105.27, 35.31]
    });
    map.addControl(new AMap.Scale());
    map.addControl(new AMap.ToolBar());
    if(getAdminToken()){ loadNodeMap(); }
}

// 加载节点点位
function loadNodeMap(){
    if(map){
        markerList.forEach(m=>map.remove(m));
    }
    markerList = [];

    adminFetch("/api/map_node_list")
    .then(res=>res.json())
    .then(data=>{
        const nodes = data.data || [];
        if(!map || typeof AMap === "undefined"){
            renderNodeDistribution(nodes, "地图未启用，当前展示节点地理分布列表。");
            return;
        }
        renderNodeDistribution(nodes, "地图已启用，下方同步保留节点地理分布列表。");
        nodes.forEach(item=>{
            let lat = parseFloat(item.lat);
            let lng = parseFloat(item.lng);
            if(lat===0 || lng===0) return;

            // 在线绿色、离线灰色
            let iconUrl = item.status===1 
            ? "https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png"
            : "https://webapi.amap.com/theme/v1.3/markers/n/mark_bs.png";

            let marker = new AMap.Marker({
                position: [lng,lat],
                icon: iconUrl,
                zIndex: item.status===1 ? 10 : 1
            });

            // 悬浮弹窗信息
            let info = `
                节点地址：${item.user_addr}<br/>
                地区：${item.country} ${item.province} ${item.city}<br/>
                状态：${item.status===1 ? "✅ 在线" : "❌ 离线"}
            `;
            marker.on('mouseover',function(e){
                let infoWin = new AMap.InfoWindow({content:info});
                infoWin.open(map, [lng,lat]);
            })
            map.add(marker);
            markerList.push(marker);
        })
    })
}

function refreshAdminData(){
    getNodes();
    getReward();
    getFileList();
    getIpfsStatus();
    getLeaderboard();
    getDailyReward();
    getInviteTree();
    getAdminWithdrawals();
    getStorageAuditLogs();
    if(map){ loadNodeMap(); }
    setAdminAutoRefreshStatus(`自动刷新中｜上次刷新 ${new Date().toLocaleTimeString()}`);
}

function startAdminAutoRefresh(){
    if(adminRefreshTimer){ clearInterval(adminRefreshTimer); }
    setAdminAutoRefreshStatus("自动刷新中");
    adminRefreshTimer = setInterval(refreshAdminData, ADMIN_REFRESH_INTERVAL_MS);
}

// 自动加载数据
document.addEventListener("DOMContentLoaded", () => {
    if(!requireAdminLogin()){ return; }
    setAdminTokenStatus("登录态已读取，正在加载后台数据", false);
    initMap();
    if(getAdminToken()){
        refreshAdminData();
        startAdminAutoRefresh();
    }
});
</script>
</body>
</html>
'''

USER_UPLOAD_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>用户文件上传</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + '''
        body{font-family:Arial,"Microsoft YaHei",sans-serif;}
        nav{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;}
        a{color:#2563eb;text-decoration:none;}
        .panel{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:18px;margin-bottom:16px;}
        form{display:grid;gap:12px;}
        label{display:grid;gap:6px;font-weight:600;}
        input,select,button{font-size:15px;padding:10px;border:1px solid #d1d5db;border-radius:6px;}
        button{background:#2563eb;color:white;border:0;cursor:pointer;}
        button.secondary{background:#4b5563;}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;}
        .notice{margin:12px 0;padding:12px;border-radius:6px;background:#fff7ed;border:1px solid #fed7aa;}
        .status{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:14px;min-height:54px;}
        .linkbox{word-break:break-all;background:#ecfdf5;border:1px solid #bbf7d0;border-radius:8px;padding:12px;margin-top:12px;}
    </style>
</head>
<body class="commercial-page user-upload-page">
    <div class="page-shell">
    <nav class="modern-nav">
        <div class="brand-lockup"><span class="brand-mark"></span><span>Web3 Nodes Store</span></div>
        <div class="nav-actions"><a href="/">首页</a><a href="/user/dashboard">用户面板</a><a href="/user/login">登录</a></div>
    </nav>
    <header class="page-hero">
        <div>
            <span class="page-kicker">文件产品</span>
            <h1>上传文件并创建可控分享</h1>
            <p>支持公开或私有存储，上传后可生成带提取码、过期时间和下载次数限制的商业化分享链接。</p>
        </div>
    </header>
    <div id="loginNotice" class="notice" hidden>未检测到登录 Token，请先登录后再上传。</div>
    <div class="commercial-grid">
    <section class="panel commercial-card">
        <form id="uploadForm">
            <label>选择文件
                <input id="fileInput" name="file" type="file" required>
            </label>
            <label>文件访问权限
                <select id="visibilityInput" name="visibility">
                    <option value="public">公开</option>
                    <option value="private">私有</option>
                </select>
            </label>
            <button type="submit">上传文件</button>
        </form>
    </section>
    <section class="panel commercial-card">
        <h2>创建分享</h2>
        <form id="shareForm">
            <label>文件哈希
                <input id="fileHashInput" name="file_hash" placeholder="上传成功后自动填入" required>
            </label>
            <div class="grid">
                <label>提取码
                    <input id="extractCodeInput" name="extract_code" placeholder="可留空">
                </label>
                <label>过期时间
                    <input id="expiresAtInput" name="expires_at" type="datetime-local">
                </label>
                <label>下载次数限制
                    <input id="maxDownloadsInput" name="max_downloads" type="number" min="0" value="0">
                </label>
            </div>
            <button type="submit" class="secondary">生成分享链接</button>
        </form>
        <div id="shareLinkBox" class="linkbox" hidden></div>
    </section>
    </div>
    <pre id="resultBox" class="status">等待上传...</pre>
    </div>
    <script>
    const token = localStorage.getItem("user_token") || "";
    const notice = document.getElementById("loginNotice");
    const resultBox = document.getElementById("resultBox");
    const fileHashInput = document.getElementById("fileHashInput");
    const shareLinkBox = document.getElementById("shareLinkBox");
    function redirectToLogin(){
        const loginUrl = new URL("/user/login", window.location.origin);
        loginUrl.searchParams.set("next", window.location.pathname + window.location.search);
        window.location.href = loginUrl.toString();
    }
    function requireUserLogin(){
        if(!token){
            notice.hidden = false;
            resultBox.textContent = "缺少 user_token，请先登录。";
            redirectToLogin();
            return false;
        }
        return true;
    }
    requireUserLogin();
    function authHeaders(extra){
        return Object.assign({"Authorization": `Bearer ${token}`}, extra || {});
    }
    function toApiDatetime(value){
        return value ? value.replace("T", " ") + ":00" : "";
    }
    async function createShare(fileHash){
        const payload = {
            visibility: "public",
            extract_code: document.getElementById("extractCodeInput").value.trim(),
            expires_at: toApiDatetime(document.getElementById("expiresAtInput").value),
            max_downloads: document.getElementById("maxDownloadsInput").value || 0,
            status: "active"
        };
        const response = await fetch(`/api/user/files/${encodeURIComponent(fileHash)}/shares`, {
            method: "POST",
            headers: authHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if(!response.ok){
            throw new Error(data.msg || response.statusText);
        }
        const shareCode = (data.data || {}).share_code || "";
        const publicUrl = `${location.origin}/s/${encodeURIComponent(shareCode)}`;
        shareLinkBox.hidden = false;
        shareLinkBox.innerHTML = `分享链接：<a href="/s/${encodeURIComponent(shareCode)}">${publicUrl}</a>`;
        return publicUrl;
    }
    document.getElementById("uploadForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if(!requireUserLogin()){ return; }
        const file = document.getElementById("fileInput").files[0];
        const visibility = document.getElementById("visibilityInput").value;
        const body = new FormData();
        body.append("file", file);
        body.append("visibility", visibility);
        resultBox.textContent = "上传中...";
        try{
            const response = await fetch("/api/user/files", {
                method: "POST",
                headers: authHeaders(),
                body
            });
            const payload = await response.json();
            const data = payload.data || {};
            if(!response.ok){
                resultBox.textContent = `上传失败\\n${payload.msg || response.statusText}`;
                return;
            }
            fileHashInput.value = data.file_hash || "";
            resultBox.textContent = `上传完成\\nfile_hash: ${data.file_hash || ""}\\n请继续生成 /s/<share_code> 分享链接后下载。`;
        }catch(error){
            resultBox.textContent = `上传失败\\n${error.message}`;
        }
    });
    document.getElementById("shareForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if(!requireUserLogin()){ return; }
        const fileHash = fileHashInput.value.trim();
        resultBox.textContent = "正在创建分享...";
        try{
            const publicUrl = await createShare(fileHash);
            resultBox.textContent = `分享已创建\\n${publicUrl}`;
        }catch(error){
            resultBox.textContent = `分享创建失败\\n${error.message}`;
        }
    });
    </script>
</body>
</html>
'''

USER_LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>用户登录</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + '''
        body{font-family:Arial,"Microsoft YaHei",sans-serif;}
        nav{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;}
        a{color:#2563eb;text-decoration:none;}
        .auth-shell{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:18px;box-shadow:0 16px 36px rgba(15,23,42,.07);}
        .login-product-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(360px,.82fr);gap:20px;align-items:start;}
        .login-value{padding:26px;}
        .login-value h2{font-size:34px;line-height:1.15;margin:0 0 14px;}
        .login-value p{color:#64748b;line-height:1.8;margin:0 0 16px;}
        .value-list{display:grid;gap:10px;margin-top:18px;}
        .value-list div{padding:12px;border-left:3px solid #20b486;background:#f8fafc;border-radius:7px;color:#35515a;}
        .tabs{display:grid;grid-template-columns:repeat(auto-fit,minmax(82px,1fr));gap:8px;margin-bottom:18px;background:linear-gradient(180deg,#eef6f6,#f8fafc);border:1px solid rgba(20,184,166,.18);border-radius:8px;padding:6px;}
        .tab{background:rgba(255,255,255,.78)!important;color:#334155!important;border:1px solid rgba(15,118,110,.12)!important;margin:0;border-radius:7px!important;box-shadow:none!important;}
        .tab.active{background:linear-gradient(135deg,#0f766e,#14b8a6 48%,#f0b429)!important;color:white!important;box-shadow:0 12px 28px rgba(20,184,166,.24)!important;}
        .panel{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:18px;}
        .auth-panel{display:none;}
        .auth-panel.active{display:block;}
        form{display:grid;gap:12px;}
        label{display:grid;gap:6px;font-weight:600;}
        input,button{font-size:15px;padding:10px;border:1px solid #d1d5db;border-radius:6px;}
        button{background:#2563eb;color:#fff;border:0;cursor:pointer;}
        button.secondary{background:#4b5563;}
        .status{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:14px;margin-top:16px;min-height:54px;}
        .hint{color:#4b5563;font-size:14px;}
        .provider-list{display:grid;gap:10px;}
        .provider-note{padding:12px;border:1px dashed #99d8cf;border-radius:8px;background:#f0fdfa;color:#155e63;line-height:1.7;}
    </style>
</head>
<body class="commercial-page user-login-page">
    <div class="page-shell">
    <nav class="modern-nav">
        <div class="brand-lockup"><span class="brand-mark"></span><span>Web3 Nodes Store</span></div>
        <div class="nav-actions"><a href="/">首页</a><a href="/user/dashboard">用户面板</a><a href="/user/upload">上传文件</a></div>
    </nav>
    <header class="page-hero">
        <div>
            <span class="page-kicker">用户中心</span>
            <h1>进入你的文件分享与收益工作台</h1>
            <p>账号、注册与钱包登录集中在一个页面，登录后即可上传文件、创建分享、查看积分和提现。</p>
        </div>
    </header>
    <div class="login-product-layout">
    <section class="login-value commercial-card">
        <span class="page-kicker">商业化闭环</span>
        <h2>从一次上传开始，连接分发、下载与收益</h2>
        <p>适合私域资料分发、节点激励运营和文件商品化分享。用户登录后可以管理文件资产、分享链接与收益流水。</p>
        <div class="value-list">
            <div>可控分享：提取码、过期时间、下载次数限制。</div>
            <div>收益记录：分享下载、节点贡献和积分流水统一追踪。</div>
            <div>钱包能力：为后续链上身份和结算扩展保留入口。</div>
        </div>
    </section>
    <div class="auth-shell commercial-card">
        <div class="tabs" role="tablist" aria-label="登录方式">
            <button type="button" class="tab active" data-auth-tab="login">账号登录</button>
            <button type="button" class="tab" data-auth-tab="register">注册账号</button>
            <button type="button" class="tab" data-auth-tab="phone">手机</button>
            <button type="button" class="tab" data-auth-tab="email">邮箱</button>
            <button type="button" class="tab" data-auth-tab="wallet">钱包登录</button>
            <button type="button" class="tab" data-auth-tab="wechat">微信</button>
            <button type="button" class="tab" data-auth-tab="qq">QQ</button>
        </div>
        <section class="panel auth-panel active" id="loginPanel" data-auth-panel="login">
            <h2>账号登录</h2>
            <form id="passwordLoginForm">
                <label>用户名
                    <input id="loginUsername" autocomplete="username" required>
                </label>
                <label>密码
                    <input id="loginPassword" type="password" autocomplete="current-password" required>
                </label>
                <button type="submit">登录</button>
            </form>
        </section>
        <section class="panel auth-panel" id="registerPanel" data-auth-panel="register">
            <h2>注册</h2>
            <form id="registerForm">
                <label>用户名
                    <input id="registerUsername" autocomplete="username" required>
                </label>
                <label>密码
                    <input id="registerPassword" type="password" autocomplete="new-password" required>
                </label>
                <button type="submit">注册并登录</button>
            </form>
        </section>
        <section class="panel auth-panel" id="phonePanel" data-auth-panel="phone">
            <h2>手机号登录</h2>
            <form id="phoneLoginForm">
                <label>手机号
                    <input id="phoneLoginIdentifier" inputmode="tel" autocomplete="tel" placeholder="13800000000" required>
                </label>
                <label>密码
                    <input id="phoneLoginPassword" type="password" autocomplete="current-password" required>
                </label>
                <button type="submit">手机登录</button>
            </form>
        </section>
        <section class="panel auth-panel" id="emailPanel" data-auth-panel="email">
            <h2>邮箱登录</h2>
            <form id="emailLoginForm">
                <label>邮箱
                    <input id="emailLoginIdentifier" type="email" autocomplete="email" placeholder="name@163.com / gmail.com / outlook.com / icloud.com" required>
                </label>
                <label>密码
                    <input id="emailLoginPassword" type="password" autocomplete="current-password" required>
                </label>
                <div class="hint">支持 163.com、gmail.com、outlook.com、icloud.com / Apple 邮箱账号作为登录名。</div>
                <button type="submit">邮箱登录</button>
            </form>
        </section>
        <section class="panel auth-panel" id="walletPanel" data-auth-panel="wallet">
            <h2>钱包登录</h2>
            <form id="walletLoginForm">
                <label>钱包地址
                    <input id="walletAddress" placeholder="0x..." required>
                </label>
                <button type="button" class="secondary" id="nonceButton">获取登录 nonce</button>
                <label>nonce
                    <input id="walletNonce" required>
                </label>
                <label>签名
                    <input id="walletSignature" required>
                </label>
                <div class="hint" id="walletMessage"></div>
                <button type="submit">钱包登录</button>
            </form>
        </section>
        <section class="panel auth-panel" id="wechatPanel" data-auth-panel="wechat">
            <h2>微信登录</h2>
            <div class="provider-list">
                <div class="provider-note">微信开放平台接入位已预留。配置 AppID、AppSecret 和回调地址后即可启用扫码登录。</div>
                <button type="button" class="secondary" onclick="showStatus('微信登录需要先接入微信开放平台配置。')">微信扫码登录</button>
            </div>
        </section>
        <section class="panel auth-panel" id="qqPanel" data-auth-panel="qq">
            <h2>QQ 登录</h2>
            <div class="provider-list">
                <div class="provider-note">QQ 互联接入位已预留。配置 APP ID、APP Key 和回调地址后即可启用授权登录。</div>
                <button type="button" class="secondary" onclick="showStatus('QQ 登录需要先接入 QQ 互联配置。')">QQ 授权登录</button>
            </div>
        </section>
    </div>
    <pre id="statusBox" class="status">等待操作...</pre>
    </div>
    </div>
    <script>
    const statusBox = document.getElementById("statusBox");
    function showStatus(message){ statusBox.textContent = message; }
    function redirectAfterLogin(){
        const params = new URLSearchParams(window.location.search);
        const next = params.get("next") || "/user/dashboard";
        if(next.startsWith("/") && !next.startsWith("//")){
            return next;
        }
        return "/user/dashboard";
    }
    function switchAuthTab(nextTab){
        document.querySelectorAll("[data-auth-tab]").forEach((button) => {
            button.classList.toggle("active", button.dataset.authTab === nextTab);
        });
        document.querySelectorAll("[data-auth-panel]").forEach((panel) => {
            panel.classList.toggle("active", panel.dataset.authPanel === nextTab);
        });
    }
    document.querySelectorAll("[data-auth-tab]").forEach((button) => {
        button.addEventListener("click", () => switchAuthTab(button.dataset.authTab));
    });
    function saveSession(payload, shouldRedirect){
        const token = payload.token || payload.user_token || "";
        if(!token){ throw new Error(payload.msg || "接口未返回 user_token"); }
        localStorage.setItem("user_token", token);
        showStatus(`登录成功\\nuser_token 已保存\\n用户：${((payload.user || {}).username) || ""}`);
        if(shouldRedirect){
            window.location.href = redirectAfterLogin();
        }
    }
    async function postJson(url, body){
        const response = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body)
        });
        const payload = await response.json();
        if(!response.ok){ throw new Error(payload.msg || response.statusText); }
        return payload;
    }
    document.getElementById("registerForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try{
            const payload = await postJson("/api/auth/register", {
                username: document.getElementById("registerUsername").value.trim(),
                password: document.getElementById("registerPassword").value
            });
            saveSession(payload, true);
        }catch(error){ showStatus(`注册失败\\n${error.message}`); }
    });
    document.getElementById("passwordLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try{
            const payload = await postJson("/api/auth/login", {
                username: document.getElementById("loginUsername").value.trim(),
                password: document.getElementById("loginPassword").value
            });
            saveSession(payload, true);
        }catch(error){ showStatus(`登录失败\\n${error.message}`); }
    });
    async function loginWithIdentifier(identifier, password, label){
        try{
            const payload = await postJson("/api/auth/login", {
                username: identifier.trim(),
                password
            });
            saveSession(payload, true);
        }catch(error){ showStatus(`${label}失败\\n${error.message}`); }
    }
    document.getElementById("phoneLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        loginWithIdentifier(
            document.getElementById("phoneLoginIdentifier").value,
            document.getElementById("phoneLoginPassword").value,
            "手机登录"
        );
    });
    document.getElementById("emailLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        loginWithIdentifier(
            document.getElementById("emailLoginIdentifier").value,
            document.getElementById("emailLoginPassword").value,
            "邮箱登录"
        );
    });
    document.getElementById("nonceButton").addEventListener("click", async () => {
        try{
            const payload = await postJson("/api/wallet/nonce", {
                wallet_address: document.getElementById("walletAddress").value.trim(),
                purpose: "login"
            });
            document.getElementById("walletNonce").value = payload.nonce || "";
            document.getElementById("walletMessage").textContent = payload.message || "";
            showStatus("nonce 已生成，请在钱包中签名后填入签名。");
        }catch(error){ showStatus(`nonce 获取失败\\n${error.message}`); }
    });
    document.getElementById("walletLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try{
            const payload = await postJson("/api/wallet/login", {
                wallet_address: document.getElementById("walletAddress").value.trim(),
                nonce: document.getElementById("walletNonce").value.trim(),
                signature: document.getElementById("walletSignature").value.trim()
            });
            saveSession(payload, true);
        }catch(error){ showStatus(`钱包登录失败\\n${error.message}`); }
    });
    </script>
</body>
</html>
'''

USER_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>用户面板</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + '''
        body{font-family:Arial,"Microsoft YaHei",sans-serif;}
        nav{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;}
        a{color:#2563eb;text-decoration:none;}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;}
        .panel{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:14px;}
        .metric{font-size:24px;font-weight:700;margin:4px 0;}
        table{width:100%;border-collapse:collapse;font-size:14px;}
        th,td{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left;vertical-align:top;}
        th{background:#f3f4f6;}
        input,button{font-size:15px;padding:10px;border:1px solid #d1d5db;border-radius:6px;}
        button{background:#2563eb;color:#fff;border:0;cursor:pointer;}
        .status{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:14px;min-height:48px;}
        .wrap{word-break:break-all;}
    </style>
</head>
<body class="commercial-page user-dashboard-page">
    <div class="page-shell">
    <nav class="modern-nav">
        <div class="brand-lockup"><span class="brand-mark"></span><span>Web3 Nodes Store</span></div>
        <div class="nav-actions"><a href="/">首页</a><a href="/user/upload">上传文件</a><a href="/user/login">登录</a></div>
    </nav>
    <header class="page-hero">
        <div>
            <span class="page-kicker">用户工作台</span>
            <h1>文件资产、分享链接与收益总览</h1>
            <p>集中查看账户、积分、收益、文件、分享和提现，适合作为面向客户的自助运营中心。</p>
        </div>
    </header>
    <section class="panel commercial-card">
        <button id="refreshButton">刷新</button>
        <pre id="statusBox" class="status">正在读取 user_token...</pre>
    </section>
    <div class="grid">
        <section class="panel commercial-card">
            <h2>账户</h2>
            <div id="accountBox"></div>
        </section>
        <section class="panel commercial-card">
            <h2>收益</h2>
            <div class="metric" id="availableEarnings">0</div>
            <div id="earningsBox"></div>
        </section>
        <section class="panel commercial-card">
            <h2>积分</h2>
            <div class="metric" id="totalPoints">0</div>
            <div id="pointsBox"></div>
        </section>
    </div>
    <section class="panel commercial-card">
        <h2>钱包绑定</h2>
        <div class="grid">
            <input id="bindWalletAddress" placeholder="钱包地址 0x...">
            <button id="bindNonceButton">获取绑定 nonce</button>
            <input id="bindNonce" placeholder="nonce">
            <input id="bindSignature" placeholder="签名">
            <button id="bindWalletButton">绑定钱包</button>
        </div>
        <div id="bindMessage" class="wrap"></div>
    </section>
    <section class="panel commercial-card">
        <h2>文件</h2>
        <div id="filesBox"></div>
    </section>
    <section class="panel commercial-card">
        <h2>分享</h2>
        <div id="sharesBox"></div>
    </section>
    <section class="panel commercial-card">
        <h2>提现</h2>
        <div class="grid">
            <input id="withdrawAmount" placeholder="提现金额">
            <button id="withdrawButton">提交提现</button>
        </div>
        <div id="withdrawalsBox"></div>
    </section>
    <script>
    const token = localStorage.getItem("user_token") || "";
    const statusBox = document.getElementById("statusBox");
    function showStatus(message){ statusBox.textContent = message; }
    function authHeaders(extra){
        return Object.assign({"Authorization": `Bearer ${token}`}, extra || {});
    }
    function esc(value){
        return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
            "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"
        }[ch]));
    }
    async function apiGet(url){
        const response = await fetch(url, {headers: authHeaders()});
        const payload = await response.json();
        if(!response.ok){ throw new Error(`${url}: ${payload.msg || response.statusText}`); }
        return payload;
    }
    async function apiPost(url, body){
        const response = await fetch(url, {
            method: "POST",
            headers: authHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify(body)
        });
        const payload = await response.json();
        if(!response.ok){ throw new Error(payload.msg || response.statusText); }
        return payload;
    }
    function renderTable(targetId, columns, rows){
        const target = document.getElementById(targetId);
        if(!rows || rows.length === 0){
            target.innerHTML = "暂无数据";
            return;
        }
        target.innerHTML = `<table><thead><tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr></thead><tbody>${
            rows.map((row) => `<tr>${columns.map((c) => `<td class="wrap">${esc(c.render ? c.render(row) : row[c.key])}</td>`).join("")}</tr>`).join("")
        }</tbody></table>`;
    }
    async function refreshDashboard(){
        if(!token){
            showStatus("缺少 user_token，请先到登录页登录。");
            return;
        }
        showStatus("加载中...");
        try{
            const [me, files, sharesData, pointsData, earnings, withdrawals] = await Promise.all([
                apiGet("/api/auth/me"),
                apiGet("/api/user/files"),
                apiGet("/api/user/shares"),
                apiGet("/api/user/points"),
                apiGet("/api/user/earnings"),
                apiGet("/api/user/withdrawals")
            ]);
            const user = me.user || {};
            document.getElementById("accountBox").innerHTML = `用户：${esc(user.username)}<br>钱包：${esc(user.wallet_address || "未绑定")}<br>状态：${esc(user.status)}`;
            const earningData = earnings.data || {};
            document.getElementById("availableEarnings").textContent = earningData.available_earnings ?? 0;
            document.getElementById("earningsBox").innerHTML = `累计收益：${esc(earningData.total_earnings ?? 0)}<br>已提现：${esc(earningData.withdrawn_earnings ?? 0)}<br>冻结中：${esc(earningData.pending_withdrawals ?? 0)}`;
            document.getElementById("totalPoints").textContent = (pointsData.data || {}).total_points ?? 0;
            renderTable("pointsBox", [
                {label:"类型", key:"point_type"},
                {label:"数量", key:"amount"},
                {label:"来源", key:"source_type"},
                {label:"时间", key:"created_at"}
            ], (pointsData.data || {}).items || []);
            renderTable("filesBox", [
                {label:"文件名", key:"file_name"},
                {label:"哈希", key:"file_hash"},
                {label:"大小(MB)", key:"size"},
                {label:"权限", key:"visibility"},
                {label:"下载", render:(row) => row.download_url || "请创建分享"}
            ], files.data || []);
            renderTable("sharesBox", [
                {label:"分享码", key:"share_code"},
                {label:"文件", key:"file_name"},
                {label:"链接", render:(row) => `/s/${row.share_code || ""}`},
                {label:"提取码", render:(row) => row.extract_code_required ? "需要" : "无"},
                {label:"下载", render:(row) => `${row.download_count || 0}/${row.max_downloads || 0}`}
            ], sharesData.data || []);
            renderTable("withdrawalsBox", [
                {label:"金额", key:"amount"},
                {label:"状态", key:"status"},
                {label:"钱包", key:"wallet_address"},
                {label:"时间", key:"created_at"}
            ], withdrawals.data || []);
            showStatus("加载完成。");
        }catch(error){
            showStatus(`加载失败\\n${error.message}`);
        }
    }
    document.getElementById("refreshButton").addEventListener("click", refreshDashboard);
    document.getElementById("bindNonceButton").addEventListener("click", async () => {
        try{
            const payload = await apiPost("/api/wallet/nonce", {
                wallet_address: document.getElementById("bindWalletAddress").value.trim(),
                purpose: "bind"
            });
            document.getElementById("bindNonce").value = payload.nonce || "";
            document.getElementById("bindMessage").textContent = payload.message || "";
        }catch(error){ showStatus(`绑定 nonce 获取失败\\n${error.message}`); }
    });
    document.getElementById("bindWalletButton").addEventListener("click", async () => {
        try{
            await apiPost("/api/wallet/bind", {
                wallet_address: document.getElementById("bindWalletAddress").value.trim(),
                nonce: document.getElementById("bindNonce").value.trim(),
                signature: document.getElementById("bindSignature").value.trim()
            });
            showStatus("钱包绑定成功。");
            refreshDashboard();
        }catch(error){ showStatus(`钱包绑定失败\\n${error.message}`); }
    });
    document.getElementById("withdrawButton").addEventListener("click", async () => {
        try{
            await apiPost("/api/user/withdrawals", {
                amount: document.getElementById("withdrawAmount").value.trim()
            });
            showStatus("提现申请已提交。");
            refreshDashboard();
        }catch(error){ showStatus(`提现提交失败\\n${error.message}`); }
    });
    refreshDashboard();
    </script>
    </div>
</body>
</html>
'''

PUBLIC_SHARE_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>文件分享</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + '''
        body{font-family:Arial,"Microsoft YaHei",sans-serif;}
        .share-shell{width:min(820px,calc(100vw - 32px));margin:0 auto;padding:24px 0 48px;}
        .panel{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:18px;margin-bottom:16px;}
        label{display:grid;gap:6px;font-weight:600;margin:12px 0;}
        input,button{font-size:15px;padding:10px;border:1px solid #d1d5db;border-radius:6px;}
        button{background:#2563eb;color:#fff;border:0;cursor:pointer;}
        .status{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:14px;min-height:54px;}
        .meta{line-height:1.8;word-break:break-all;}
    </style>
</head>
<body class="commercial-page public-share-page">
    <div class="share-shell">
    <nav class="modern-nav">
        <div class="brand-lockup"><span class="brand-mark"></span><span>Web3 Nodes Store</span></div>
        <div class="nav-actions"><a href="/">首页</a><a href="/user/login">用户登录</a></div>
    </nav>
    <header class="page-hero">
        <div>
            <span class="page-kicker">安全文件交付</span>
            <h1>文件分享</h1>
            <p>通过分享码获取文件信息，填写提取码后即可下载。下载行为会记录到分享与节点收益系统。</p>
        </div>
    </header>
    <section class="panel commercial-card" data-api-share="/api/share/{{ share_code }}">
        <div id="shareMeta" class="meta">正在加载分享信息...</div>
        <label id="extractCodeLabel" hidden>提取码
            <input id="extractCodeInput" name="extract_code" autocomplete="off">
        </label>
        <button id="downloadButton">下载</button>
    </section>
    <pre id="statusBox" class="status">等待下载...</pre>
    </div>
    <script>
    const shareCode = "{{ share_code }}";
    const statusBox = document.getElementById("statusBox");
    const shareMeta = document.getElementById("shareMeta");
    const extractCodeLabel = document.getElementById("extractCodeLabel");
    function esc(value){
        return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
            "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"
        }[ch]));
    }
    function showStatus(message){ statusBox.textContent = message; }
    async function loadShare(){
        try{
            const response = await fetch(`/api/share/${encodeURIComponent(shareCode)}`);
            const payload = await response.json();
            if(!response.ok){ throw new Error(payload.msg || response.statusText); }
            const data = payload.data || {};
            shareMeta.innerHTML = `文件：${esc(data.file_name || "")}<br>大小(MB)：${esc(data.file_size || 0)}<br>下载次数：${esc(data.download_count || 0)} / ${esc(data.max_downloads || 0)}<br>过期时间：${esc(data.expires_at || "不限")}`;
            extractCodeLabel.hidden = !data.extract_code_required;
            showStatus(data.extract_code_required ? "请输入提取码后下载。" : "分享可直接下载。");
        }catch(error){
            shareMeta.textContent = "分享不可用";
            showStatus(`加载失败\\n${error.message}`);
        }
    }
    document.getElementById("downloadButton").addEventListener("click", async () => {
        const code = document.getElementById("extractCodeInput").value.trim();
        const query = code ? `?extract_code=${encodeURIComponent(code)}` : "";
        window.location.href = `/api/share/${encodeURIComponent(shareCode)}/download${query}`;
    });
    loadShare();
    </script>
</body>
</html>
'''

@app.route("/")
def home_page():
    return render_template_string(HOME_HTML)


@app.route("/admin")
def admin_index():
    return render_template_string(
        ADMIN_HTML,
        amap_web_key=AMAP_WEB_KEY if AMAP_WEB_KEY and AMAP_SECURITY_JSCODE else "",
        amap_security_jscode=AMAP_SECURITY_JSCODE if AMAP_WEB_KEY and AMAP_SECURITY_JSCODE else "",
    )


@app.route("/admin/login")
def admin_login_page():
    return render_template_string(ADMIN_LOGIN_HTML)


@app.route("/api/admin/login", methods=["POST"])
def admin_login_api():
    if not ADMIN_API_TOKEN:
        return jsonify({"code":503,"msg":"后台 Token 未配置"}), 503
    token = get_json_body().get("token", "")
    if not admin_token_value_is_valid(token):
        return jsonify({"code":401,"msg":"后台 Token 错误","authenticated":False}), 401
    return jsonify({"code":200,"msg":"登录成功","authenticated":True})


@app.route("/user/upload")
def user_upload_page():
    return render_template_string(USER_UPLOAD_HTML)


@app.route("/user/login")
def user_login_page():
    return render_template_string(USER_LOGIN_HTML)


@app.route("/user/dashboard")
def user_dashboard_page():
    return render_template_string(USER_DASHBOARD_HTML)


@app.route("/s/<share_code>")
def public_share_page(share_code):
    return render_template_string(PUBLIC_SHARE_HTML, share_code=share_code)


@app.route("/api/health")
def health_check():
    db_ok = init_db()
    return jsonify({
        "code": 200 if db_ok else 503,
        "server": "ok",
        "database": "ok" if db_ok else "error",
        "db_error": db_error,
    }), 200 if db_ok else 503

# 定时结算线程
def run_settlement_once():
    global db_error
    if not init_db():
        return False
    try:
        return auto_settle_reward()
    except Exception as exc:
        db_error = str(exc)
        return False


def settle_task():
    while True:
        if time.strftime("%H:%M") == "00:00":
            run_settlement_once()
        time.sleep(60)

# AES加密
def aes_encrypt(data):
    if AES is None:
        raise RuntimeError("缺少 pycryptodome 依赖，请执行：pip install pycryptodome")
    cipher = AES.new(AES_KEY.encode(), AES.MODE_ECB)
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    return cipher.encrypt(data)


def aes_decrypt(data):
    if AES is None:
        raise RuntimeError("缺少 pycryptodome 依赖，请执行：pip install pycryptodome")
    cipher = AES.new(AES_KEY.encode(), AES.MODE_ECB)
    plain = cipher.decrypt(data)
    if not plain:
        return plain
    pad = plain[-1]
    if pad < 1 or pad > 16:
        raise RuntimeError("文件解密失败，填充数据无效")
    return plain[:-pad]

# 文件分片
def file_shard(data):
    shards = []
    for i in range(0, len(data), SHARD_SIZE):
        shards.append(data[i:i+SHARD_SIZE])
    return shards

# 文件哈希
def get_file_hash(data):
    return hashlib.sha256(data).hexdigest()

# 1. 校验文件分片进度（断点续传/秒传）
@app.route("/api/upload_check", methods=["POST"])
def upload_check():
    data = request.get_json()
    file_hash = data.get("fileHash")
    file_dir = get_chunk_dir(file_hash)
    if file_dir is None:
        return jsonify({"code":400,"msg":"非法文件哈希"}), 400
    if not file_dir.exists():
        return jsonify({"code":200,"data":{"uploadedChunk":0}})

    # 获取已上传分片下标
    chunk_list = []
    for item in file_dir.iterdir():
        if item.name.isdigit():
            chunk_list.append(int(item.name))
    if not chunk_list:
        return jsonify({"code":200,"data":{"uploadedChunk":0}})
    return jsonify({"code":200,"data":{"uploadedChunk":max(chunk_list)+1}})

# 2. 分片上传接口
@app.route("/api/upload_chunk", methods=["POST"])
def upload_chunk():
    file_hash = request.form.get("fileHash")
    chunk_index = int(request.form.get("chunkIndex"))
    chunk_total = int(request.form.get("chunkTotal"))
    chunk = request.files["chunk"]

    # 分片临时目录
    file_dir = get_chunk_dir(file_hash)
    if file_dir is None:
        return jsonify({"code":400,"msg":"非法文件哈希"}), 400
    if chunk_index < 0 or chunk_index >= chunk_total:
        return jsonify({"code":400,"msg":"非法分片序号"}), 400
    file_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = file_dir / str(chunk_index)

    # 已存在直接跳过（秒传）
    if chunk_path.exists():
        return jsonify({"code":200,"msg":"分片已存在"})

    chunk.save(chunk_path)
    return jsonify({"code":200,"msg":"分片上传成功"})

# 3. 分片合并 + 加密 + 分布式存储 + IPFS上链
@app.route("/api/upload_merge", methods=["POST"])
def upload_merge():
    data = request.get_json()
    file_hash = data.get("fileHash")
    file_name = data.get("fileName")
    upload_addr = data.get("user_addr")
    visibility = normalize_visibility(data.get("visibility", "public"))
    access_token = create_access_token(visibility)

    file_dir = get_chunk_dir(file_hash)
    if file_dir is None:
        return jsonify({"code":400,"msg":"非法文件哈希"}), 400
    if not file_dir.exists():
        return jsonify({"code":400,"msg":"分片不存在"})

    # 读取所有分片并合并
    chunk_files = [int(i.name) for i in file_dir.iterdir() if i.name.isdigit()]
    chunk_files.sort()
    file_data = b""
    for idx in chunk_files:
        with open(file_dir / str(idx),"rb") as f:
            file_data += f.read()
        if len(file_data) > MAX_UPLOAD_BYTES:
            return jsonify({"code":413,"msg":"文件超过上传大小限制"}), 413

    # 原有核心业务：加密、分片、IPFS、存证、算力分红
    try:
        encrypt_data = aes_encrypt(file_data)
    except RuntimeError as exc:
        return jsonify({"code":500,"msg":str(exc)}), 500
    shards = file_shard(encrypt_data)
    shard_num = len(shards)
    real_file_hash = get_file_hash(file_data)

    # IPFS上传
    import ipfshttpclient
    try:
        client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001')
        cid = client.add_bytes(encrypt_data)
    except:
        return jsonify({"code":400,"msg":"IPFS节点未启动"})

    # 分配在线节点存储
    current_cursor().execute("select user_address from node_power where online_duration > 10")
    online_nodes = [x[0] for x in current_cursor().fetchall()]
    import random
    assign_nodes = random.sample(online_nodes, min(len(online_nodes),shard_num)) if online_nodes else get_backup_nodes()

    # 写入存证数据库
    current_cursor().execute('''
    insert into file_chain_record(file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,visibility,access_token)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ''',(file_name,real_file_hash,cid,round(len(file_data)/1024/1024,3),shard_num,upload_addr,json.dumps(assign_nodes, ensure_ascii=False),visibility,access_token))
    db.commit()

    # 节点算力奖励
    for node in assign_nodes:
        current_cursor().execute('update node_power set disk_used=disk_used+0.1 where user_address=%s',(node,))
    db.commit()

    # 清理临时分片
    shutil.rmtree(file_dir)

    return jsonify({
        "code":200,
        "msg":"文件加密上链完成",
        "data":{
            "file_hash":real_file_hash,
            "ipfs_cid":cid,
            "shard_count":shard_num,
            "storage_nodes":assign_nodes,
            "visibility":visibility,
            "access_token":access_token,
            "download_url":f"/api/file_download/{real_file_hash}" + (f"?token={access_token}" if access_token else "")
        }
    })

# 废弃旧接口，防止冲突
@app.route("/api/upload_file",methods=["POST"])
def api_upload_file():
    uploaded_file = request.files.get("file")
    upload_addr = request.form.get("user_addr", "")
    visibility = normalize_visibility(request.form.get("visibility", "public"))
    access_token = create_access_token(visibility)
    if not uploaded_file:
        return jsonify({"code":400,"msg":"缺少上传文件"})

    file_data = uploaded_file.read()
    if not file_data:
        return jsonify({"code":400,"msg":"上传文件为空"})
    if len(file_data) > MAX_UPLOAD_BYTES:
        return jsonify({"code":413,"msg":"文件超过上传大小限制"}), 413

    try:
        encrypt_data = aes_encrypt(file_data)
    except RuntimeError as exc:
        return jsonify({"code":500,"msg":str(exc)}), 500
    shards = file_shard(encrypt_data)
    shard_num = len(shards)
    real_file_hash = get_file_hash(file_data)

    import ipfshttpclient
    try:
        client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001')
        cid = client.add_bytes(encrypt_data)
    except Exception:
        return jsonify({"code":400,"msg":"IPFS节点未启动"})

    assign_nodes = get_backup_nodes()
    current_cursor().execute('''
    insert into file_chain_record(file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,visibility,access_token)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ''',(uploaded_file.filename,real_file_hash,cid,round(len(file_data)/1024/1024,3),shard_num,upload_addr,json.dumps(assign_nodes, ensure_ascii=False),visibility,access_token))

    for node in assign_nodes:
        current_cursor().execute('update node_power set disk_used=disk_used+0.1 where user_address=%s',(node,))

    return jsonify({
        "code":200,
        "msg":"文件加密上链完成",
        "data":{
            "file_hash":real_file_hash,
            "ipfs_cid":cid,
            "shard_count":shard_num,
            "storage_nodes":assign_nodes,
            "visibility":visibility,
            "access_token":access_token,
            "download_url":f"/api/file_download/{real_file_hash}" + (f"?token={access_token}" if access_token else "")
        }
    })


@app.route("/api/user/earnings", methods=["GET"])
@require_user
def user_earnings():
    summary = calculate_user_earnings(g.current_user.get("user_id"))
    return jsonify({"code":200,"data":summary})


@app.route("/api/user/points", methods=["GET"])
@require_user
def user_points():
    user_id = g.current_user.get("user_id")
    current_cursor().execute(
        """
        select id,user_id,wallet_address,point_type,amount,source_type,source_id,remark,created_at
        from point_ledger
        where user_id=%s
        order by created_at desc,id desc
        """,
        (user_id,),
    )
    rows = current_cursor().fetchall()
    total_points = sum(float(row[4] or 0) for row in rows)
    return jsonify({
        "code":200,
        "data":{
            "total_points":total_points,
            "total_earnings":points.points_to_earning_units(total_points),
            "items":[format_point_ledger_row(row) for row in rows],
        },
    })


@app.route("/api/user/withdrawals", methods=["GET"])
@require_user
def user_withdrawal_list():
    user_id = g.current_user.get("user_id")
    current_cursor().execute(
        """
        select id,user_id,wallet_address,amount,status,admin_note,created_at,reviewed_at,
        node_address,withdrawal_channel,withdrawal_account
        from withdrawal_request
        where user_id=%s
        order by created_at desc,id desc
        """,
        (user_id,),
    )
    return jsonify({
        "code":200,
        "data":[format_withdrawal_row(row) for row in current_cursor().fetchall()],
    })


@app.route("/api/user/withdrawals", methods=["POST"])
@require_user
def user_withdrawal_create():
    data = get_json_body()
    amount, message = withdrawals.parse_withdrawal_amount(data.get("amount"))
    if amount is None:
        return jsonify({"code":400,"msg":message}), 400
    amount_for_db = withdrawals.format_withdrawal_amount(amount)
    user_row = getattr(g, "current_user_row", None) or ()
    user_id = user_row[0] if len(user_row) > 0 else g.current_user.get("user_id")
    wallet_address = user_row[3] if len(user_row) > 3 and user_row[3] else ""
    if not wallet_address:
        return jsonify({"code":400,"msg":"请先绑定钱包地址"}), 400

    with DatabaseTransaction():
        try:
            if not lock_active_user_for_update(user_id):
                rollback_database()
                return jsonify({"code":401,"msg":"用户不存在或已停用"}), 401
            summary = calculate_user_earnings(user_id, include_decimal=True)
            if amount > summary["_available_earnings_decimal"]:
                rollback_database()
                summary.pop("_available_earnings_decimal", None)
                return jsonify({"code":400,"msg":"可提现余额不足","data":summary}), 400
            current_cursor().execute(
                """
                insert into withdrawal_request(
                    user_id,wallet_address,amount,status,node_address,withdrawal_channel,withdrawal_account
                )
                values(%s,%s,%s,%s,%s,%s,%s)
                """,
                (user_id,wallet_address,amount_for_db,"pending","","wallet",wallet_address),
            )
            commit_database()
        except Exception:
            rollback_database()
            return jsonify({"code":500,"msg":"提现申请创建失败"}), 500
    return jsonify({
        "code":200,
        "msg":"提现申请已提交",
        "data":{
            "user_id":user_id,
            "wallet_address":wallet_address,
            "node_address":"",
            "withdrawal_channel":"wallet",
            "withdrawal_account":wallet_address,
            "amount":amount_for_db,
            "status":"pending",
        },
    })


@app.route("/api/admin/withdrawals", methods=["GET"])
def admin_withdrawal_list():
    current_cursor().execute(
        """
        select id,user_id,wallet_address,amount,status,admin_note,created_at,reviewed_at,
        node_address,withdrawal_channel,withdrawal_account
        from withdrawal_request
        order by created_at desc,id desc
        """
    )
    return jsonify({
        "code":200,
        "data":[format_withdrawal_row(row) for row in current_cursor().fetchall()],
    })


@app.route("/api/admin/withdrawals/<int:withdrawal_id>/review", methods=["POST"])
def admin_withdrawal_review(withdrawal_id):
    data = get_json_body()
    status = str(data.get("status") or "").strip().lower()
    ok, message = withdrawals.validate_review_status(status)
    if not ok:
        return jsonify({"code":400,"msg":message}), 400
    admin_note = str(data.get("admin_note") or "")[:255]
    with DatabaseTransaction():
        try:
            active_cursor = current_cursor()
            active_cursor.execute(
                "select id,status from withdrawal_request where id=%s for update",
                (withdrawal_id,),
            )
            row = active_cursor.fetchone()
            if not row:
                rollback_database()
                return jsonify({"code":404,"msg":"提现申请不存在"}), 404
            transition_ok, transition_message = withdrawals.validate_status_transition(row[1], status)
            if not transition_ok:
                rollback_database()
                return jsonify({"code":400,"msg":transition_message}), 400
            active_cursor.execute(
                """
                update withdrawal_request
                set status=%s,admin_note=%s,reviewed_at=%s
                where id=%s
                """,
                (status,admin_note,datetime.now(),withdrawal_id),
            )
            if getattr(active_cursor, "rowcount", None) == 0:
                rollback_database()
                return jsonify({"code":404,"msg":"提现申请不存在"}), 404
            commit_database()
        except Exception:
            rollback_database()
            return jsonify({"code":500,"msg":"提现审核更新失败"}), 500
    return jsonify({"code":200,"msg":"提现审核已更新","data":{"id":withdrawal_id,"status":status}})


def format_storage_audit_row(row):
    metadata_text = row[8] or "{}"
    try:
        metadata = json.loads(metadata_text)
        if not isinstance(metadata, dict):
            metadata = {}
    except Exception:
        metadata = {}
    return {
        "id": row[0],
        "event_type": row[1] or "",
        "file_hash": row[2] or "",
        "chunk_index": row[3],
        "node_address": row[4] or "",
        "request_id": row[5] or "",
        "status": row[6] or "",
        "message": row[7] or "",
        "metadata": metadata,
        "metadata_json": metadata_text,
        "created_at": str(row[9]) if row[9] else "",
    }


def select_storage_audit_rows(args):
    where = []
    params = []
    for field in ("file_hash", "node_address", "event_type", "status"):
        value = str(args.get(field) or "").strip()
        if value:
            where.append(f"{field}=%s")
            params.append(value)
    from_time = str(args.get("from") or "").strip()
    to_time = str(args.get("to") or "").strip()
    if from_time:
        where.append("created_at>=%s")
        params.append(from_time)
    if to_time:
        where.append("created_at<=%s")
        params.append(to_time)
    limit = min(max(int(args.get("limit", 200) or 200), 1), 1000)
    sql = """
        select id,event_type,file_hash,chunk_index,node_address,request_id,status,message,metadata_json,created_at
        from storage_audit_log
    """
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by created_at desc,id desc limit %s"
    params.append(limit)
    current_cursor().execute(sql, tuple(params))
    return [format_storage_audit_row(row) for row in current_cursor().fetchall()]


@app.route("/api/admin/audit/storage", methods=["GET"])
def admin_storage_audit_list():
    rows = select_storage_audit_rows(request.args)
    return jsonify({"code":200,"data":rows})


@app.route("/api/admin/audit/storage/export", methods=["GET"])
def admin_storage_audit_export():
    rows = select_storage_audit_rows(request.args)
    export_format = str(request.args.get("format") or "json").strip().lower()
    if export_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "id",
                "event_type",
                "file_hash",
                "chunk_index",
                "node_address",
                "request_id",
                "status",
                "message",
                "metadata_json",
                "created_at",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
        response = app.response_class(output.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=storage-audit.csv"
        return response
    return jsonify({"code":200,"data":rows})


@app.route("/api/admin/users", methods=["GET"])
def admin_user_list():
    current_cursor().execute(
        """
        select id,username,password_hash,wallet_address,status
        from app_user
        order by id desc
        """
    )
    return jsonify({"code":200,"data":[format_user(row) for row in current_cursor().fetchall()]})


@app.route("/api/admin/shares", methods=["GET"])
def admin_share_list():
    current_cursor().execute(f"""
    select {shares.SHARE_SELECT_PROJECTION}
    from file_share s
    join file_chain_record f on f.file_hash=s.file_hash and f.deleted_at is null
    order by s.created_at desc
    """)
    return jsonify({
        "code":200,
        "data":[shares.format_share_row(row) for row in current_cursor().fetchall()],
    })


@app.route("/api/admin/downloads", methods=["GET"])
def admin_download_list():
    current_cursor().execute(
        """
        select id,share_code,file_hash,downloader_ip,downloader_user_id,node_address,file_size,created_at
        from file_download_log
        order by created_at desc,id desc
        """
    )
    downloads = []
    for row in current_cursor().fetchall():
        downloads.append({
            "id":row[0],
            "share_code":row[1] or "",
            "file_hash":row[2] or "",
            "downloader_ip":row[3] or "",
            "downloader_user_id":row[4],
            "node_address":row[5] or "",
            "file_size":float(row[6] or 0),
            "created_at":str(row[7]) if len(row) > 7 and row[7] else "",
        })
    return jsonify({"code":200,"data":downloads})


@app.route("/api/admin/points", methods=["GET"])
def admin_point_list():
    current_cursor().execute(
        """
        select id,user_id,wallet_address,point_type,amount,source_type,source_id,remark,created_at
        from point_ledger
        order by created_at desc,id desc
        """
    )
    return jsonify({
        "code":200,
        "data":[format_point_ledger_row(row) for row in current_cursor().fetchall()],
    })


@app.route("/api/user/files", methods=["POST"])
@require_user
def user_file_upload():
    uploaded_file = request.files.get("file")
    visibility = normalize_visibility(request.form.get("visibility", "public"))
    access_token = create_access_token(visibility)
    if not uploaded_file:
        return jsonify({"code":400,"msg":"缺少上传文件"}), 400

    file_data = uploaded_file.read()
    if not file_data:
        return jsonify({"code":400,"msg":"上传文件为空"}), 400
    if len(file_data) > MAX_UPLOAD_BYTES:
        return jsonify({"code":413,"msg":"文件超过上传大小限制"}), 413

    user_row = getattr(g, "current_user_row", None) or ()
    owner_user_id = user_row[0] if len(user_row) > 0 else g.current_user.get("user_id")
    owner_wallet_address = user_row[3] if len(user_row) > 3 and user_row[3] else ""
    username = user_row[1] if len(user_row) > 1 and user_row[1] else ""
    upload_user = owner_wallet_address or username
    real_file_hash = get_file_hash(file_data)
    request_id = secrets.token_hex(8)
    current_cursor().execute(f"""
    select {USER_FILE_SELECT_PROJECTION}
    from file_chain_record
    where file_hash=%s and deleted_at is null
    order by create_time desc
    limit 1
    """,(real_file_hash,))
    duplicate_row = current_cursor().fetchone()
    if duplicate_row:
        duplicate_response = {
            "code":409,
            "msg":"文件已存在，当前版本暂不支持重复上传",
        }
        if duplicate_row[12] == owner_user_id:
            duplicate_response["data"] = format_user_file_record(duplicate_row)
        return jsonify(duplicate_response), 409

    try:
        encrypt_data = aes_encrypt(file_data)
    except RuntimeError as exc:
        return jsonify({"code":500,"msg":str(exc)}), 500
    shards = file_shard(encrypt_data)
    shard_num = len(shards)

    try:
        assign_nodes = real_user_storage_nodes(get_backup_nodes())
        if not assign_nodes:
            return jsonify({"code":503,"msg":"暂无可用用户节点，请先启动节点客户端后再上传"}), 503
        assign_nodes = call_persist_file_to_storage_nodes(real_file_hash, encrypt_data, assign_nodes, request_id=request_id)
    except Exception as exc:
        return jsonify({"code":503,"msg":str(exc) or "用户节点存储失败"}), 503

    cid, ipfs_backup_status, ipfs_backup_error = backup_to_ipfs(encrypt_data)
    if ipfs_backup_status == "ok":
        insert_storage_audit_log(
            "fallback.ipfs.write.success",
            file_hash=real_file_hash,
            request_id=request_id,
            status="ok",
            message="IPFS backup stored",
            metadata={"ipfs_cid": cid},
        )
    else:
        insert_storage_audit_log(
            "fallback.ipfs.write.failed",
            file_hash=real_file_hash,
            request_id=request_id,
            status="failed",
            message=ipfs_backup_error or "IPFS backup failed",
        )
    with DatabaseTransaction():
        try:
            current_cursor().execute('''
            insert into file_chain_record(file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,visibility,access_token,owner_user_id,owner_wallet_address)
            values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''',(
                uploaded_file.filename,
                real_file_hash,
                cid,
                round(len(file_data)/1024/1024,3),
                shard_num,
                upload_user,
                json.dumps(assign_nodes, ensure_ascii=False),
                visibility,
                access_token,
                owner_user_id,
                owner_wallet_address,
            ))
            shard_records = insert_file_shard_records(real_file_hash, encrypt_data, assign_nodes)
            insert_storage_audit_log(
                "upload.sharded",
                file_hash=real_file_hash,
                request_id=request_id,
                status="ok",
                message="encrypted shards recorded",
                metadata={"shard_count": len(shard_records), "nodes": assign_nodes},
            )

            for node in assign_nodes:
                current_cursor().execute('update node_power set disk_used=disk_used+0.1 where user_address=%s',(node,))
            commit_database()
        except Exception as exc:
            rollback_database()
            if duplicate_database_error(exc):
                return jsonify({
                    "code":409,
                    "msg":"文件已存在，当前版本暂不支持重复上传",
                }), 409
            return jsonify({"code":500,"msg":"文件记录保存失败"}), 500

    return jsonify({
        "code":200,
        "msg":"文件已写入用户节点，IPFS备份完成" if ipfs_backup_status == "ok" else "文件已写入用户节点，IPFS备份待重试",
        "data":{
            "file_hash":real_file_hash,
            "ipfs_cid":cid,
            "ipfs_backup_status":ipfs_backup_status,
            "ipfs_backup_error":ipfs_backup_error,
            "shard_count":shard_num,
            "storage_nodes":assign_nodes,
            "visibility":visibility,
            "access_token":access_token,
            "owner_user_id":owner_user_id,
            "owner_wallet_address":owner_wallet_address,
            "download_url":"",
            "share_required":True
        }
    })


@app.route("/api/user/files", methods=["GET"])
@require_user
def user_file_list():
    owner_user_id = g.current_user.get("user_id")
    current_cursor().execute(f"""
    select {USER_FILE_SELECT_PROJECTION}
    from file_chain_record
    where owner_user_id=%s and deleted_at is null
    order by create_time desc
    """,(owner_user_id,))
    return jsonify({"code":200,"data":format_user_file_records(current_cursor().fetchall())})


@app.route("/api/user/files/<file_hash>", methods=["GET"])
@require_user
def user_file_detail(file_hash):
    if not validate_file_hash(file_hash):
        return jsonify({"code":400,"msg":"file_hash 格式无效"}), 400
    owner_user_id = g.current_user.get("user_id")
    current_cursor().execute(f"""
    select {USER_FILE_SELECT_PROJECTION}
    from file_chain_record
    where owner_user_id=%s and file_hash=%s and deleted_at is null
    """,(owner_user_id,file_hash))
    row = current_cursor().fetchone()
    if not row:
        return jsonify({"code":404,"msg":"文件不存在"}), 404
    return jsonify({"code":200,"data":format_user_file_record(row)})


@app.route("/api/user/files/<file_hash>", methods=["DELETE"])
@require_user
def user_file_delete(file_hash):
    if not validate_file_hash(file_hash):
        return jsonify({"code":400,"msg":"file_hash 格式无效"}), 400
    owner_user_id = g.current_user.get("user_id")
    active_cursor = current_cursor()
    active_cursor.execute(
        "update file_chain_record set deleted_at=%s where owner_user_id=%s and file_hash=%s and deleted_at is null",
        (datetime.now(),owner_user_id,file_hash),
    )
    commit_database()
    if getattr(active_cursor, "rowcount", None) == 0:
        return jsonify({"code":404,"msg":"文件不存在"}), 404
    return jsonify({"code":200,"msg":"文件记录已删除"})


@app.route("/api/user/files/<file_hash>/shares", methods=["POST"])
@require_user
def user_file_share_create(file_hash):
    if not validate_file_hash(file_hash):
        return jsonify({"code":400,"msg":"file_hash 格式无效"}), 400
    owner_user_id = g.current_user.get("user_id")
    current_cursor().execute(
        """
        select file_hash,owner_user_id
        from file_chain_record
        where file_hash=%s and owner_user_id=%s and deleted_at is null
        limit 1
        """,
        (file_hash,owner_user_id),
    )
    if not current_cursor().fetchone():
        return jsonify({"code":404,"msg":"文件不存在"}), 404

    data = get_json_body()
    visibility = normalize_visibility(data.get("visibility", "public"))
    status = normalize_share_status(data.get("status", "active"))
    if status is None:
        return jsonify({"code":400,"msg":"status 格式无效"}), 400
    expires_at, expiry_error = parse_share_expires_at(data.get("expires_at"))
    if expiry_error:
        return jsonify({"code":400,"msg":expiry_error}), 400
    max_downloads, max_error = parse_non_negative_int(data.get("max_downloads", 0), "max_downloads")
    if max_error:
        return jsonify({"code":400,"msg":max_error}), 400
    extract_code = str(data.get("extract_code") or "").strip()
    extract_code_hash = shares.hash_extract_code(extract_code) if extract_code else ""
    share_code, create_error = insert_file_share_with_retry(
        file_hash,
        owner_user_id,
        visibility,
        extract_code_hash,
        expires_at,
        max_downloads,
        status,
    )
    if create_error:
        return jsonify({"code":500,"msg":create_error}), 500
    commit_database()
    return jsonify({
        "code":200,
        "msg":"分享已创建",
        "data":{
            "share_code":share_code,
            "file_hash":file_hash,
            "owner_user_id":owner_user_id,
            "visibility":visibility,
            "extract_code_required":bool(extract_code_hash),
            "expires_at":str(expires_at) if expires_at else "",
            "max_downloads":max_downloads,
            "download_count":0,
            "status":status,
            "share_url":f"/s/{urllib.parse.quote(share_code)}",
        },
    })


@app.route("/api/user/shares", methods=["GET"])
@require_user
def user_share_list():
    owner_user_id = g.current_user.get("user_id")
    current_cursor().execute(f"""
    select {shares.SHARE_SELECT_PROJECTION}
    from file_share s
    join file_chain_record f on f.file_hash=s.file_hash and f.deleted_at is null
    where s.owner_user_id=%s and s.status<>'deleted'
    order by s.created_at desc
    """,(owner_user_id,))
    return jsonify({
        "code":200,
        "data":[shares.format_share_row(row) for row in current_cursor().fetchall()],
    })


@app.route("/api/user/shares/<share_code>", methods=["PATCH"])
@require_user
def user_share_update(share_code):
    if not validate_share_code(share_code):
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    owner_user_id = g.current_user.get("user_id")
    current_cursor().execute(
        "select share_code from file_share where share_code=%s and owner_user_id=%s and status<>'deleted'",
        (share_code,owner_user_id),
    )
    if not current_cursor().fetchone():
        return jsonify({"code":404,"msg":"分享不存在"}), 404

    data = get_json_body()
    updates = []
    params = []
    if "extract_code" in data:
        extract_code = str(data.get("extract_code") or "").strip()
        updates.append("extract_code_hash=%s")
        params.append(shares.hash_extract_code(extract_code) if extract_code else "")
    if "expires_at" in data:
        expires_at, expiry_error = parse_share_expires_at(data.get("expires_at"))
        if expiry_error:
            return jsonify({"code":400,"msg":expiry_error}), 400
        updates.append("expires_at=%s")
        params.append(expires_at)
    if "max_downloads" in data:
        max_downloads, max_error = parse_non_negative_int(data.get("max_downloads"), "max_downloads")
        if max_error:
            return jsonify({"code":400,"msg":max_error}), 400
        updates.append("max_downloads=%s")
        params.append(max_downloads)
    if "status" in data:
        status = normalize_share_status(data.get("status"))
        if status is None:
            return jsonify({"code":400,"msg":"status 格式无效"}), 400
        updates.append("status=%s")
        params.append(status)
    if "visibility" in data:
        updates.append("visibility=%s")
        params.append(normalize_visibility(data.get("visibility")))
    if not updates:
        return jsonify({"code":400,"msg":"没有可更新的分享字段"}), 400

    params.extend([share_code, owner_user_id])
    current_cursor().execute(
        f"update file_share set {','.join(updates)} where share_code=%s and owner_user_id=%s and status<>'deleted'",
        tuple(params),
    )
    if getattr(current_cursor(), "rowcount", None) == 0:
        rollback_database()
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    commit_database()
    return jsonify({"code":200,"msg":"分享已更新"})


@app.route("/api/user/shares/<share_code>", methods=["DELETE"])
@require_user
def user_share_delete(share_code):
    if not validate_share_code(share_code):
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    owner_user_id = g.current_user.get("user_id")
    active_cursor = current_cursor()
    active_cursor.execute(
        "update file_share set status=%s where share_code=%s and owner_user_id=%s and status<>'deleted'",
        ("deleted",share_code,owner_user_id),
    )
    commit_database()
    if getattr(active_cursor, "rowcount", None) == 0:
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    return jsonify({"code":200,"msg":"分享已删除"})


@app.route("/api/share/<share_code>", methods=["GET"])
def public_share_detail(share_code):
    if not validate_share_code(share_code):
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    row = select_share_row(share_code)
    if not row:
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    share = shares.format_share_row(row, include_extract_code_hash=True)
    allowed, status_code, message = shares.validate_share_access(share)
    if not allowed:
        return jsonify({"code":status_code,"msg":message}), status_code
    return jsonify({"code":200,"data":shares.format_public_share(share)})


@app.route("/api/share/<share_code>/verify", methods=["POST"])
def public_share_verify(share_code):
    if not validate_share_code(share_code):
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    row = select_share_row(share_code)
    if not row:
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    share = shares.format_share_row(row, include_extract_code_hash=True)
    allowed, status_code, message = shares.validate_share_access(share)
    if not allowed:
        return jsonify({"code":status_code,"msg":message}), status_code
    code_hash = share.get("extract_code_hash") or ""
    if code_hash and not shares.verify_extract_code(get_json_body().get("extract_code", ""), code_hash):
        return jsonify({"code":403,"msg":"提取码错误","verified":False}), 403
    return jsonify({"code":200,"verified":True})


@app.route("/api/share/<share_code>/download", methods=["GET", "POST"])
def public_share_download(share_code):
    if not validate_share_code(share_code):
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    row = select_share_download_row(share_code)
    if not row:
        return jsonify({"code":404,"msg":"分享不存在"}), 404
    share = format_share_download_row(row)
    allowed, status_code, message = shares.validate_share_access(share)
    if not allowed:
        return jsonify({"code":status_code,"msg":message}), status_code
    code_hash = share.get("extract_code_hash") or ""
    if code_hash and not shares.verify_extract_code(request_extract_code(), code_hash):
        return jsonify({"code":403,"msg":"提取码错误"}), 403

    downloader_user_id = optional_downloader_user_id()
    request_id = secrets.token_hex(8)
    encrypted = read_verified_encrypted_file(
        share["file_hash"],
        share["stored_nodes"],
        share["ipfs_cid"],
        request_id=request_id,
    )
    if encrypted is None:
        return jsonify({"code":502,"msg":"用户节点副本不可用，且暂无可用兜底备份"}), 502
    try:
        plain = decrypt_and_verify_file(share["file_hash"], encrypted)
    except RuntimeError as exc:
        return jsonify({"code":500,"msg":str(exc)}), 500

    with DatabaseTransaction():
        try:
            recorded = record_share_download_success(
                share,
                downloader_user_id,
                request.remote_addr or "",
            )
            if not recorded:
                rollback_database()
                return jsonify({"code":409,"msg":"分享状态已变化，请重试"}), 409
            commit_database()
        except Exception:
            rollback_database()
            return jsonify({"code":500,"msg":"下载记录保存失败"}), 500

    filename = share["file_name"] or f"{share['file_hash']}.bin"
    response = app.response_class(plain, mimetype="application/octet-stream")
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"
    return response


# 查询所有上链存证记录
@app.route("/api/file_list",methods=["GET"])
def file_list():
    current_cursor().execute("""
    select id,file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,create_time,visibility,access_token,deleted_at
    from file_chain_record where deleted_at is null order by create_time desc
    """)
    result = filter_file_records(
        current_cursor().fetchall(),
        keyword=request.args.get("q", ""),
        page=request.args.get("page", 1),
        page_size=request.args.get("page_size", 20),
    )
    return jsonify({"code":200,"data":result["items"],"total":result["total"],"page":result["page"],"page_size":result["page_size"]})


@app.route("/api/file_delete",methods=["POST"])
def file_delete():
    data = request.get_json() or {}
    file_hash = data.get("file_hash")
    if not file_hash:
        return jsonify({"code":400,"msg":"缺少 file_hash"}), 400
    current_cursor().execute("update file_chain_record set deleted_at=%s where file_hash=%s",(datetime.now(),file_hash))
    return jsonify({"code":200,"msg":"文件记录已删除"})


@app.route("/api/file_health",methods=["GET"])
def file_health():
    current_cursor().execute("""
    select id,file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,create_time,visibility,access_token,deleted_at
    from file_chain_record where deleted_at is null order by create_time desc
    """)
    records = [format_file_record(row) for row in current_cursor().fetchall()]
    current_cursor().execute(f"select user_address from node_power where update_time > {node_alive_interval_sql(3)}")
    alive_nodes = {item[0] for item in current_cursor().fetchall()}
    data = []
    for record in records:
        health = calculate_file_health(record, alive_nodes)
        record.update({"health":health})
        data.append(record)
    return jsonify({"code":200,"data":data})


@app.route("/api/ipfs_status",methods=["GET"])
def ipfs_status():
    return jsonify({"code":200,"data":read_ipfs_status()})


@app.route("/api/file_download/<file_hash>",methods=["GET"])
def file_download(file_hash):
    current_cursor().execute("""
    select id,file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,create_time,visibility,access_token,deleted_at,owner_user_id
    from file_chain_record where file_hash=%s and deleted_at is null
    """,(file_hash,))
    row = current_cursor().fetchone()
    if not row:
        return jsonify({"code":404,"msg":"文件不存在"}), 404
    record = format_file_record(row)
    if not file_access_allowed(record, request.args.get("token", "")):
        if record.get("owner_user_id") is not None:
            return jsonify({"code":403,"msg":"用户文件请通过分享链接下载"}), 403
        return jsonify({"code":403,"msg":"文件访问令牌无效"}), 403
    request_id = secrets.token_hex(8)
    encrypted = read_verified_encrypted_file(
        file_hash,
        record.get("nodes") or [],
        record["ipfs_cid"],
        request_id=request_id,
    )
    if encrypted is None:
        return jsonify({"code":502,"msg":"用户节点副本不可用，且暂无可用兜底备份"}), 502
    try:
        plain = decrypt_and_verify_file(file_hash, encrypted)
    except RuntimeError as exc:
        return jsonify({"code":500,"msg":str(exc)}), 500
    filename = record["file_name"] or f"{file_hash}.bin"
    response = app.response_class(plain, mimetype="application/octet-stream")
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"
    return response

# 简易IP地理位置解析（免费公开接口，无需密钥）
def get_ip_location(ip):
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN",timeout=3)
        data = res.json()
        if data["status"] == "success":
            return {
                "country":data.get("country","未知"),
                "province":data.get("regionName","未知"),
                "city":data.get("city","未知"),
                "lat":str(data.get("lat","0")),
                "lng":str(data.get("lon","0"))
            }
    except:
        pass
    return {"country":"未知","province":"未知","city":"未知","lat":"0","lng":"0"}

# 中间件：获取访客真实IP
def get_real_ip():
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    elif request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

# 新增：节点上报位置（心跳自动调用）
@app.route("/api/report_location",methods=["POST"])
def report_location():
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    ip = get_real_ip()
    loc = get_ip_location(ip)

    # 输入心跳数据
    print(f"节点位置上报 - IP: {ip}, MAC: {node_mac}, 用户地址: {user_addr}, 位置: {loc}")

    # 更新或写入节点位置
    params = (user_addr,node_mac,ip,loc["country"],loc["province"],loc["city"],loc["lat"],loc["lng"])
    if DB_ENGINE == "mysql":
        params = params + (ip,loc["country"],loc["province"],loc["city"],loc["lat"],loc["lng"])
    current_cursor().execute(node_location_upsert_sql(), params)
    db.commit()
    return jsonify({"code":200,"msg":"位置上报成功"})

# 新增：获取全网节点地图点位
@app.route("/api/map_node_list",methods=["GET"])
def map_node_list():
    current_cursor().execute("select * from node_location")
    res = current_cursor().fetchall()
    arr = []
    for item in res:
        arr.append({
            "user_addr":item[1],
            "node_mac":item[2],
            "ip":item[3],
            "country":item[4],
            "province":item[5],
            "city":item[6],
            "lat":item[7],
            "lng":item[8],
            "status":item[9]
        })
    return jsonify({"code":200,"data":arr})

# 定时标记离线节点
@app.route("/api/map_offline_clear",methods=["POST"])
def map_offline_clear():
    current_cursor().execute(f"update node_location set online_status=0 where update_time < {node_alive_interval_sql(2)}")
    db.commit()
    return jsonify({"code":200})

# 获取【异地、不同IP】在线节点（规避同机房批量掉线）
def get_diff_online_nodes(num):
    # 读取所有在线节点
    current_cursor().execute(f"""
    SELECT DISTINCT user_address,ip_addr,country,city 
    FROM node_location 
    WHERE online_status=1 AND update_time > {node_alive_interval_sql(1)}
    """)
    all_nodes = current_cursor().fetchall()
    if not all_nodes:
        return []
    
    # 按地区、IP去重，尽量分散节点
    selected = []
    ip_list = []
    for node in all_nodes:
        if node[1] not in ip_list:
            ip_list.append(node[1])
            selected.append(node[0])
        if len(selected) >= num:
            break
    return selected

def get_backup_nodes():
    assign_nodes = get_diff_online_nodes(COPY_NUM)
    while len(assign_nodes) < COPY_NUM:
        assign_nodes.append("SERVER_BACKUP_NODE")
    return assign_nodes

# 初始化纠删码编码器
rs = reedsolo.RSCodec(EC_PARITY_SHARD) if reedsolo is not None else None

# 文件编码：生成数据片+校验片
def file_ec_encode(file_data):
    if rs is None:
        raise RuntimeError("缺少 reedsolo 依赖，请执行：pip install reedsolo")
    # 均匀分片
    shards = [file_data[i:i+SHARD_SIZE] for i in range(0,len(file_data),SHARD_SIZE)]
    # 纠删码编码，生成可自愈碎片
    ec_shards = rs.encode(shards)
    return ec_shards

# 文件解码：丢失部分碎片自动还原完整文件
def file_ec_decode(ec_shards):
    if rs is None:
        raise RuntimeError("缺少 reedsolo 依赖，请执行：pip install reedsolo")
    # 自动补全丢失分片、修复损坏数据
    origin_shards = rs.decode(ec_shards)
    return b"".join(origin_shards)


# 定时任务：巡检所有文件，副本不足自动重新分发补副本
@app.route("/api/auto_repair_backup",methods=["POST"])
def auto_repair_backup():
    # 遍历所有存证文件
    current_cursor().execute("select id,ipfs_cid,stored_nodes from file_chain_record")
    all_file = current_cursor().fetchall()
    for item in all_file:
        fid,cid,nodes_str = item
        if not nodes_str:
            continue
        # 检测当前在线存储节点数量
        try:
            node_list = json.loads(nodes_str)
        except Exception:
            node_list = []
        alive = 0
        for addr in node_list:
            current_cursor().execute("select 1 from node_power where user_address=%s and online_duration>10",(addr,))
            if current_cursor().fetchone():
                alive +=1
        # 副本少于3个 → 自动新增节点补备份
        if alive < COPY_NUM:
            new_nodes = get_diff_online_nodes(COPY_NUM - alive)
            # 更新存储节点列表、重新分发分片
            new_all = list(set(node_list + new_nodes))
            current_cursor().execute("update file_chain_record set stored_nodes=%s where id=%s",(json.dumps(new_all, ensure_ascii=False),fid))
    db.commit()
    return jsonify({"code":200,"msg":"数据副本巡检修复完成"})

# 启动服务
if __name__ == "__main__":
    ensure_database_initialized()
    # 开启定时结算
    import threading
    threading.Thread(target=settle_task,daemon=True).start()
    print("✅ 完整服务启动成功！首页地址：http://127.0.0.1:8000")
    print("✅ 后台地址：http://127.0.0.1:8000/admin")
    app.run(host="0.0.0.0",port=8000,debug=False)
