from flask import Blueprint, jsonify

from app.services import pcdn


bp = Blueprint("pcdn_api", __name__)


def legacy_server():
    import server_main

    return server_main


def require_admin():
    if legacy_server().admin_token_is_valid():
        return None
    return jsonify({"code": 401, "msg": "缺少或无效的后台访问 Token"}), 401


@bp.route("/api/pcdn/status", methods=["GET"])
def pcdn_status():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({"code": 200, "data": pcdn.service.pcdn_status(legacy.SERVER_CONFIG)})


@bp.route("/api/pcdn/tasks", methods=["GET"])
def pcdn_tasks():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({"code": 200, "data": pcdn.service.list_tasks(legacy.SERVER_CONFIG)})


@bp.route("/api/pcdn/tasks", methods=["POST"])
def pcdn_task_create():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({
        "code": 200,
        "msg": "PCDN task created",
        "data": pcdn.service.create_task(legacy.SERVER_CONFIG, legacy.get_json_body()),
    })


@bp.route("/api/pcdn/sync", methods=["POST"])
def pcdn_sync():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({
        "code": 200,
        "msg": "PCDN usage synced",
        "data": pcdn.service.sync_usage(legacy.SERVER_CONFIG),
    })


@bp.route("/api/pcdn/node_metrics", methods=["GET"])
def pcdn_node_metrics():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    data = pcdn.service.sync_usage(legacy.SERVER_CONFIG)
    return jsonify({"code": 200, "data": data["metrics"]})


@bp.route("/api/pcdn/settlements", methods=["GET"])
@bp.route("/api/pcdn/settlements/run", methods=["POST"])
def pcdn_settlements():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({
        "code": 200,
        "msg": "PCDN settlements ready",
        "data": pcdn.service.run_settlement(legacy.SERVER_CONFIG),
    })
