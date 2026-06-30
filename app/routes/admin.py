import csv
import io
import json

from flask import Blueprint, Response, jsonify, request


bp = Blueprint("admin_api", __name__)


def legacy_server():
    import server_main

    return server_main


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
    legacy = legacy_server()
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
    legacy.current_cursor().execute(sql, tuple(params))
    return [format_storage_audit_row(row) for row in legacy.current_cursor().fetchall()]


@bp.route("/api/admin/audit/storage", methods=["GET"])
def admin_storage_audit_list():
    rows = select_storage_audit_rows(request.args)
    return jsonify({"code": 200, "data": rows})


@bp.route("/api/admin/audit/storage/export", methods=["GET"])
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
        response = Response(output.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=storage-audit.csv"
        return response
    return jsonify({"code": 200, "data": rows})


@bp.route("/api/admin/users", methods=["GET"])
def admin_user_list():
    legacy = legacy_server()
    legacy.current_cursor().execute(
        """
        select id,username,password_hash,wallet_address,status
        from app_user
        order by id desc
        """
    )
    return jsonify({"code": 200, "data": [legacy.format_user(row) for row in legacy.current_cursor().fetchall()]})


@bp.route("/api/admin/shares", methods=["GET"])
def admin_share_list():
    legacy = legacy_server()
    legacy.current_cursor().execute(f"""
    select {legacy.shares.SHARE_SELECT_PROJECTION}
    from file_share s
    join file_chain_record f on f.file_hash=s.file_hash and f.deleted_at is null
    order by s.created_at desc
    """)
    return jsonify({
        "code": 200,
        "data": [legacy.shares.format_share_row(row) for row in legacy.current_cursor().fetchall()],
    })


@bp.route("/api/admin/downloads", methods=["GET"])
def admin_download_list():
    legacy = legacy_server()
    legacy.current_cursor().execute(
        """
        select id,share_code,file_hash,downloader_ip,downloader_user_id,node_address,file_size,created_at
        from file_download_log
        order by created_at desc,id desc
        """
    )
    downloads = []
    for row in legacy.current_cursor().fetchall():
        downloads.append({
            "id": row[0],
            "share_code": row[1] or "",
            "file_hash": row[2] or "",
            "downloader_ip": row[3] or "",
            "downloader_user_id": row[4],
            "node_address": row[5] or "",
            "file_size": float(row[6] or 0),
            "created_at": str(row[7]) if len(row) > 7 and row[7] else "",
        })
    return jsonify({"code": 200, "data": downloads})


@bp.route("/api/admin/points", methods=["GET"])
def admin_point_list():
    legacy = legacy_server()
    legacy.current_cursor().execute(
        """
        select id,user_id,wallet_address,point_type,amount,source_type,source_id,remark,created_at
        from point_ledger
        order by created_at desc,id desc
        """
    )
    return jsonify({
        "code": 200,
        "data": [legacy.format_point_ledger_row(row) for row in legacy.current_cursor().fetchall()],
    })
