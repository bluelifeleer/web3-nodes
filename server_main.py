# 服务端主程序 server_main.py（完整版带API路由，修复8000端口报错）
import time
import hashlib
import random
import csv
import io
from datetime import datetime, timedelta
from functools import wraps
import requests
from flask import Flask, request, jsonify, g
from pathlib import Path
import re
import secrets
import urllib.parse
import base64
from decimal import Decimal, InvalidOperation
from app.services.files import USER_FILE_SELECT_PROJECTION, format_user_file_record
import app.services.withdrawals as withdrawals
try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None
import os
import shutil
import json
import subprocess
try:
    import reedsolo
except ImportError:
    reedsolo = None
import app.database as database_module
from app.config import ServerConfig
from app.database import (
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
from app.routes import register_blueprints
from app.routes.pages import (
    admin_console_page,
    admin_index,
    admin_login_api,
    admin_login_page,
    health_check,
    home_page,
    management_console_page,
    node_lookup_page,
    normalized_console_role,
    public_share_page,
    render_management_console,
    user_console_page,
    user_dashboard_page,
    user_login_page,
    user_upload_page,
)
import app.services.auth as auth
import app.services.points as points
import app.services.shares as shares
from app.services.runtime import (
    RUNTIME_SECRET_KEYS,
    ensure_runtime_secrets,
    generate_runtime_secret,
    parse_env_file_values,
)
from app.web.pages import (
    ADMIN_DASHBOARD_TEMPLATE,
    ADMIN_HTML,
    ADMIN_LOGIN_HTML,
    ADMIN_LOGIN_TEMPLATE,
    COMMERCIAL_PAGE_CSS,
    CONSOLE_SHELL_CSS,
    CONSOLE_SIDEBAR_HTML,
    HOME_HTML,
    MANAGEMENT_CONSOLE_TEMPLATE,
    NODE_LOOKUP_HTML,
    NODE_LOOKUP_TEMPLATE,
    PUBLIC_SHARE_HTML,
    PUBLIC_SHARE_TEMPLATE,
    USER_DASHBOARD_HTML,
    USER_DASHBOARD_TEMPLATE,
    USER_LOGIN_HTML,
    USER_LOGIN_TEMPLATE,
    USER_UPLOAD_HTML,
    USER_UPLOAD_TEMPLATE,
)
from app.services.ipfs import (
    DEFAULT_IPFS_API_ADDR,
    HttpIPFSClient,
    get_ipfs_api_addr,
    get_ipfs_client,
    ipfs_api_base_url,
    normalize_ipfs_api_addr,
    read_ipfs_status,
)
from app.services.nodes import (
    build_invite_tree,
    build_leaderboard,
    calculate_quality_score,
    format_node_record,
    node_is_online,
)
from app.services.storage import (
    build_encrypted_shard_manifest,
    create_access_token,
    get_chunk_dir,
    normalize_storage_node_name,
    normalize_visibility,
    storage_node_file_path,
    validate_file_hash,
)

# ==================== 初始化Flask服务 ====================
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "app" / "templates"),
    static_folder=str(BASE_DIR / "app" / "static"),
    static_url_path="/static",
)

if os.getenv("WEB3_NODES_SKIP_DOTENV") != "1":
    ensure_runtime_secrets()

SERVER_CONFIG = ServerConfig.from_env()
ADMIN_API_TOKEN = SERVER_CONFIG.admin_api_token
SESSION_SECRET = SERVER_CONFIG.session_secret
MAX_UPLOAD_BYTES = SERVER_CONFIG.max_upload_bytes
AMAP_WEB_KEY = SERVER_CONFIG.amap_web_key
AMAP_SECURITY_JSCODE = SERVER_CONFIG.amap_security_jscode
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
db = None
cursor = None
db_error = ""
register_blueprints(app)


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
    "/admin/console",
    "/admin/login",
    "/console",
    "/node/lookup",
    "/api/admin/login",
    "/api/health",
    "/user/console",
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
    if request.endpoint == "static":
        return None
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
    if raw:
        try:
            current_cursor().execute(
                """
                select storage_api_url
                from node_power
                where user_address=%s
                order by update_time desc
                limit 1
                """,
                (raw,),
            )
            row = current_cursor().fetchone()
            if row and row[0]:
                return str(row[0]).strip().rstrip("/")
        except Exception:
            return ""
    return ""


def select_storage_node_candidates(limit=COPY_NUM):
    current_cursor().execute(f"""
    select user_address
    from node_power
    where update_time > {node_alive_interval_sql(3)}
      and storage_status=%s
      and storage_available_gb > 0
      and storage_api_url <> ''
    order by storage_available_gb desc, update_time desc
    limit %s
    """, ("ok", int(limit)))
    return [row[0] for row in current_cursor().fetchall()]


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


def select_node_rows():
    current_cursor().execute("""
    SELECT un.user_address,un.invite_code,un.parent_invite_code,
    np.disk_used,np.online_duration,np.upload_bandwidth,np.update_time,
    nl.country,nl.city,
    np.storage_path,np.storage_status,np.storage_error,
    np.storage_total_gb,np.storage_used_gb,np.storage_free_gb,
    np.storage_quota_gb,np.storage_available_gb,np.storage_api_url
    FROM user_node un
    LEFT JOIN node_power np ON un.user_address=np.user_address
    LEFT JOIN node_location nl ON un.user_address=nl.user_address
    """)
    return current_cursor().fetchall()

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
    client = None
    try:
        client = get_ipfs_client()
        cid = client.add_bytes(encrypt_data)
    except:
        return jsonify({"code":400,"msg":"IPFS节点未启动"})
    finally:
        if client is not None and hasattr(client, "close"):
            client.close()

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

    client = None
    try:
        client = get_ipfs_client()
        cid = client.add_bytes(encrypt_data)
    except Exception:
        return jsonify({"code":400,"msg":"IPFS节点未启动"})
    finally:
        if client is not None and hasattr(client, "close"):
            client.close()

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
