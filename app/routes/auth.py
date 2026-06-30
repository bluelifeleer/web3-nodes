from datetime import datetime, timedelta
import secrets

from flask import Blueprint, g, jsonify


bp = Blueprint("auth_api", __name__)


def legacy_server():
    import server_main

    return server_main


@bp.route("/api/auth/register", methods=["POST"])
def auth_register():
    legacy = legacy_server()
    data = legacy.get_json_body()
    raw_username = data.get("username")
    raw_password = data.get("password")
    if not isinstance(raw_username, str) or not isinstance(raw_password, str):
        return jsonify({"code": 400, "msg": "缺少用户名或密码"}), 400
    username = raw_username.strip()
    password = raw_password
    if not username or not password:
        return jsonify({"code": 400, "msg": "缺少用户名或密码"}), 400
    if not legacy.SESSION_SECRET:
        return legacy.session_secret_missing_response()
    if legacy.select_user_by_username(username):
        return jsonify({"code": 409, "msg": "用户名已存在"}), 409
    try:
        legacy.current_cursor().execute(
            "insert into app_user(username,password_hash) values(%s,%s)",
            (username, legacy.auth.hash_password(password)),
        )
        legacy.commit_database()
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            return jsonify({"code": 409, "msg": "用户名已存在"}), 409
        return jsonify({"code": 500, "msg": "用户注册失败"}), 500
    user_row = legacy.select_user_by_username(username)
    token, user = legacy.create_user_session(user_row)
    if not token:
        return legacy.session_secret_missing_response()
    return jsonify({"code": 200, "msg": "注册成功", "token": token, "user": user})


@bp.route("/api/auth/login", methods=["POST"])
def auth_login():
    legacy = legacy_server()
    data = legacy.get_json_body()
    raw_username = data.get("username")
    raw_password = data.get("password")
    if not isinstance(raw_username, str) or not isinstance(raw_password, str):
        return jsonify({"code": 400, "msg": "缺少用户名或密码"}), 400
    username = raw_username.strip()
    password = raw_password
    if not username or not password:
        return jsonify({"code": 400, "msg": "缺少用户名或密码"}), 400
    if not legacy.SESSION_SECRET:
        return legacy.session_secret_missing_response()
    user_row = legacy.select_user_by_username(username)
    if not user_row or not legacy.auth.verify_password(password, user_row[2]):
        return jsonify({"code": 401, "msg": "用户名或密码错误"}), 401
    if not legacy.user_is_active(user_row):
        return jsonify({"code": 401, "msg": "用户名或密码错误"}), 401
    legacy.current_cursor().execute("update app_user set last_login_at=%s where id=%s", (datetime.now(), user_row[0]))
    legacy.commit_database()
    fresh_user = legacy.select_user_by_id(user_row[0]) or user_row
    if not legacy.user_is_active(fresh_user):
        return jsonify({"code": 401, "msg": "用户名或密码错误"}), 401
    token, user = legacy.create_user_session(fresh_user)
    if not token:
        return legacy.session_secret_missing_response()
    return jsonify({"code": 200, "msg": "登录成功", "token": token, "user": user})


@bp.route("/api/auth/me", methods=["GET"])
def auth_me():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        return jsonify({"code": 200, "user": legacy.format_user(g.current_user_row)})

    return view()


@bp.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    response = jsonify({"code": 200, "msg": "已退出登录"})
    response.delete_cookie("user_token")
    return response


@bp.route("/api/wallet/nonce", methods=["POST"])
def wallet_nonce():
    legacy = legacy_server()
    data = legacy.get_json_body()
    if legacy.wallet_nonce_fields_invalid(data):
        return jsonify({"code": 400, "msg": "缺少钱包地址"}), 400
    wallet_address = legacy.auth.normalize_wallet_address(data.get("wallet_address"))
    purpose = (data.get("purpose") or "login").strip() or "login"
    nonce = secrets.token_urlsafe(24)
    expires_at = datetime.now() + timedelta(minutes=10)
    legacy.current_cursor().execute(
        "insert into wallet_nonce(wallet_address,nonce,expires_at) values(%s,%s,%s)",
        (wallet_address, nonce, expires_at),
    )
    legacy.commit_database()
    return jsonify({
        "code": 200,
        "wallet_address": wallet_address,
        "nonce": nonce,
        "purpose": purpose,
        "message": legacy.auth.build_wallet_message(nonce, purpose),
        "expires_at": expires_at.isoformat(),
    })


@bp.route("/api/wallet/bind", methods=["POST"])
def wallet_bind():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        data = legacy.get_json_body()
        if legacy.wallet_fields_missing(data):
            return jsonify({"code": 400, "msg": "缺少钱包地址、nonce 或签名"}), 400
        wallet_address = legacy.auth.normalize_wallet_address(data.get("wallet_address"))
        ok, msg = legacy.consume_wallet_nonce(wallet_address, data.get("nonce"), "bind", data.get("signature"))
        if not ok:
            return jsonify({"code": 400, "msg": msg}), 400
        try:
            legacy.current_cursor().execute(
                "update app_user set wallet_address=%s where id=%s",
                (wallet_address, g.current_user.get("user_id")),
            )
            legacy.commit_database()
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                return jsonify({"code": 409, "msg": "钱包地址已绑定其他用户"}), 409
            return jsonify({"code": 500, "msg": "钱包绑定失败"}), 500
        user_row = legacy.select_user_by_id(g.current_user.get("user_id"))
        return jsonify({"code": 200, "msg": "钱包绑定成功", "user": legacy.format_user(user_row)})

    return view()


@bp.route("/api/wallet/login", methods=["POST"])
def wallet_login():
    legacy = legacy_server()
    data = legacy.get_json_body()
    if legacy.wallet_fields_missing(data):
        return jsonify({"code": 400, "msg": "缺少钱包地址、nonce 或签名"}), 400
    wallet_address = legacy.auth.normalize_wallet_address(data.get("wallet_address"))
    if not legacy.SESSION_SECRET:
        return legacy.session_secret_missing_response()
    ok, msg = legacy.consume_wallet_nonce(wallet_address, data.get("nonce"), "login", data.get("signature"))
    if not ok:
        return jsonify({"code": 400, "msg": msg}), 400
    user_row = legacy.select_user_by_wallet(wallet_address)
    if not user_row:
        return jsonify({"code": 401, "msg": "钱包地址未绑定用户"}), 401
    if not legacy.user_is_active(user_row):
        return jsonify({"code": 401, "msg": "钱包地址未绑定用户"}), 401
    legacy.current_cursor().execute("update app_user set last_login_at=%s where id=%s", (datetime.now(), user_row[0]))
    legacy.commit_database()
    fresh_user = legacy.select_user_by_id(user_row[0]) or user_row
    if not legacy.user_is_active(fresh_user):
        return jsonify({"code": 401, "msg": "钱包地址未绑定用户"}), 401
    token, user = legacy.create_user_session(fresh_user)
    if not token:
        return legacy.session_secret_missing_response()
    return jsonify({"code": 200, "msg": "登录成功", "token": token, "user": user})
