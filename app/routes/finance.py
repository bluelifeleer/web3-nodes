from datetime import datetime

from flask import Blueprint, g, jsonify


bp = Blueprint("finance_api", __name__)


def legacy_server():
    import server_main

    return server_main


@bp.route("/api/user/earnings", methods=["GET"])
def user_earnings():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        summary = legacy.calculate_user_earnings(g.current_user.get("user_id"))
        return jsonify({"code": 200, "data": summary})

    return view()


@bp.route("/api/user/points", methods=["GET"])
def user_points():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        user_id = g.current_user.get("user_id")
        legacy.current_cursor().execute(
            """
            select id,user_id,wallet_address,point_type,amount,source_type,source_id,remark,created_at
            from point_ledger
            where user_id=%s
            order by created_at desc,id desc
            """,
            (user_id,),
        )
        rows = legacy.current_cursor().fetchall()
        total_points = sum(float(row[4] or 0) for row in rows)
        return jsonify({
            "code": 200,
            "data": {
                "total_points": total_points,
                "total_earnings": legacy.points.points_to_earning_units(total_points),
                "items": [legacy.format_point_ledger_row(row) for row in rows],
            },
        })

    return view()


@bp.route("/api/user/withdrawals", methods=["GET"])
def user_withdrawal_list():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        user_id = g.current_user.get("user_id")
        legacy.current_cursor().execute(
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
            "code": 200,
            "data": [legacy.format_withdrawal_row(row) for row in legacy.current_cursor().fetchall()],
        })

    return view()


@bp.route("/api/user/withdrawals", methods=["POST"])
def user_withdrawal_create():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        data = legacy.get_json_body()
        amount, message = legacy.withdrawals.parse_withdrawal_amount(data.get("amount"))
        if amount is None:
            return jsonify({"code": 400, "msg": message}), 400
        amount_for_db = legacy.withdrawals.format_withdrawal_amount(amount)
        user_row = getattr(g, "current_user_row", None) or ()
        user_id = user_row[0] if len(user_row) > 0 else g.current_user.get("user_id")
        wallet_address = user_row[3] if len(user_row) > 3 and user_row[3] else ""
        if not wallet_address:
            return jsonify({"code": 400, "msg": "请先绑定钱包地址"}), 400

        with legacy.DatabaseTransaction():
            try:
                if not legacy.lock_active_user_for_update(user_id):
                    legacy.rollback_database()
                    return jsonify({"code": 401, "msg": "用户不存在或已停用"}), 401
                summary = legacy.calculate_user_earnings(user_id, include_decimal=True)
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
                    (user_id, wallet_address, amount_for_db, "pending", "", "wallet", wallet_address),
                )
                legacy.commit_database()
            except Exception:
                legacy.rollback_database()
                return jsonify({"code": 500, "msg": "提现申请创建失败"}), 500
        return jsonify({
            "code": 200,
            "msg": "提现申请已提交",
            "data": {
                "user_id": user_id,
                "wallet_address": wallet_address,
                "node_address": "",
                "withdrawal_channel": "wallet",
                "withdrawal_account": wallet_address,
                "amount": amount_for_db,
                "status": "pending",
            },
        })

    return view()


@bp.route("/api/admin/withdrawals", methods=["GET"])
def admin_withdrawal_list():
    legacy = legacy_server()
    legacy.current_cursor().execute(
        """
        select id,user_id,wallet_address,amount,status,admin_note,created_at,reviewed_at,
        node_address,withdrawal_channel,withdrawal_account
        from withdrawal_request
        order by created_at desc,id desc
        """
    )
    return jsonify({
        "code": 200,
        "data": [legacy.format_withdrawal_row(row) for row in legacy.current_cursor().fetchall()],
    })


@bp.route("/api/admin/withdrawals/<int:withdrawal_id>/review", methods=["POST"])
def admin_withdrawal_review(withdrawal_id):
    legacy = legacy_server()
    data = legacy.get_json_body()
    status = str(data.get("status") or "").strip().lower()
    ok, message = legacy.withdrawals.validate_review_status(status)
    if not ok:
        return jsonify({"code": 400, "msg": message}), 400
    admin_note = str(data.get("admin_note") or "")[:255]
    with legacy.DatabaseTransaction():
        try:
            active_cursor = legacy.current_cursor()
            active_cursor.execute(
                "select id,status from withdrawal_request where id=%s for update",
                (withdrawal_id,),
            )
            row = active_cursor.fetchone()
            if not row:
                legacy.rollback_database()
                return jsonify({"code": 404, "msg": "提现申请不存在"}), 404
            transition_ok, transition_message = legacy.withdrawals.validate_status_transition(row[1], status)
            if not transition_ok:
                legacy.rollback_database()
                return jsonify({"code": 400, "msg": transition_message}), 400
            active_cursor.execute(
                """
                update withdrawal_request
                set status=%s,admin_note=%s,reviewed_at=%s
                where id=%s
                """,
                (status, admin_note, datetime.now(), withdrawal_id),
            )
            if getattr(active_cursor, "rowcount", None) == 0:
                legacy.rollback_database()
                return jsonify({"code": 404, "msg": "提现申请不存在"}), 404
            legacy.commit_database()
        except Exception:
            legacy.rollback_database()
            return jsonify({"code": 500, "msg": "提现审核更新失败"}), 500
    return jsonify({"code": 200, "msg": "提现审核已更新", "data": {"id": withdrawal_id, "status": status}})
