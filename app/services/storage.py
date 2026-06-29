import hashlib
import os
import re
import secrets
import sys
from pathlib import Path


CHUNK_TMP_DIR = "./chunk_tmp"
NODE_STORAGE_DIR = os.getenv("NODE_STORAGE_DIR", "./node_storage")
SAFE_FILE_HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")
SHARD_SIZE = 1024 * 1024


def validate_file_hash(file_hash):
    return isinstance(file_hash, str) and bool(SAFE_FILE_HASH_RE.fullmatch(file_hash))


def server_main_module():
    return sys.modules.get("server_main")


def configured_chunk_tmp_dir():
    module = server_main_module()
    return getattr(module, "CHUNK_TMP_DIR", CHUNK_TMP_DIR)


def configured_node_storage_dir():
    module = server_main_module()
    return getattr(module, "NODE_STORAGE_DIR", NODE_STORAGE_DIR)


def get_chunk_dir(file_hash):
    if not validate_file_hash(file_hash):
        return None
    base_dir = Path(configured_chunk_tmp_dir()).resolve()
    chunk_dir = (base_dir / file_hash).resolve()
    if base_dir != chunk_dir and base_dir not in chunk_dir.parents:
        return None
    return chunk_dir


def normalize_visibility(value):
    return "private" if value == "private" else "public"


def create_access_token(visibility):
    return secrets.token_urlsafe(24) if normalize_visibility(visibility) == "private" else ""


def normalize_storage_node_name(node):
    raw = str(node or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", raw):
        return raw
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def storage_node_file_path(file_hash, node):
    if not validate_file_hash(file_hash):
        return None
    node_name = normalize_storage_node_name(node)
    if not node_name:
        return None
    base_dir = Path(configured_node_storage_dir()).resolve()
    node_dir = (base_dir / node_name / file_hash[:2]).resolve()
    if base_dir != node_dir and base_dir not in node_dir.parents:
        return None
    return node_dir / f"{file_hash}.bin"


def default_file_shard(data):
    module = server_main_module()
    shard_size = int(getattr(module, "SHARD_SIZE", SHARD_SIZE) or SHARD_SIZE)
    return [data[index:index + shard_size] for index in range(0, len(data), shard_size)]


def file_shards_for_manifest(data):
    module = server_main_module()
    shard_func = getattr(module, "file_shard", None)
    if callable(shard_func):
        return shard_func(data)
    return default_file_shard(data)


def build_encrypted_shard_manifest(file_hash, encrypted_data):
    encrypted_hash = hashlib.sha256(encrypted_data).hexdigest()
    shards = []
    for index, shard_bytes in enumerate(file_shards_for_manifest(encrypted_data)):
        shards.append({
            "file_hash": file_hash,
            "encrypted_hash": encrypted_hash,
            "chunk_index": index,
            "chunk_total": 0,
            "chunk_hash": hashlib.sha256(shard_bytes).hexdigest(),
            "chunk_size": len(shard_bytes),
            "chunk_bytes": shard_bytes,
        })
    chunk_total = len(shards)
    for shard in shards:
        shard["chunk_total"] = chunk_total
    return {
        "file_hash": file_hash,
        "encrypted_hash": encrypted_hash,
        "shards": shards,
    }
