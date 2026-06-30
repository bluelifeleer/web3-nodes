from datetime import datetime
import json

from flask import Blueprint, g, jsonify, request


bp = Blueprint("node_api", __name__)


def legacy_server():
    import server_main

    return server_main


def parse_node_identity_lookup_payload():
    raw_payload = None
    upload = request.files.get("identity_file")
    if upload:
        raw_payload = upload.read().decode("utf-8")
    elif request.form.get("identity_text"):
        raw_payload = request.form.get("identity_text")
    elif request.form.get("identity"):
        raw_payload = request.form.get("identity")

    if raw_payload is not None:
        try:
            payload = json.loads(raw_payload)
        except (TypeError, ValueError):
            return None, "节点标识文件不是有效 JSON"
    else:
        payload = request.get_json(silent=True) or {}

    if not isinstance(payload, dict):
        return None, "节点标识格式无效"
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else payload
    user_addr = str(identity.get("user_addr") or identity.get("node_address") or "").strip()[:128]
    node_mac = str(identity.get("node_mac") or "").strip()[:128]
    if not user_addr or not node_mac:
        return None, "节点标识缺少 user_addr 或 node_mac"
    return {"user_addr": user_addr, "node_mac": node_mac}, ""


@bp.route("/register", methods=["POST"])
def node_register():
    legacy = legacy_server()
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    parent_invite = data.get("parent_invite", "")

    legacy.current_cursor().execute("select * from node_power where node_mac=%s", (node_mac,))
    if legacy.current_cursor().fetchone():
        return jsonify({"code": 200, "msg": "节点已注册，无需重复绑定"})

    invite_code = legacy.create_invite_code()
    legacy.current_cursor().execute(
        "insert into user_node(user_address,invite_code,parent_invite_code) values(%s,%s,%s)",
        (user_addr, invite_code, parent_invite),
    )
    legacy.current_cursor().execute(
        "insert into node_power(user_address,node_mac) values(%s,%s)",
        (user_addr, node_mac),
    )
    return jsonify({"code": 200, "msg": "节点注册成功，上级绑定完成", "invite_code": invite_code})


@bp.route("/heartbeat", methods=["POST"])
def node_heartbeat():
    legacy = legacy_server()
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    disk_used = data.get("disk_used", 0)
    upload_bw = data.get("upload_bw", 0)
    storage_path = str(data.get("storage_path") or "")[:255]
    storage_status = str(data.get("storage_status") or "unknown")[:32]
    storage_error = str(data.get("storage_error") or "")[:255]
    storage_total_gb = float(data.get("storage_total_gb") or 0)
    storage_used_gb = float(data.get("storage_used_gb") or disk_used or 0)
    storage_free_gb = float(data.get("storage_free_gb") or 0)
    storage_quota_gb = float(data.get("storage_quota_gb") or 0)
    storage_available_gb = float(data.get("storage_available_gb") or 0)
    storage_api_url = str(data.get("storage_api_url") or "")[:255]

    print(f"{user_addr} {node_mac} {disk_used} {upload_bw}")

    legacy.current_cursor().execute(
        "update node_power set disk_used=%s,upload_bandwidth=%s,storage_path=%s,storage_status=%s,storage_error=%s,storage_total_gb=%s,storage_used_gb=%s,storage_free_gb=%s,storage_quota_gb=%s,storage_available_gb=%s,storage_api_url=%s,online_duration=online_duration+1,update_time=%s where user_address=%s and node_mac=%s",
        (
            disk_used,
            upload_bw,
            storage_path,
            storage_status,
            storage_error,
            storage_total_gb,
            storage_used_gb,
            storage_free_gb,
            storage_quota_gb,
            storage_available_gb,
            storage_api_url,
            datetime.now(),
            user_addr,
            node_mac,
        ),
    )
    return jsonify({"code": 200, "msg": "心跳上报成功"})


@bp.route("/api/node_list", methods=["GET"])
def node_list():
    legacy = legacy_server()
    return jsonify({"code": 200, "data": [legacy.format_node_record(item) for item in legacy.select_node_rows()]})


@bp.route("/api/reward_list", methods=["GET"])
def reward_list():
    legacy = legacy_server()
    legacy.current_cursor().execute("""
    select id,user_address,reward_type,reward_amount,node_contribution,settle_time,source_user_address,settle_date
    from node_reward order by settle_time desc
    """)
    data_list = []
    for item in legacy.current_cursor().fetchall():
        data_list.append({
            "id": item[0],
            "user_addr": item[1],
            "reward_type": "本级收益" if item[2] == 1 else "上级分成",
            "amount": item[3],
            "contrib": item[4],
            "time": str(item[5]),
            "source_user": item[6],
            "settle_date": str(item[7]) if item[7] else "",
        })
    return jsonify({"code": 200, "data": data_list})


