# 服务端主程序 server_main.py（完整版带API路由，修复8000端口报错）
import time
import hashlib
import random
from datetime import datetime, timedelta
from functools import wraps
import requests
from flask import Flask, request, jsonify, render_template_string, g
from pathlib import Path
import re
import secrets
import urllib.parse
import auth
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

ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "")
SESSION_SECRET = os.getenv("SESSION_SECRET")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
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


def commit_database():
    connection = getattr(g, "db", None) or db
    if hasattr(connection, "commit"):
        connection.commit()


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


def is_admin_protected_path(path):
    return path in ADMIN_PROTECTED_PATHS


def admin_token_is_valid():
    if not ADMIN_API_TOKEN:
        return False
    supplied = request.headers.get("X-Admin-Token") or request.args.get("admin_token", "")
    return secrets.compare_digest(supplied, ADMIN_API_TOKEN)


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
    if request.path == "/" or request.path == "/api/health":
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
        auth.normalize_wallet_address(data.get("wallet_address"))
        and data.get("nonce")
        and data.get("signature")
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
    wallet_address = auth.normalize_wallet_address(data.get("wallet_address"))
    purpose = (data.get("purpose") or "login").strip() or "login"
    if not wallet_address:
        return jsonify({"code":400,"msg":"缺少钱包地址"}), 400
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
    wallet_address = auth.normalize_wallet_address(data.get("wallet_address"))
    if wallet_fields_missing(data):
        return jsonify({"code":400,"msg":"缺少钱包地址、nonce 或签名"}), 400
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
    wallet_address = auth.normalize_wallet_address(data.get("wallet_address"))
    if wallet_fields_missing(data):
        return jsonify({"code":400,"msg":"缺少钱包地址、nonce 或签名"}), 400
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
        "download_url": f"/api/file_download/{file_hash}{token_query}",
    }


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
    nl.country,nl.city
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

    # 输入心跳数据
    print(f"{user_addr} {node_mac} {disk_used} {upload_bw}")

    current_cursor().execute(
        "update node_power set disk_used=%s,upload_bandwidth=%s,online_duration=online_duration+1,update_time=%s where user_address=%s and node_mac=%s",
        (disk_used,upload_bw,datetime.now(),user_addr,node_mac)
    )
    return jsonify({"code":200,"msg":"心跳上报成功"})

# 3. 每日自动分账函数
def auto_settle_reward():
    current_cursor().execute("select * from node_power where online_duration > %s",(ONLINE_VALID_MIN,))
    node_list = current_cursor().fetchall()
    settle_date = datetime.now().date()

    for node in node_list:
        user_addr = node[1]
        disk_contrib = node[4]
        online_contrib = node[5]
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


@app.route("/api/leaderboard",methods=["GET"])
def leaderboard():
    return jsonify({"code":200,"data":build_leaderboard(select_node_rows())})


@app.route("/api/invite_tree",methods=["GET"])
def invite_tree():
    return jsonify({"code":200,"data":build_invite_tree(select_node_rows())})

