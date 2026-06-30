from flask import Blueprint, jsonify, render_template, render_template_string, request

from app.web.pages import (
    ADMIN_DASHBOARD_TEMPLATE,
    ADMIN_LOGIN_TEMPLATE,
    HOME_HTML,
    MANAGEMENT_CONSOLE_TEMPLATE,
    NODE_LOOKUP_TEMPLATE,
    PUBLIC_SHARE_TEMPLATE,
    USER_DASHBOARD_TEMPLATE,
    USER_LOGIN_TEMPLATE,
    USER_UPLOAD_TEMPLATE,
)


bp = Blueprint("pages", __name__)


def legacy_server():
    import server_main

    return server_main


@bp.route("/")
def home_page():
    return render_template_string(HOME_HTML)


@bp.route("/admin")
def admin_index():
    legacy = legacy_server()
    amap_enabled = legacy.AMAP_WEB_KEY and legacy.AMAP_SECURITY_JSCODE
    return render_template(
        ADMIN_DASHBOARD_TEMPLATE,
        amap_web_key=legacy.AMAP_WEB_KEY if amap_enabled else "",
        amap_security_jscode=legacy.AMAP_SECURITY_JSCODE if amap_enabled else "",
        business_mode=legacy.SERVER_CONFIG.business_mode,
        pcdn_provider=legacy.SERVER_CONFIG.pcdn_provider,
    )


def normalized_console_role(default_role="user"):
    role = str(request.args.get("role") or default_role or "user").strip().lower()
    return "admin" if role == "admin" else "user"


def render_management_console(role="user"):
    safe_role = "admin" if role == "admin" else "user"
    return render_template(
        MANAGEMENT_CONSOLE_TEMPLATE,
        role=safe_role,
        role_label="管理员" if safe_role == "admin" else "用户",
        role_title="管理员运营台" if safe_role == "admin" else "用户工作台",
    )


@bp.route("/console")
def management_console_page():
    return render_management_console(normalized_console_role("user"))


@bp.route("/admin/console")
def admin_console_page():
    return render_management_console("admin")


@bp.route("/user/console")
def user_console_page():
    return render_management_console("user")


@bp.route("/admin/login")
def admin_login_page():
    return render_template(ADMIN_LOGIN_TEMPLATE)


@bp.route("/api/admin/login", methods=["POST"])
def admin_login_api():
    legacy = legacy_server()
    if not legacy.ADMIN_API_TOKEN:
        return jsonify({"code": 503, "msg": "后台 Token 未配置"}), 503
    token = legacy.get_json_body().get("token", "")
    if not legacy.admin_token_value_is_valid(token):
        return jsonify({"code": 401, "msg": "后台 Token 错误", "authenticated": False}), 401
    return jsonify({"code": 200, "msg": "登录成功", "authenticated": True})


@bp.route("/user/upload")
def user_upload_page():
    return render_template(USER_UPLOAD_TEMPLATE)


@bp.route("/user/login")
def user_login_page():
    return render_template(USER_LOGIN_TEMPLATE)


@bp.route("/user/dashboard")
def user_dashboard_page():
    return render_template(USER_DASHBOARD_TEMPLATE)


@bp.route("/node/lookup")
def node_lookup_page():
    return render_template(NODE_LOOKUP_TEMPLATE)


@bp.route("/s/<share_code>")
def public_share_page(share_code):
    return render_template(PUBLIC_SHARE_TEMPLATE, share_code=share_code)


@bp.route("/api/health")
def health_check():
    legacy = legacy_server()
    db_ok = legacy.init_db()
    return jsonify({
        "code": 200 if db_ok else 503,
        "server": "ok",
        "database": "ok" if db_ok else "error",
        "db_error": legacy.db_error,
    }), 200 if db_ok else 503