@bp.route("/api/reward_daily", methods=["GET"])
def reward_daily():
    legacy = legacy_server()
    legacy.current_cursor().execute("""
    select settle_date,user_address,reward_type,sum(reward_amount),sum(node_contribution),count(*)
    from node_reward
    group by settle_date,user_address,reward_type
    order by settle_date desc,user_address
    """)
    data = []
    for item in legacy.current_cursor().fetchall():
        data.append({
            "settle_date": str(item[0]) if item[0] else "",
            "user_addr": item[1],
            "reward_type": "本级收益" if item[2] == 1 else "上级分成",
            "amount": round(float(item[3] or 0), 4),
            "contrib": round(float(item[4] or 0), 4),
            "count": item[5],
        })
    return jsonify({"code": 200, "data": data})


@bp.route("/api/node/me", methods=["GET"])
def node_me():
    legacy = legacy_server()
    identity, error_response = legacy.require_node_identity()
    if error_response:
        return error_response
    return jsonify({"code": 200, "data": identity})


@bp.route("/api/node/earnings", methods=["GET"])
def node_earnings():
    legacy = legacy_server()
    identity, error_response = legacy.require_node_identity()
    if error_response:
        return error_response
    return jsonify({"code": 200, "data": legacy.calculate_node_earnings(identity["user_addr"])})


@bp.route("/api/node/identity/lookup", methods=["POST"])
def node_identity_lookup():
    legacy = legacy_server()
    identity_request, message = parse_node_identity_lookup_payload()
    if not identity_request:
        return jsonify({"code": 400, "msg": message}), 400
    row = legacy.select_node_identity_row(identity_request["user_addr"], identity_request["node_mac"])
    if not row:
        return jsonify({"code": 404, "msg": "节点不存在或标识不匹配", "data": {"found": False}}), 404
    identity = legacy.format_node_identity_row(row)
    earnings = legacy.calculate_node_earnings(identity["user_addr"])
    legacy.current_cursor().execute(
        """
        select id,user_id,wallet_address,amount,status,admin_note,created_at,reviewed_at,
        node_address,withdrawal_channel,withdrawal_account
        from withdrawal_request
        where node_address=%s
        order by created_at desc,id desc
        limit 20
        """,
        (identity["user_addr"],),
    )
    withdrawals = [legacy.format_withdrawal_row(item) for item in legacy.current_cursor().fetchall()]
    return jsonify({
        "code": 200,
        "data": {
            "found": True,
            "identity": identity_request,
            "node": identity,
            "earnings": earnings,
            "withdrawals": withdrawals,
        },
    })


@bp.route("/api/node/withdrawals", methods=["GET"])
def node_withdrawal_list():
    legacy = legacy_server()
    identity, error_response = legacy.require_node_identity()
    if error_response:
        return error_response
    legacy.current_cursor().execute(
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
        "code": 200,
        "data": [legacy.format_withdrawal_row(row) for row in legacy.current_cursor().fetchall()],
    })


@bp.route("/api/node/withdrawals", methods=["POST"])
def node_withdrawal_create():
    legacy = legacy_server()
    data = legacy.get_json_body()
    identity, error_response = legacy.require_node_identity()
    if error_response:
        return error_response
    amount, message = legacy.withdrawals.parse_withdrawal_amount(data.get("amount"))
    if amount is None:
        return jsonify({"code": 400, "msg": message}), 400
    wallet_address = str(data.get("wallet_address") or "").strip()[:128]
    if not wallet_address:
        return jsonify({"code": 400, "msg": "缺少 wallet_address"}), 400
    amount_for_db = legacy.withdrawals.format_withdrawal_amount(amount)

    with legacy.DatabaseTransaction():
        try:
            locked_row = legacy.lock_node_identity_for_update(identity["user_addr"], identity["node_mac"])
            if not locked_row:
                legacy.rollback_database()
                return jsonify({"code": 401, "msg": "节点身份校验失败"}), 401
            identity = legacy.format_node_identity_row(locked_row)
            g.current_node = identity
            summary = legacy.calculate_node_earnings(identity["user_addr"], include_decimal=True)
            if amount > summary["_available_earnings_decimal"]:
                legacy.rollback_database()
                summary.pop("_available_earnings_decimal", None)
                return jsonify({"code": 400, "msg": "可提现余额不足", "data": summary}), 400
            legacy.current_cursor().execute(
                """
                insert into withdrawal_request(
                    user_id,wallet_address,amount,status,node_address,withdrawal_channel,withdrawal_account
                )
                values(%s,%s,%s,%s,%s,%s,%s)
                """,
                (None, wallet_address, amount_for_db, "pending", identity["user_addr"], "wallet", wallet_address),
            )
            legacy.commit_database()
        except Exception:
            legacy.rollback_database()
            return jsonify({"code": 500, "msg": "提现申请创建失败"}), 500
    return jsonify({
        "code": 200,
        "msg": "提现申请已提交",
        "data": {
            "user_id": None,
            "node_address": identity["user_addr"],
            "wallet_address": wallet_address,
            "withdrawal_channel": "wallet",
            "withdrawal_account": wallet_address,
            "amount": amount_for_db,
            "status": "pending",
        },
    })


@bp.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    legacy = legacy_server()
    return jsonify({"code": 200, "data": legacy.build_leaderboard(legacy.select_node_rows())})


@bp.route("/api/invite_tree", methods=["GET"])
def invite_tree():
    legacy = legacy_server()
    return jsonify({"code": 200, "data": legacy.build_invite_tree(legacy.select_node_rows())})
