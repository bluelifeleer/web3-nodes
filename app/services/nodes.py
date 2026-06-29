from datetime import datetime


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
        "storage_path": item[9] if len(item) > 9 and item[9] else "",
        "storage_status": item[10] if len(item) > 10 and item[10] else "unknown",
        "storage_error": item[11] if len(item) > 11 and item[11] else "",
        "storage_total_gb": item[12] if len(item) > 12 and item[12] is not None else 0,
        "storage_used_gb": item[13] if len(item) > 13 and item[13] is not None else item[3] or 0,
        "storage_free_gb": item[14] if len(item) > 14 and item[14] is not None else 0,
        "storage_quota_gb": item[15] if len(item) > 15 and item[15] is not None else 0,
        "storage_available_gb": item[16] if len(item) > 16 and item[16] is not None else 0,
        "storage_api_url": item[17] if len(item) > 17 and item[17] else "",
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
