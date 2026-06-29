import json


USER_FILE_SELECT_PROJECTION = (
    "id,file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,"
    "stored_nodes,create_time,visibility,access_token,deleted_at,"
    "owner_user_id,owner_wallet_address,download_count,last_download_at"
)


def normalize_visibility(value):
    return "private" if value == "private" else "public"


def parse_stored_nodes(value):
    try:
        parsed = json.loads(value) if value else []
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def format_user_file_record(row):
    visibility = normalize_visibility(row[9] if len(row) > 9 else "public")
    access_token = row[10] if len(row) > 10 and row[10] else ""
    file_hash = row[2]
    return {
        "id": row[0],
        "file_name": row[1],
        "file_hash": file_hash,
        "ipfs_cid": row[3],
        "size": row[4],
        "shard": row[5],
        "uploader": row[6],
        "nodes": parse_stored_nodes(row[7]),
        "created_at": str(row[8]),
        "time": str(row[8]),
        "visibility": visibility,
        "access_token": access_token,
        "deleted_at": str(row[11]) if len(row) > 11 and row[11] else "",
        "owner_user_id": row[12] if len(row) > 12 else None,
        "owner_wallet_address": row[13] if len(row) > 13 and row[13] else "",
        "download_count": row[14] if len(row) > 14 and row[14] is not None else 0,
        "last_download_at": str(row[15]) if len(row) > 15 and row[15] else "",
        "download_url": "",
    }
