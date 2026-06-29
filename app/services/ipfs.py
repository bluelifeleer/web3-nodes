import os
import subprocess
import sys
import urllib.parse

import requests


DEFAULT_IPFS_API_ADDR = "/ip4/127.0.0.1/tcp/5001"


def normalize_ipfs_api_addr(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("/"):
        return raw
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme in ("http", "https") and parsed.hostname and parsed.port:
        host = parsed.hostname
        if ":" in host:
            return f"/ip6/{host}/tcp/{parsed.port}"
        return f"/ip4/{host}/tcp/{parsed.port}"
    return raw


def get_ipfs_api_addr():
    for key in ("IPFS_API_ADDR", "IPFS_API_MULTIADDR", "IPFS_API_URL"):
        configured = normalize_ipfs_api_addr(os.getenv(key, ""))
        if configured:
            return configured
    try:
        configured = subprocess.check_output(
            ["ipfs", "config", "Addresses.API"],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).strip()
        configured = normalize_ipfs_api_addr(configured)
        if configured:
            return configured
    except Exception:
        pass
    return DEFAULT_IPFS_API_ADDR


def ipfs_api_base_url(api_addr):
    raw = normalize_ipfs_api_addr(api_addr) or DEFAULT_IPFS_API_ADDR
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/") + "/api/v0"
    parts = [part for part in raw.split("/") if part]
    host = "127.0.0.1"
    port = "5001"
    for index, part in enumerate(parts):
        if part in ("ip4", "ip6", "dns", "dns4", "dns6") and index + 1 < len(parts):
            host = parts[index + 1]
        if part == "tcp" and index + 1 < len(parts):
            port = parts[index + 1]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/api/v0"


class HttpIPFSClient:
    def __init__(self, api_addr=None, timeout=30):
        self.api_addr = normalize_ipfs_api_addr(api_addr) or get_ipfs_api_addr()
        self.base_url = ipfs_api_base_url(self.api_addr)
        self.timeout = timeout

    def _post(self, endpoint, **kwargs):
        response = requests_module().post(f"{self.base_url}/{endpoint.lstrip('/')}", timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response

    def id(self):
        return self._post("id").json()

    def repo_stat(self):
        return self._post("repo/stat").json()

    def add_bytes(self, data):
        response = self._post("add", files={"file": ("file", bytes(data))})
        payload = response.json()
        return payload.get("Hash") or payload.get("Cid") or payload.get("Name", "")

    def cat(self, cid):
        return self._post("cat", params={"arg": cid}).content

    def close(self):
        return None


def requests_module():
    server_main = sys.modules.get("server_main")
    patched = getattr(server_main, "requests", None)
    if patched is not None and hasattr(patched, "post"):
        return patched
    return requests


def ipfshttpclient_module():
    server_main = sys.modules.get("server_main")
    patched = getattr(server_main, "ipfshttpclient", None)
    if patched is not None:
        return patched
    return globals().get("ipfshttpclient")


def get_ipfs_client():
    client_module = ipfshttpclient_module()
    if client_module is None:
        try:
            import ipfshttpclient as client_module
            globals()["ipfshttpclient"] = client_module
        except Exception:
            return HttpIPFSClient(get_ipfs_api_addr())
    api_addr = get_ipfs_api_addr()
    try:
        return client_module.connect(api_addr)
    except Exception as exc:
        if "Unsupported daemon version" in str(exc):
            return HttpIPFSClient(api_addr)
        raise


def read_ipfs_status(client_factory=get_ipfs_client):
    try:
        client = client_factory()
        try:
            identity = client.id()
            repo = client.repo_stat()
        finally:
            if hasattr(client, "close"):
                client.close()
        return {
            "online": True,
            "peer_id": identity.get("ID", ""),
            "addresses": identity.get("Addresses", []),
            "repo_size": repo.get("RepoSize", 0),
            "storage_max": repo.get("StorageMax", 0),
            "num_objects": repo.get("NumObjects", 0),
            "error": "",
        }
    except Exception as exc:
        return {
            "online": False,
            "peer_id": "",
            "addresses": [],
            "repo_size": 0,
            "storage_max": 0,
            "num_objects": 0,
            "error": str(exc),
        }
