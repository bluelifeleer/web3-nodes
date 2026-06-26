import base64
import hashlib
import hmac
import json
import secrets
import time


SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120000,
    )
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password, password_hash):
    if not isinstance(password_hash, str):
        return False
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except (AttributeError, ValueError):
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(actual, expected)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data):
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(payload, secret, ttl=SESSION_TTL_SECONDS):
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64(raw)
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_b64(signature)}"


def verify_session_token(token, secret):
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64(
            hmac.new(
                secret.encode("utf-8"),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_unb64(encoded))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def build_wallet_message(nonce, purpose):
    return (
        f"Web3 Nodes {purpose}\n"
        f"Nonce: {nonce}\n"
        "This signature expires soon and does not transfer assets."
    )


def normalize_wallet_address(address):
    return (address or "").strip().lower()


def recover_wallet_address(message, signature):
    from eth_account import Account
    from eth_account.messages import encode_defunct

    return normalize_wallet_address(
        Account.recover_message(encode_defunct(text=message), signature=signature)
    )
