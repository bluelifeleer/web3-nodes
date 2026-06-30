import json
import urllib.parse

from flask import Blueprint, g, jsonify, request


bp = Blueprint("files_api", __name__)


def legacy_server():
    import server_main

    return server_main


@bp.route("/api/user/files", methods=["POST"])
def user_file_upload():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        uploaded_file = request.files.get("file")
        visibility = legacy.normalize_visibility(request.form.get("visibility", "public"))
        access_token = legacy.create_access_token(visibility)
        if not uploaded_file:
            return jsonify({"code": 400, "msg": "缺少上传文件"}), 400

        file_data = uploaded_file.read()
        if not file_data:
            return jsonify({"code": 400, "msg": "上传文件为空"}), 400
        if len(file_data) > legacy.MAX_UPLOAD_BYTES:
            return jsonify({"code": 413, "msg": "文件超过上传大小限制"}), 413

        user_row = getattr(g, "current_user_row", None) or ()
        owner_user_id = user_row[0] if len(user_row) > 0 else g.current_user.get("user_id")
        owner_wallet_address = user_row[3] if len(user_row) > 3 and user_row[3] else ""
        username = user_row[1] if len(user_row) > 1 and user_row[1] else ""
        upload_user = owner_wallet_address or username
        real_file_hash = legacy.get_file_hash(file_data)
        request_id = legacy.secrets.token_hex(8)
        legacy.current_cursor().execute(
            f"""
            select {legacy.USER_FILE_SELECT_PROJECTION}
            from file_chain_record
            where file_hash=%s and deleted_at is null
            order by create_time desc
            limit 1
            """,
            (real_file_hash,),
        )
        duplicate_row = legacy.current_cursor().fetchone()
        if duplicate_row:
            duplicate_response = {
                "code": 409,
                "msg": "文件已存在，当前版本暂不支持重复上传",
            }
            if duplicate_row[12] == owner_user_id:
                duplicate_response["data"] = legacy.format_user_file_record(duplicate_row)
            return jsonify(duplicate_response), 409

        try:
            encrypt_data = legacy.aes_encrypt(file_data)
        except RuntimeError as exc:
            return jsonify({"code": 500, "msg": str(exc)}), 500
        shards = legacy.file_shard(encrypt_data)
        shard_num = len(shards)

        try:
            assign_nodes = legacy.select_storage_node_candidates(legacy.COPY_NUM)
            if not assign_nodes:
                return jsonify({"code": 503, "msg": "暂无可用用户节点，请先启动节点客户端后再上传"}), 503
            assign_nodes = legacy.call_persist_file_to_storage_nodes(
                real_file_hash,
                encrypt_data,
                assign_nodes,
                request_id=request_id,
            )
        except Exception as exc:
            return jsonify({"code": 503, "msg": str(exc) or "用户节点存储失败"}), 503

        cid, ipfs_backup_status, ipfs_backup_error = legacy.backup_to_ipfs(encrypt_data)
        if ipfs_backup_status == "ok":
            legacy.insert_storage_audit_log(
                "fallback.ipfs.write.success",
                file_hash=real_file_hash,
                request_id=request_id,
                status="ok",
                message="IPFS backup stored",
                metadata={"ipfs_cid": cid},
            )
        else:
            legacy.insert_storage_audit_log(
                "fallback.ipfs.write.failed",
                file_hash=real_file_hash,
                request_id=request_id,
                status="failed",
                message=ipfs_backup_error or "IPFS backup failed",
            )
        with legacy.DatabaseTransaction():
            try:
                legacy.current_cursor().execute(
                    """
                    insert into file_chain_record(file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,visibility,access_token,owner_user_id,owner_wallet_address)
                    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        uploaded_file.filename,
                        real_file_hash,
                        cid,
                        round(len(file_data) / 1024 / 1024, 3),
                        shard_num,
                        upload_user,
                        json.dumps(assign_nodes, ensure_ascii=False),
                        visibility,
                        access_token,
                        owner_user_id,
                        owner_wallet_address,
                    ),
                )
                shard_records = legacy.insert_file_shard_records(real_file_hash, encrypt_data, assign_nodes)
                legacy.insert_storage_audit_log(
                    "upload.sharded",
                    file_hash=real_file_hash,
                    request_id=request_id,
                    status="ok",
                    message="encrypted shards recorded",
                    metadata={"shard_count": len(shard_records), "nodes": assign_nodes},
                )

                for node in assign_nodes:
                    legacy.current_cursor().execute(
                        "update node_power set disk_used=disk_used+0.1 where user_address=%s",
                        (node,),
                    )
                legacy.commit_database()
            except Exception as exc:
                legacy.rollback_database()
                if legacy.duplicate_database_error(exc):
                    return jsonify({
                        "code": 409,
                        "msg": "文件已存在，当前版本暂不支持重复上传",
                    }), 409
                return jsonify({"code": 500, "msg": "文件记录保存失败"}), 500

        return jsonify({
            "code": 200,
            "msg": "文件已写入用户节点，IPFS备份完成" if ipfs_backup_status == "ok" else "文件已写入用户节点，IPFS备份待重试",
            "data": {
                "file_hash": real_file_hash,
                "ipfs_cid": cid,
                "ipfs_backup_status": ipfs_backup_status,
                "ipfs_backup_error": ipfs_backup_error,
                "shard_count": shard_num,
                "storage_nodes": assign_nodes,
                "visibility": visibility,
                "access_token": access_token,
                "owner_user_id": owner_user_id,
                "owner_wallet_address": owner_wallet_address,
                "download_url": "",
                "share_required": True,
            },
        })

    return view()


@bp.route("/api/user/files", methods=["GET"])
def user_file_list():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        owner_user_id = g.current_user.get("user_id")
        legacy.current_cursor().execute(
            f"""
            select {legacy.USER_FILE_SELECT_PROJECTION}
            from file_chain_record
            where owner_user_id=%s and deleted_at is null
            order by create_time desc
            """,
            (owner_user_id,),
        )
        return jsonify({"code": 200, "data": legacy.format_user_file_records(legacy.current_cursor().fetchall())})

    return view()


@bp.route("/api/user/files/<file_hash>", methods=["GET"])
def user_file_detail(file_hash):
    legacy = legacy_server()

    @legacy.require_user
    def view():
        if not legacy.validate_file_hash(file_hash):
            return jsonify({"code": 400, "msg": "file_hash 格式无效"}), 400
        owner_user_id = g.current_user.get("user_id")
        legacy.current_cursor().execute(
            f"""
            select {legacy.USER_FILE_SELECT_PROJECTION}
            from file_chain_record
            where owner_user_id=%s and file_hash=%s and deleted_at is null
            """,
            (owner_user_id, file_hash),
        )
        row = legacy.current_cursor().fetchone()
        if not row:
            return jsonify({"code": 404, "msg": "文件不存在"}), 404
        return jsonify({"code": 200, "data": legacy.format_user_file_record(row)})

    return view()


@bp.route("/api/user/files/<file_hash>", methods=["DELETE"])
def user_file_delete(file_hash):
    legacy = legacy_server()

    @legacy.require_user
    def view():
        if not legacy.validate_file_hash(file_hash):
            return jsonify({"code": 400, "msg": "file_hash 格式无效"}), 400
        owner_user_id = g.current_user.get("user_id")
        active_cursor = legacy.current_cursor()
        active_cursor.execute(
            "update file_chain_record set deleted_at=%s where owner_user_id=%s and file_hash=%s and deleted_at is null",
            (legacy.datetime.now(), owner_user_id, file_hash),
        )
        legacy.commit_database()
        if getattr(active_cursor, "rowcount", None) == 0:
            return jsonify({"code": 404, "msg": "文件不存在"}), 404
        return jsonify({"code": 200, "msg": "文件记录已删除"})

    return view()


@bp.route("/api/user/files/<file_hash>/shares", methods=["POST"])
def user_file_share_create(file_hash):
    legacy = legacy_server()

    @legacy.require_user
    def view():
        if not legacy.validate_file_hash(file_hash):
            return jsonify({"code": 400, "msg": "file_hash 格式无效"}), 400
        owner_user_id = g.current_user.get("user_id")
        legacy.current_cursor().execute(
            """
            select file_hash,owner_user_id
            from file_chain_record
            where file_hash=%s and owner_user_id=%s and deleted_at is null
            limit 1
            """,
            (file_hash, owner_user_id),
        )
        if not legacy.current_cursor().fetchone():
            return jsonify({"code": 404, "msg": "文件不存在"}), 404

        data = legacy.get_json_body()
        visibility = legacy.normalize_visibility(data.get("visibility", "public"))
        status = legacy.normalize_share_status(data.get("status", "active"))
        if status is None:
            return jsonify({"code": 400, "msg": "status 格式无效"}), 400
        expires_at, expiry_error = legacy.parse_share_expires_at(data.get("expires_at"))
        if expiry_error:
            return jsonify({"code": 400, "msg": expiry_error}), 400
        max_downloads, max_error = legacy.parse_non_negative_int(data.get("max_downloads", 0), "max_downloads")
        if max_error:
            return jsonify({"code": 400, "msg": max_error}), 400
        extract_code = str(data.get("extract_code") or "").strip()
        extract_code_hash = legacy.shares.hash_extract_code(extract_code) if extract_code else ""
        share_code, create_error = legacy.insert_file_share_with_retry(
            file_hash,
            owner_user_id,
            visibility,
            extract_code_hash,
            expires_at,
            max_downloads,
            status,
        )
        if create_error:
            return jsonify({"code": 500, "msg": create_error}), 500
        legacy.commit_database()
        share_url = f"/s/{urllib.parse.quote(share_code)}"
        share_url_with_extract_code = (
            f"{share_url}?extract_code={urllib.parse.quote(extract_code)}"
            if extract_code else share_url
        )
        return jsonify({
            "code": 200,
            "msg": "分享已创建",
            "data": {
                "share_code": share_code,
                "file_hash": file_hash,
                "owner_user_id": owner_user_id,
                "visibility": visibility,
                "extract_code_required": bool(extract_code_hash),
                "expires_at": str(expires_at) if expires_at else "",
                "max_downloads": max_downloads,
                "download_count": 0,
                "status": status,
                "share_url": share_url,
                "share_url_with_extract_code": share_url_with_extract_code,
            },
        })

    return view()


@bp.route("/api/user/shares", methods=["GET"])
def user_share_list():
    legacy = legacy_server()

    @legacy.require_user
    def view():
        owner_user_id = g.current_user.get("user_id")
        legacy.current_cursor().execute(
            f"""
            select {legacy.shares.SHARE_SELECT_PROJECTION}
            from file_share s
            join file_chain_record f on f.file_hash=s.file_hash and f.deleted_at is null
            where s.owner_user_id=%s and s.status<>'deleted'
            order by s.created_at desc
            """,
            (owner_user_id,),
        )
        return jsonify({
            "code": 200,
            "data": [legacy.shares.format_share_row(row) for row in legacy.current_cursor().fetchall()],
        })

    return view()


@bp.route("/api/user/shares/<share_code>", methods=["PATCH"])
def user_share_update(share_code):
    legacy = legacy_server()

    @legacy.require_user
    def view():
        if not legacy.validate_share_code(share_code):
            return jsonify({"code": 404, "msg": "分享不存在"}), 404
        owner_user_id = g.current_user.get("user_id")
        legacy.current_cursor().execute(
            "select share_code from file_share where share_code=%s and owner_user_id=%s and status<>'deleted'",
            (share_code, owner_user_id),
        )
        if not legacy.current_cursor().fetchone():
            return jsonify({"code": 404, "msg": "分享不存在"}), 404

        data = legacy.get_json_body()
        updates = []
        params = []
        if "extract_code" in data:
            extract_code = str(data.get("extract_code") or "").strip()
            updates.append("extract_code_hash=%s")
            params.append(legacy.shares.hash_extract_code(extract_code) if extract_code else "")
        if "expires_at" in data:
            expires_at, expiry_error = legacy.parse_share_expires_at(data.get("expires_at"))
            if expiry_error:
                return jsonify({"code": 400, "msg": expiry_error}), 400
            updates.append("expires_at=%s")
            params.append(expires_at)
        if "max_downloads" in data:
            max_downloads, max_error = legacy.parse_non_negative_int(data.get("max_downloads"), "max_downloads")
            if max_error:
                return jsonify({"code": 400, "msg": max_error}), 400
            updates.append("max_downloads=%s")
            params.append(max_downloads)
        if "status" in data:
            status = legacy.normalize_share_status(data.get("status"))
            if status is None:
                return jsonify({"code": 400, "msg": "status 格式无效"}), 400
            updates.append("status=%s")
            params.append(status)
        if "visibility" in data:
            updates.append("visibility=%s")
            params.append(legacy.normalize_visibility(data.get("visibility")))
        if not updates:
            return jsonify({"code": 400, "msg": "没有可更新的分享字段"}), 400

        params.extend([share_code, owner_user_id])
        legacy.current_cursor().execute(
            f"update file_share set {','.join(updates)} where share_code=%s and owner_user_id=%s and status<>'deleted'",
            tuple(params),
        )
        if getattr(legacy.current_cursor(), "rowcount", None) == 0:
            legacy.rollback_database()
            return jsonify({"code": 404, "msg": "分享不存在"}), 404
        legacy.commit_database()
        return jsonify({"code": 200, "msg": "分享已更新"})

    return view()


@bp.route("/api/user/shares/<share_code>", methods=["DELETE"])
def user_share_delete(share_code):
    legacy = legacy_server()

    @legacy.require_user
    def view():
        if not legacy.validate_share_code(share_code):
            return jsonify({"code": 404, "msg": "分享不存在"}), 404
        owner_user_id = g.current_user.get("user_id")
        active_cursor = legacy.current_cursor()
        active_cursor.execute(
            "update file_share set status=%s where share_code=%s and owner_user_id=%s and status<>'deleted'",
            ("deleted", share_code, owner_user_id),
        )
        legacy.commit_database()
        if getattr(active_cursor, "rowcount", None) == 0:
            return jsonify({"code": 404, "msg": "分享不存在"}), 404
        return jsonify({"code": 200, "msg": "分享已删除"})

    return view()


@bp.route("/api/share/<share_code>", methods=["GET"])
def public_share_detail(share_code):
    legacy = legacy_server()
    if not legacy.validate_share_code(share_code):
        return jsonify({"code": 404, "msg": "分享不存在"}), 404
    row = legacy.select_share_row(share_code)
    if not row:
        return jsonify({"code": 404, "msg": "分享不存在"}), 404
    share = legacy.shares.format_share_row(row, include_extract_code_hash=True)
    allowed, status_code, message = legacy.shares.validate_share_access(share)
    if not allowed:
        return jsonify({"code": status_code, "msg": message}), status_code
    return jsonify({"code": 200, "data": legacy.shares.format_public_share(share)})


@bp.route("/api/share/<share_code>/verify", methods=["POST"])
def public_share_verify(share_code):
    legacy = legacy_server()
    if not legacy.validate_share_code(share_code):
        return jsonify({"code": 404, "msg": "分享不存在"}), 404
    row = legacy.select_share_row(share_code)
    if not row:
        return jsonify({"code": 404, "msg": "分享不存在"}), 404
    share = legacy.shares.format_share_row(row, include_extract_code_hash=True)
    allowed, status_code, message = legacy.shares.validate_share_access(share)
    if not allowed:
        return jsonify({"code": status_code, "msg": message}), status_code
    code_hash = share.get("extract_code_hash") or ""
    if code_hash and not legacy.shares.verify_extract_code(legacy.get_json_body().get("extract_code", ""), code_hash):
        return jsonify({"code": 403, "msg": "提取码错误", "verified": False}), 403
    return jsonify({"code": 200, "verified": True})


@bp.route("/api/share/<share_code>/download", methods=["GET", "POST"])
def public_share_download(share_code):
    legacy = legacy_server()
    if not legacy.validate_share_code(share_code):
        return jsonify({"code": 404, "msg": "分享不存在"}), 404
    row = legacy.select_share_download_row(share_code)
    if not row:
        return jsonify({"code": 404, "msg": "分享不存在"}), 404
    share = legacy.format_share_download_row(row)
    allowed, status_code, message = legacy.shares.validate_share_access(share)
    if not allowed:
        return jsonify({"code": status_code, "msg": message}), status_code
    code_hash = share.get("extract_code_hash") or ""
    if code_hash and not legacy.shares.verify_extract_code(legacy.request_extract_code(), code_hash):
        return jsonify({"code": 403, "msg": "提取码错误"}), 403

    downloader_user_id = legacy.optional_downloader_user_id()
    request_id = legacy.secrets.token_hex(8)
    encrypted = legacy.read_verified_encrypted_file(
        share["file_hash"],
        share["stored_nodes"],
        share["ipfs_cid"],
        request_id=request_id,
    )
    if encrypted is None:
        return jsonify({"code": 502, "msg": "用户节点副本不可用，且暂无可用兜底备份"}), 502
    try:
        plain = legacy.decrypt_and_verify_file(share["file_hash"], encrypted)
    except RuntimeError as exc:
        return jsonify({"code": 500, "msg": str(exc)}), 500

    with legacy.DatabaseTransaction():
        try:
            recorded = legacy.record_share_download_success(
                share,
                downloader_user_id,
                request.remote_addr or "",
            )
            if not recorded:
                legacy.rollback_database()
                return jsonify({"code": 409, "msg": "分享状态已变化，请重试"}), 409
            legacy.commit_database()
        except Exception:
            legacy.rollback_database()
            return jsonify({"code": 500, "msg": "下载记录保存失败"}), 500

    filename = share["file_name"] or f"{share['file_hash']}.bin"
    response = legacy.app.response_class(plain, mimetype="application/octet-stream")
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"
    return response
