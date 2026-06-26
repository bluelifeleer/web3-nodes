import hashlib
import secrets
from datetime import UTC, datetime, timezone


SHARE_SELECT_PROJECTION = (
    "s.share_code,s.file_hash,s.owner_user_id,s.visibility,s.extract_code_hash,"
    "s.expires_at,s.max_downloads,s.download_count,s.status,s.created_at,"
    "f.file_name,f.file_size"
)


def create_share_code():
    return secrets.token_urlsafe(12)[:16]


def hash_extract_code(code, salt=None):
    salt = salt or secrets.token_hex(16)
    normalized = str(code or "")
    digest = hashlib.sha256(f"{salt}:{normalized}".encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def verify_extract_code(code, code_hash):
    try:
        algorithm, salt, expected = str(code_hash or "").split("$", 2)
    except ValueError:
        return False
    if algorithm != "sha256" or not salt or not expected:
        return False
    actual = hash_extract_code(code, salt).rsplit("$", 1)[-1]
    return secrets.compare_digest(actual, expected)


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def _as_utc_naive(value):
    if value and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def validate_share_access(share):
    if not share or str(share.get("status") or "").lower() != "active":
        return False, 404, "分享不存在"
    expires_at = _as_utc_naive(parse_datetime(share.get("expires_at")))
    if expires_at and expires_at <= datetime.now(UTC).replace(tzinfo=None):
        return False, 410, "分享已过期"
    max_downloads = int(share.get("max_downloads") or 0)
    download_count = int(share.get("download_count") or 0)
    if max_downloads > 0 and download_count >= max_downloads:
        return False, 429, "下载次数已用完"
    return True, 200, "OK"


def format_share_row(row, include_extract_code_hash=False):
    share = {
        "share_code": row[0],
        "file_hash": row[1],
        "owner_user_id": row[2],
        "visibility": row[3] or "public",
        "extract_code_required": bool(row[4]),
        "expires_at": str(row[5]) if row[5] else "",
        "max_downloads": row[6] if row[6] is not None else 0,
        "download_count": row[7] if row[7] is not None else 0,
        "status": row[8] or "active",
        "created_at": str(row[9]) if len(row) > 9 and row[9] else "",
        "file_name": row[10] if len(row) > 10 and row[10] else "",
        "file_size": row[11] if len(row) > 11 and row[11] is not None else 0,
    }
    if include_extract_code_hash:
        share["extract_code_hash"] = row[4] or ""
    return share