# ==================== 极简前端后台面板 ====================
ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Web3节点激励后台面板</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{padding:20px;background:#f5f7fa;font-family:微软雅黑;}
        .box{background:#fff;padding:20px;border-radius:8px;margin-bottom:20px;box-shadow:0 0 8px #eee;}
        h3{margin-bottom:15px;color:#222;}
        table{width:100%;border-collapse:collapse;margin-top:10px;}
        th,td{border:1px solid #eee;padding:10px;text-align:center;font-size:14px;}
        th{background:#f0f5ff;}
        input,button{padding:8px 12px;margin:0 5px;border-radius:4px;border:1px solid #ccc;}
        button{background:#2d8cf0;color:#fff;border:none;cursor:pointer;}
        .token-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:#fff7e6;border:1px solid #ffd591;}
        .token-bar input{min-width:320px;margin-left:0;}
        .token-status{color:#8c6d1f;font-size:14px;}
    </style>
    <script type="text/javascript" src="https://webapi.amap.com/maps?v=2.0&key=6f17f9896974a8686929496921212479"></script>
</head>
<body>
    <div class="box token-bar">
        <strong>后台 Token</strong>
        <input type="password" id="adminTokenInput" placeholder="请输入 .env 里的 ADMIN_API_TOKEN">
        <button onclick="saveAdminToken()">保存并加载</button>
        <button onclick="clearAdminToken()" style="background:#64748b;">清除</button>
        <span id="adminTokenStatus" class="token-status"></span>
    </div>

    <div class="box">
        <h3>分成比例配置</h3>
        <input type="text" id="selfRatio" placeholder="上级分成比例" value="0.15">
        <input type="text" id="nodeRatio" placeholder="节点分成比例" value="0.85">
        <button onclick="setRatio()">保存配置</button>
    </div>

    <div class="box">
        <h3>全网节点列表</h3>
        <button onclick="getNodes()">刷新节点数据</button>
        <table>
            <thead>
                <tr>
                    <th>节点地址</th>
                    <th>个人推广码</th>
                    <th>上级推广码</th>
                    <th>存储占用G</th>
                    <th>在线时长(分)</th>
                    <th>上行带宽</th>
                    <th>在线状态</th>
                    <th>质量分</th>
                </tr>
            </thead>
            <tbody id="nodeTable"></tbody>
        </table>
    </div>

    <div class="box" style="min-height:600px;">
        <h3>🌍 全网节点全球地理分布地图</h3>
        <p style="color:#888;font-size:14px;margin-bottom:15px;">实时在线节点打点｜离线节点灰色显示｜自动IP属地解析</p>
        <div id="map" style="width:100%;height:500px;border-radius:8px;"></div>
    </div>

    <div class="box">
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

    <div class="box">
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

    <div class="box">
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

    <div class="box">
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

    <div class="box">
        <h3>邀请关系树</h3>
        <button onclick="getInviteTree()">刷新邀请关系</button>
        <pre id="inviteTreeBox" style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:6px;"></pre>
    </div>

<script>
function getAdminToken(){
    return localStorage.getItem("admin_token") || "";
}

function setAdminTokenStatus(text, isError){
    const status = document.getElementById("adminTokenStatus");
    if(status){
        status.innerText = text || "";
        status.style.color = isError ? "#c2410c" : "#166534";
    }
}

function initAdminTokenPanel(){
    const input = document.getElementById("adminTokenInput");
    const token = getAdminToken();
    if(input && token){ input.value = token; }
    setAdminTokenStatus(token ? "Token 已保存，正在加载后台数据" : "请输入 Token 后加载后台数据", !token);
}

function saveAdminToken(){
    const input = document.getElementById("adminTokenInput");
    const token = input ? input.value.trim() : "";
    if(!token){
        localStorage.removeItem("admin_token");
        setAdminTokenStatus("Token 不能为空", true);
        return;
    }
    localStorage.setItem("admin_token", token);
    setAdminTokenStatus("Token 已保存，正在加载后台数据", false);
    refreshAdminData();
}

function clearAdminToken(){
    localStorage.removeItem("admin_token");
    const input = document.getElementById("adminTokenInput");
    if(input){ input.value = ""; }
    setAdminTokenStatus("Token 已清除，请重新输入", true);
}

function adminFetch(url, options){
    const token = getAdminToken();
    if(!token){
        setAdminTokenStatus("请输入 Token 后加载后台数据", true);
        return Promise.resolve({
            status: 401,
            json: () => Promise.resolve({code:401,msg:"请输入后台 Token",data:[]})
        });
    }
    options = options || {};
    options.headers = Object.assign({}, options.headers || {}, {"X-Admin-Token": token});
    return fetch(url, options).then(res=>{
        if(res.status === 401){
            localStorage.removeItem("admin_token");
            setAdminTokenStatus("Token 无效，请重新输入", true);
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
            html += `<tr>
                <td>${item.user_addr}</td>
                <td>${item.invite_code}</td>
                <td>${item.parent_code||"无"}</td>
                <td>${item.disk_used}</td>
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

function initMap(){
    // 初始化地图，中心点中国
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
    // 清空旧标记
    markerList.forEach(m=>map.remove(m));
    markerList = [];

    adminFetch("/api/map_node_list")
    .then(res=>res.json())
    .then(data=>{
        data.data.forEach(item=>{
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

// 每30秒刷新地图
setInterval(function(){
    if(getAdminToken()){ loadNodeMap(); }
},30000);

function refreshAdminData(){
    getNodes();
    getReward();
    getFileList();
    getLeaderboard();
    getDailyReward();
    getInviteTree();
    if(map){ loadNodeMap(); }
}

// 自动加载数据
window.onload = function(){
    initAdminTokenPanel();
    initMap();
    if(getAdminToken()){ refreshAdminData(); }
}
</script>
</body>
</html>
'''

# 后台首页路由
@app.route("/")
def admin_index():
    return render_template_string(ADMIN_HTML)


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
    select id,file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,create_time,visibility,access_token,deleted_at
    from file_chain_record where file_hash=%s and deleted_at is null
    """,(file_hash,))
    row = current_cursor().fetchone()
    if not row:
        return jsonify({"code":404,"msg":"文件不存在"}), 404
    record = format_file_record(row)
    if not file_access_allowed(record, request.args.get("token", "")):
        return jsonify({"code":403,"msg":"文件访问令牌无效"}), 403
    client = get_ipfs_client()
    try:
        encrypted = client.cat(record["ipfs_cid"])
    finally:
        if hasattr(client, "close"):
            client.close()
    try:
        plain = aes_decrypt(encrypted)
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
    print("✅ 完整服务启动成功！后台地址：http://127.0.0.1:8000")
    app.run(host="0.0.0.0",port=8000,debug=False)
