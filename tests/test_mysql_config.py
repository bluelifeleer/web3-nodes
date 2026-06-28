import importlib
import base64
import http.client
import io
import json
import os
import sys
import tempfile
import types
import unittest
import urllib.request
from pathlib import Path


ENV_KEYS = (
    "DB_ENGINE",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB_NAME",
    "ADMIN_API_TOKEN",
    "SESSION_SECRET",
    "MAX_UPLOAD_MB",
    "AES_KEY",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DB_NAME",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "WEB3_NODES_SKIP_DOTENV",
    "AMAP_WEB_KEY",
    "AMAP_SECURITY_JSCODE",
    "NODE_OPEN_MAP_WINDOW",
)


def load_server_main(**env):
    old_env = {key: os.environ.get(key) for key in ENV_KEYS}
    old_pymysql = sys.modules.get("pymysql")
    old_psycopg = sys.modules.get("psycopg")
    old_requests = sys.modules.get("requests")
    old_db = sys.modules.get("db")

    class FakeResponse:
        def json(self):
            return {
                "status": "success",
                "country": "中国",
                "regionName": "广东",
                "city": "深圳",
                "lat": 22.5431,
                "lon": 114.0579,
            }

    try:
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in env.items():
            os.environ[key] = value
        os.environ.setdefault("WEB3_NODES_SKIP_DOTENV", "1")
        sys.modules["pymysql"] = types.SimpleNamespace(connect=lambda **kwargs: None)
        sys.modules["psycopg"] = types.SimpleNamespace(connect=lambda **kwargs: None)
        sys.modules["requests"] = types.SimpleNamespace(
            get=lambda url, timeout: FakeResponse()
        )
        sys.modules.pop("server_main", None)
        sys.modules.pop("db", None)
        return importlib.import_module("server_main")
    finally:
        if old_db is None:
            sys.modules.pop("db", None)
        else:
            sys.modules["db"] = old_db
        if old_pymysql is None:
            sys.modules.pop("pymysql", None)
        else:
            sys.modules["pymysql"] = old_pymysql
        if old_psycopg is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = old_psycopg
        if old_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = old_requests
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class MysqlConfigTest(unittest.TestCase):
    def test_password_hash_verification_accepts_correct_password(self):
        auth = importlib.import_module("auth")

        password_hash = auth.hash_password("secret-pass")

        self.assertNotEqual(password_hash, "secret-pass")
        self.assertTrue(auth.verify_password("secret-pass", password_hash))
        self.assertFalse(auth.verify_password("wrong-pass", password_hash))

    def test_password_verification_rejects_corrupted_hashes(self):
        auth = importlib.import_module("auth")

        self.assertFalse(auth.verify_password("secret-pass", None))
        self.assertFalse(auth.verify_password("secret-pass", "not-a-valid-hash"))

    def test_session_token_round_trip(self):
        auth = importlib.import_module("auth")

        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "test-secret")
        payload = auth.verify_session_token(token, "test-secret")

        self.assertEqual(payload["user_id"], 7)
        self.assertEqual(payload["username"], "alice")

    def test_session_token_rejects_tampering_and_expiry(self):
        auth = importlib.import_module("auth")

        token = auth.create_session_token({"user_id": 7}, "test-secret")
        encoded, signature = token.split(".", 1)
        tampered = f"{encoded[:-1]}x.{signature}"
        expired = auth.create_session_token({"user_id": 7}, "test-secret", ttl=-1)

        self.assertIsNone(auth.verify_session_token(tampered, "test-secret"))
        self.assertIsNone(auth.verify_session_token(expired, "test-secret"))

    def test_extract_code_hash_accepts_correct_code_and_rejects_wrong_code(self):
        shares = importlib.import_module("shares")

        code_hash = shares.hash_extract_code("A1b2")

        self.assertNotIn("A1b2", code_hash)
        self.assertTrue(shares.verify_extract_code("A1b2", code_hash))
        self.assertFalse(shares.verify_extract_code("wrong", code_hash))

    def test_point_helpers_calculate_share_and_node_download_points(self):
        points = importlib.import_module("points")

        self.assertEqual(points.share_download_points(), 1)
        self.assertEqual(points.node_download_points(10), 1.0)
        self.assertEqual(points.points_to_earning_units(250), 2.5)

    def test_withdrawal_amount_validation(self):
        withdrawals = importlib.import_module("withdrawals")

        self.assertEqual(withdrawals.validate_withdrawal_amount(1), (True, "ok"))
        self.assertEqual(withdrawals.validate_withdrawal_amount(0), (False, "提现金额必须大于0"))
        self.assertEqual(withdrawals.validate_withdrawal_amount(float("nan")), (False, "提现金额格式错误"))
        self.assertEqual(withdrawals.validate_withdrawal_amount(float("inf")), (False, "提现金额格式错误"))
        self.assertEqual(withdrawals.validate_withdrawal_amount("1e-400"), (False, "提现金额不能小于0.000001"))

    def test_withdrawal_review_status_validation(self):
        withdrawals = importlib.import_module("withdrawals")

        self.assertEqual(withdrawals.validate_review_status("approved"), (True, "ok"))
        self.assertEqual(withdrawals.validate_review_status("unknown"), (False, "提现状态无效"))

    def test_withdrawal_status_transition_validation(self):
        withdrawals = importlib.import_module("withdrawals")

        self.assertEqual(withdrawals.validate_status_transition("pending", "approved"), (True, "ok"))
        self.assertEqual(withdrawals.validate_status_transition("approved", "paid"), (True, "ok"))
        self.assertEqual(withdrawals.validate_status_transition("paid", "rejected"), (False, "提现状态不可从 paid 变更为 rejected"))
        self.assertEqual(withdrawals.validate_status_transition("pending", "pending"), (False, "不能将提现审核为 pending"))

    def test_validate_share_access_rejects_expired_active_share(self):
        shares = importlib.import_module("shares")
        expired_share = {
            "status": "active",
            "expires_at": "2000-01-01T00:00:00",
            "max_downloads": 0,
            "download_count": 0,
        }

        result = shares.validate_share_access(expired_share)

        self.assertEqual(result, (False, 410, "分享已过期"))

    def test_validate_share_access_rejects_exhausted_active_share(self):
        shares = importlib.import_module("shares")
        exhausted_share = {
            "status": "active",
            "expires_at": None,
            "max_downloads": 3,
            "download_count": 3,
        }

        result = shares.validate_share_access(exhausted_share)

        self.assertEqual(result, (False, 429, "下载次数已用完"))

    def test_validate_share_access_treats_naive_expiry_as_server_local_time(self):
        shares = importlib.import_module("shares")
        datetime_module = importlib.import_module("datetime")
        expired_local_time = datetime_module.datetime.now() - datetime_module.timedelta(seconds=1)
        expired_share = {
            "status": "active",
            "expires_at": expired_local_time,
            "max_downloads": 0,
            "download_count": 0,
        }

        result = shares.validate_share_access(expired_share)

        self.assertEqual(result, (False, 410, "分享已过期"))

    def test_parse_share_expires_at_normalizes_aware_datetime_to_local_naive(self):
        datetime_module = importlib.import_module("datetime")
        server_main = load_server_main()
        aware = datetime_module.datetime(
            2026,
            6,
            27,
            3,
            0,
            0,
            tzinfo=datetime_module.timezone.utc,
        )

        parsed, error = server_main.parse_share_expires_at(aware.isoformat())

        self.assertIsNone(error)
        self.assertIsNone(parsed.tzinfo)
        self.assertEqual(parsed, aware.astimezone().replace(tzinfo=None))

    def test_wallet_login_message_contains_nonce_and_purpose(self):
        auth = importlib.import_module("auth")

        message = auth.build_wallet_message("abc123", "login")

        self.assertIn("abc123", message)
        self.assertIn("login", message)
        self.assertIn("Web3 Nodes", message)

    def test_register_rejects_missing_username(self):
        server_main = load_server_main()
        server_main.init_db = lambda: True
        response = server_main.app.test_client().post("/api/auth/register", json={"password": "pw"})
        self.assertEqual(response.status_code, 400)

    def test_register_with_non_json_body_returns_json_400(self):
        server_main = load_server_main()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post("/api/auth/register", data="not-json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_register_with_json_array_returns_json_400(self):
        server_main = load_server_main()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post("/api/auth/register", json=[1])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_register_with_numeric_password_returns_json_400(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/auth/register",
            json={"username": "alice", "password": 123},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_register_rejects_duplicate_username(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            "hash",
            None,
            "active",
        )

        response = server_main.app.test_client().post(
            "/api/auth/register",
            json={"username": "alice", "password": "pw"},
        )

        self.assertEqual(response.status_code, 409)

    def test_login_rejects_bad_password(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            auth.hash_password("correct-pass"),
            None,
            "active",
        )

        response = server_main.app.test_client().post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong-pass"},
        )

        self.assertEqual(response.status_code, 401)

    def test_login_with_numeric_password_returns_json_400(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/auth/login",
            json={"username": "alice", "password": 123},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_login_fails_safely_without_session_secret(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main()
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            auth.hash_password("pw"),
            None,
            "active",
        )

        response = server_main.app.test_client().post(
            "/api/auth/login",
            json={"username": "alice", "password": "pw"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content_type, "application/json")

    def test_login_without_session_secret_does_not_reveal_password_validity(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main()
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            auth.hash_password("correct-pass"),
            None,
            "active",
        )
        client = server_main.app.test_client()

        valid_response = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "correct-pass"},
        )
        invalid_response = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong-pass"},
        )

        self.assertEqual(valid_response.status_code, 503)
        self.assertEqual(invalid_response.status_code, 503)
        self.assertEqual(valid_response.content_type, "application/json")
        self.assertEqual(invalid_response.content_type, "application/json")

    def test_login_does_not_use_admin_api_token_as_session_secret(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(ADMIN_API_TOKEN="admin-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            auth.hash_password("pw"),
            "",
            "active",
        )
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            auth.hash_password("pw"),
            "",
            "active",
        )

        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None

        server_main.cursor = FakeCursor()

        response = server_main.app.test_client().post(
            "/api/auth/login",
            json={"username": "alice", "password": "pw"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content_type, "application/json")

    def test_login_can_issue_token_with_session_secret(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            auth.hash_password("pw"),
            "",
            "active",
        )
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            auth.hash_password("pw"),
            "",
            "active",
        )

        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None

        server_main.cursor = FakeCursor()

        response = server_main.app.test_client().post(
            "/api/auth/login",
            json={"username": "alice", "password": "pw"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.get_json())

    def test_login_rejects_inactive_user(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            auth.hash_password("pw"),
            "",
            "disabled",
        )

        response = server_main.app.test_client().post(
            "/api/auth/login",
            json={"username": "alice", "password": "pw"},
        )

        self.assertEqual(response.status_code, 401)

    def test_login_rejects_null_status_user(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_username = lambda username: (
            1,
            username,
            auth.hash_password("pw"),
            "",
            None,
        )

        response = server_main.app.test_client().post(
            "/api/auth/login",
            json={"username": "alice", "password": "pw"},
        )

        self.assertEqual(response.status_code, 401)

    def test_auth_me_requires_user_token(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        response = server_main.app.test_client().get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_auth_me_rejects_known_default_secret_when_unconfigured(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main()
        server_main.init_db = lambda: True
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            "hash",
            "",
            "active",
        )
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "dev-session-secret")

        response = server_main.app.test_client().get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 503)

    def test_auth_me_accepts_valid_configured_session_secret(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            "hash",
            "",
            "active",
        )
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        response = server_main.app.test_client().get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)

    def test_auth_me_rejects_inactive_user_token(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            "hash",
            "",
            "disabled",
        )
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        response = server_main.app.test_client().get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 401)

    def test_auth_me_rejects_null_status_user_token(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            "hash",
            "",
            None,
        )
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        response = server_main.app.test_client().get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 401)

    def test_wallet_nonce_rowcount_zero_rejects_consumption(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")

        class FakeCursor:
            def __init__(self):
                self.rowcount = 0
                self.executed = []

            def execute(self, sql, params=None):
                self.executed.append((sql, params))

            def fetchone(self):
                return (3, "0xabc", "nonce1", server_main.datetime.now() + server_main.timedelta(minutes=5), None)

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.auth.recover_wallet_address = lambda message, signature: "0xabc"

        ok, msg = server_main.consume_wallet_nonce("0xabc", "nonce1", "login", "signature")

        self.assertFalse(ok)
        self.assertIn("nonce", msg.lower())

    def test_wallet_nonce_with_json_array_returns_json_400(self):
        server_main = load_server_main()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post("/api/wallet/nonce", json=[1])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_wallet_nonce_with_numeric_wallet_address_returns_json_400(self):
        server_main = load_server_main()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/wallet/nonce",
            json={"wallet_address": 123},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_wallet_nonce_with_numeric_purpose_returns_json_400(self):
        server_main = load_server_main()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/wallet/nonce",
            json={"wallet_address": "0xabc", "purpose": 123},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_wallet_login_missing_fields_return_json_400(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        array_response = client.post("/api/wallet/login", json=[1])
        partial_response = client.post("/api/wallet/login", json={"wallet_address": "0xabc"})

        self.assertEqual(array_response.status_code, 400)
        self.assertEqual(array_response.content_type, "application/json")
        self.assertEqual(partial_response.status_code, 400)
        self.assertEqual(partial_response.content_type, "application/json")

    def test_wallet_login_numeric_wallet_address_returns_json_400(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/wallet/login",
            json={"wallet_address": 123, "nonce": "nonce1", "signature": "sig"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_wallet_bind_missing_fields_return_json_400(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            "hash",
            "",
            "active",
        )
        client = server_main.app.test_client()

        array_response = client.post(
            "/api/wallet/bind",
            headers={"Authorization": f"Bearer {token}"},
            json=[1],
        )
        partial_response = client.post(
            "/api/wallet/bind",
            headers={"Authorization": f"Bearer {token}"},
            json={"wallet_address": "0xabc"},
        )

        self.assertEqual(array_response.status_code, 400)
        self.assertEqual(array_response.content_type, "application/json")
        self.assertEqual(partial_response.status_code, 400)
        self.assertEqual(partial_response.content_type, "application/json")

    def test_wallet_bind_numeric_wallet_address_returns_json_400(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            "hash",
            "",
            "active",
        )

        response = server_main.app.test_client().post(
            "/api/wallet/bind",
            headers={"Authorization": f"Bearer {token}"},
            json={"wallet_address": 123, "nonce": "nonce1", "signature": "sig"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_wallet_login_invalid_nonce_returns_json_400(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None

            def fetchone(self):
                return None

        server_main.cursor = FakeCursor()

        response = server_main.app.test_client().post(
            "/api/wallet/login",
            json={"wallet_address": "0xabc", "nonce": "bad-nonce", "signature": "sig"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_wallet_bind_invalid_nonce_returns_json_400(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        server_main.select_user_by_id = lambda user_id: (
            user_id,
            "alice",
            "hash",
            "",
            "active",
        )

        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None

            def fetchone(self):
                return None

        server_main.cursor = FakeCursor()

        response = server_main.app.test_client().post(
            "/api/wallet/bind",
            headers={"Authorization": f"Bearer {token}"},
            json={"wallet_address": "0xabc", "nonce": "bad-nonce", "signature": "sig"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")

    def test_wallet_login_rejects_inactive_user(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        server_main.consume_wallet_nonce = lambda wallet, nonce, purpose, signature: (True, "")
        server_main.select_user_by_wallet = lambda wallet_address: (
            7,
            "alice",
            "hash",
            wallet_address,
            "disabled",
        )

        response = server_main.app.test_client().post(
            "/api/wallet/login",
            json={"wallet_address": "0xabc", "nonce": "nonce1", "signature": "sig"},
        )

        self.assertEqual(response.status_code, 401)

    def test_default_database_engine_is_postgresql(self):
        server_main = load_server_main()

        self.assertEqual(server_main.DB_ENGINE, "postgresql")
        self.assertEqual(server_main.DB_CONFIG["host"], "127.0.0.1")
        self.assertEqual(server_main.DB_CONFIG["port"], 5432)
        self.assertEqual(server_main.DB_CONFIG["user"], "postgres")
        self.assertEqual(server_main.DB_CONFIG["password"], "")
        self.assertEqual(server_main.DB_CONFIG["database"], "web3_modes_store")

    def test_postgres_environment_variables_are_preferred(self):
        server_main = load_server_main(
            DB_ENGINE="postgresql",
            POSTGRES_HOST="10.0.0.9",
            POSTGRES_PORT="5433",
            POSTGRES_USER="pguser",
            POSTGRES_PASSWORD="pgpass",
            POSTGRES_DB_NAME="pgdb",
        )

        self.assertEqual(server_main.DB_CONFIG["host"], "10.0.0.9")
        self.assertEqual(server_main.DB_CONFIG["port"], 5433)
        self.assertEqual(server_main.DB_CONFIG["user"], "pguser")
        self.assertEqual(server_main.DB_CONFIG["password"], "pgpass")
        self.assertEqual(server_main.DB_CONFIG["database"], "pgdb")

    def test_mysql_environment_variables_are_preferred(self):
        server_main = load_server_main(
            DB_ENGINE="mysql",
            MYSQL_HOST="172.25.244.60",
            MYSQL_PORT="3306",
            MYSQL_USER="root",
            MYSQL_PASSWORD="cjl19880307",
            MYSQL_DB_NAME="web3_modes_store",
            DB_HOST="127.0.0.1",
            DB_PORT="3307",
            DB_USER="legacy",
            DB_PASSWORD="legacy-password",
            DB_NAME="node_reward",
        )

        self.assertEqual(server_main.DB_CONFIG["host"], "172.25.244.60")
        self.assertEqual(server_main.DB_CONFIG["port"], 3306)
        self.assertEqual(server_main.DB_CONFIG["user"], "root")
        self.assertEqual(server_main.DB_CONFIG["password"], "cjl19880307")
        self.assertEqual(server_main.DB_CONFIG["database"], "web3_modes_store")

    def test_default_database_config_does_not_embed_production_password(self):
        server_main = load_server_main()

        self.assertEqual(server_main.DB_CONFIG["host"], "127.0.0.1")
        self.assertEqual(server_main.DB_CONFIG["password"], "")

    def test_dotenv_file_can_populate_environment_without_overwriting_existing(self):
        server_main = load_server_main()
        os.environ["MYSQL_USER"] = "existing-user"
        env_path = Path("tests/.env.sample")
        env_path.write_text(
            "\n".join(
                [
                    "MYSQL_HOST=10.0.0.5",
                    "MYSQL_USER=env-user",
                    "MYSQL_PASSWORD=env-password",
                    "ADMIN_API_TOKEN=env-token",
                ]
            ),
            encoding="utf-8",
        )
        try:
            server_main.load_env_file(env_path)
            self.assertEqual(os.environ["MYSQL_HOST"], "10.0.0.5")
            self.assertEqual(os.environ["MYSQL_USER"], "existing-user")
            self.assertEqual(os.environ["MYSQL_PASSWORD"], "env-password")
            self.assertEqual(os.environ["ADMIN_API_TOKEN"], "env-token")
        finally:
            env_path.unlink(missing_ok=True)
            for key in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "ADMIN_API_TOKEN"):
                os.environ.pop(key, None)

    def test_runtime_secret_bootstrap_generates_missing_values(self):
        server_main = load_server_main()
        env_path = Path("tests/.env.generated")
        env_path.unlink(missing_ok=True)
        environ = {}
        printed = []
        try:
            generated = server_main.ensure_runtime_secrets(
                env_path=env_path,
                environ=environ,
                print_func=printed.append,
            )

            self.assertEqual(set(generated), {"ADMIN_API_TOKEN", "SESSION_SECRET", "AES_KEY"})
            self.assertEqual(environ["ADMIN_API_TOKEN"], generated["ADMIN_API_TOKEN"])
            self.assertEqual(environ["SESSION_SECRET"], generated["SESSION_SECRET"])
            self.assertEqual(environ["AES_KEY"], generated["AES_KEY"])
            self.assertEqual(len(generated["AES_KEY"]), 16)
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("ADMIN_API_TOKEN=", text)
            self.assertIn("SESSION_SECRET=", text)
            self.assertIn("AES_KEY=", text)
            self.assertTrue(any("/admin/login" in line for line in printed))
        finally:
            env_path.unlink(missing_ok=True)

    def test_runtime_secret_bootstrap_preserves_existing_values(self):
        server_main = load_server_main()
        env_path = Path("tests/.env.existing")
        env_path.write_text(
            "\n".join([
                "ADMIN_API_TOKEN=existing-admin",
                "SESSION_SECRET=existing-session",
                "AES_KEY=existing-aes-key",
            ]),
            encoding="utf-8",
        )
        environ = {}
        try:
            generated = server_main.ensure_runtime_secrets(
                env_path=env_path,
                environ=environ,
                print_func=lambda message: None,
            )

            self.assertEqual(generated, {})
            self.assertEqual(environ["ADMIN_API_TOKEN"], "existing-admin")
            self.assertEqual(environ["SESSION_SECRET"], "existing-session")
            self.assertEqual(environ["AES_KEY"], "existing-aes-key")
            self.assertEqual(env_path.read_text(encoding="utf-8").count("ADMIN_API_TOKEN="), 1)
        finally:
            env_path.unlink(missing_ok=True)

    def test_init_mysql_sql_contains_database_and_required_tables(self):
        sql = Path("init_mysql.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE DATABASE IF NOT EXISTS `web3_modes_store`", sql)
        self.assertIn("USE `web3_modes_store`", sql)
        for table_name in (
            "user_node",
            "node_power",
            "node_reward",
            "file_chain_record",
            "node_location",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS `{table_name}`", sql)
        self.assertIn("`settle_date` date", sql)
        self.assertIn("`source_user_address` varchar(64)", sql)
        self.assertIn("UNIQUE KEY `idx_reward_once`", sql)
        self.assertIn("`visibility` varchar(16)", sql)
        self.assertIn("`access_token` varchar(64)", sql)
        self.assertIn("`deleted_at` datetime", sql)

    def test_init_postgresql_sql_contains_database_tables_and_constraints(self):
        sql = Path("init_postgresql.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS user_node", sql)
        self.assertIn("id SERIAL PRIMARY KEY", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS node_reward", sql)
        self.assertIn("settle_date date", sql)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS idx_reward_once", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS file_chain_record", sql)
        self.assertIn("visibility varchar(16)", sql)

    def test_user_product_tables_exist_in_postgresql_init_sql(self):
        sql = Path("init_postgresql.sql").read_text(encoding="utf-8")

        for table_name in (
            "app_user",
            "wallet_nonce",
            "file_share",
            "file_download_log",
            "point_ledger",
            "withdrawal_request",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table_name}", sql)

        self.assertIn("owner_user_id integer", sql)
        self.assertIn("owner_wallet_address varchar(128)", sql)
        self.assertIn("download_count integer DEFAULT 0", sql)
        self.assertIn("last_download_at timestamp DEFAULT NULL", sql)

    def test_user_product_tables_exist_in_mysql_init_sql(self):
        sql = Path("init_mysql.sql").read_text(encoding="utf-8")

        for table_name in (
            "app_user",
            "wallet_nonce",
            "file_share",
            "file_download_log",
            "point_ledger",
            "withdrawal_request",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS `{table_name}`", sql)

        self.assertIn("`owner_user_id` int DEFAULT NULL", sql)
        self.assertIn("`owner_wallet_address` varchar(128) DEFAULT ''", sql)
        self.assertIn("`download_count` int DEFAULT 0", sql)
        self.assertIn("`last_download_at` datetime DEFAULT NULL", sql)

    def test_withdrawal_request_node_fields_exist_in_init_sql_and_migrations(self):
        mysql_sql = Path("init_mysql.sql").read_text(encoding="utf-8")
        postgres_sql = Path("init_postgresql.sql").read_text(encoding="utf-8")
        mysql_server = load_server_main(DB_ENGINE="mysql")
        postgres_server = load_server_main(DB_ENGINE="postgresql")
        mysql_migrations = "\n".join(mysql_server.database_module.SCHEMA_MIGRATIONS)
        postgres_migrations = "\n".join(postgres_server.database_module.POSTGRES_SCHEMA_MIGRATIONS)

        self.assertIn("`user_id` int DEFAULT NULL", mysql_sql)
        self.assertIn("user_id integer DEFAULT NULL", postgres_sql)
        for column in ("node_address", "withdrawal_channel", "withdrawal_account"):
            self.assertIn(column, mysql_sql)
            self.assertIn(column, postgres_sql)
            self.assertIn(column, mysql_migrations)
            self.assertIn(column, postgres_migrations)

    def test_user_product_indexes_exist_in_postgresql_init_sql_and_migrations(self):
        sql = Path("init_postgresql.sql").read_text(encoding="utf-8")
        server_main = load_server_main(DB_ENGINE="postgresql")
        migrations = "\n".join(server_main.database_module.POSTGRES_SCHEMA_MIGRATIONS)

        expected_indexes = (
            ("idx_file_chain_owner", "file_chain_record", "owner_user_id"),
            ("idx_wallet_nonce_address", "wallet_nonce", "wallet_address"),
            ("idx_file_share_file", "file_share", "file_hash"),
            ("idx_file_share_owner", "file_share", "owner_user_id"),
            ("idx_download_file", "file_download_log", "file_hash"),
            ("idx_download_share", "file_download_log", "share_code"),
            ("idx_point_user", "point_ledger", "user_id"),
            ("idx_point_wallet", "point_ledger", "wallet_address"),
            ("idx_withdrawal_user", "withdrawal_request", "user_id"),
            ("idx_withdrawal_status", "withdrawal_request", "status"),
        )

        for index_name, table_name, column_name in expected_indexes:
            expected = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"
            self.assertIn(expected, sql)
            self.assertIn(expected, migrations)

    def test_user_product_indexes_exist_in_mysql_init_sql_and_migrations(self):
        sql = Path("init_mysql.sql").read_text(encoding="utf-8")
        server_main = load_server_main(DB_ENGINE="mysql")
        migrations = "\n".join(server_main.database_module.SCHEMA_MIGRATIONS)

        expected_keys = (
            ("idx_file_chain_owner", "owner_user_id"),
            ("idx_wallet_nonce_address", "wallet_address"),
            ("idx_file_share_file", "file_hash"),
            ("idx_file_share_owner", "owner_user_id"),
            ("idx_download_file", "file_hash"),
            ("idx_download_share", "share_code"),
            ("idx_point_user", "user_id"),
            ("idx_point_wallet", "wallet_address"),
            ("idx_withdrawal_user", "user_id"),
            ("idx_withdrawal_status", "status"),
        )

        for index_name, column_name in expected_keys:
            if index_name == "idx_file_chain_owner":
                self.assertIn("CREATE INDEX idx_file_chain_owner ON `file_chain_record` (`owner_user_id`)", sql)
            else:
                self.assertIn(f"KEY `{index_name}` (`{column_name}`)", sql)
            self.assertIn(f"CREATE INDEX {index_name}", migrations)

    def test_node_power_capacity_fields_exist_in_init_sql_and_migrations(self):
        mysql_sql = Path("init_mysql.sql").read_text(encoding="utf-8")
        postgres_sql = Path("init_postgresql.sql").read_text(encoding="utf-8")
        mysql_server = load_server_main(DB_ENGINE="mysql")
        postgres_server = load_server_main(DB_ENGINE="postgresql")
        mysql_migrations = "\n".join(mysql_server.database_module.SCHEMA_MIGRATIONS)
        postgres_migrations = "\n".join(postgres_server.database_module.POSTGRES_SCHEMA_MIGRATIONS)

        for column in ("storage_path", "storage_status", "storage_error", "storage_total_gb", "storage_used_gb", "storage_free_gb"):
            self.assertIn(column, mysql_sql)
            self.assertIn(column, postgres_sql)
            self.assertIn(column, mysql_migrations)
            self.assertIn(column, postgres_migrations)

    def test_shard_and_audit_schema_exist(self):
        mysql_sql = Path("init_mysql.sql").read_text(encoding="utf-8")
        postgres_sql = Path("init_postgresql.sql").read_text(encoding="utf-8")
        mysql_server = load_server_main(DB_ENGINE="mysql")
        postgres_server = load_server_main(DB_ENGINE="postgresql")
        mysql_migrations = "\n".join(mysql_server.database_module.SCHEMA_MIGRATIONS)
        postgres_migrations = "\n".join(postgres_server.database_module.POSTGRES_SCHEMA_MIGRATIONS)

        for text in (mysql_sql, postgres_sql, mysql_migrations, postgres_migrations):
            self.assertIn("file_shard_record", text)
            self.assertIn("storage_audit_log", text)
            self.assertIn("storage_quota_gb", text)
            self.assertIn("storage_available_gb", text)

    def test_insert_storage_audit_log_writes_expected_fields(self):
        server_main = load_server_main()
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))

        server_main.cursor = FakeCursor()
        server_main.insert_storage_audit_log(
            "shard.write.success",
            file_hash="a" * 64,
            chunk_index=2,
            node_address="NODE_A",
            request_id="REQ1",
            status="ok",
            message="stored",
            metadata={"chunk_hash": "b" * 64},
        )

        self.assertEqual(len(executed), 1)
        sql, params = executed[0]
        self.assertIn("insert into storage_audit_log", sql.lower())
        self.assertIn("shard.write.success", params)
        self.assertIn("a" * 64, params)
        self.assertIn("NODE_A", params)
        self.assertIn("REQ1", params)

    def test_heartbeat_stores_capacity_fields_and_allows_old_payloads(self):
        server_main = load_server_main()
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        old_response = client.post("/heartbeat", json={
            "user_addr": "NODE_A",
            "node_mac": "MAC_A",
            "disk_used": 2.5,
            "upload_bw": 1.2,
        })
        new_response = client.post("/heartbeat", json={
            "user_addr": "NODE_A",
            "node_mac": "MAC_A",
            "disk_used": 3.5,
            "upload_bw": 1.5,
            "storage_path": "D:/web3-node-data",
            "storage_status": "ok",
            "storage_error": "",
            "storage_total_gb": 512,
            "storage_used_gb": 128,
            "storage_free_gb": 384,
        })

        self.assertEqual(old_response.status_code, 200)
        self.assertEqual(new_response.status_code, 200)
        self.assertEqual(executed[0][1][2:8], ("", "unknown", "", 0.0, 2.5, 0.0))
        self.assertTrue(any("storage_total_gb" in sql for sql, _ in executed))
        self.assertIn("D:/web3-node-data", executed[-1][1])

    def test_sql_dialect_helpers_switch_by_engine(self):
        mysql_server = load_server_main(DB_ENGINE="mysql")
        postgres_server = load_server_main(DB_ENGINE="postgresql")

        self.assertIn("ON DUPLICATE KEY UPDATE", mysql_server.reward_upsert_sql())
        self.assertIn("ON CONFLICT", postgres_server.reward_upsert_sql())
        self.assertIn("NOW() - INTERVAL 3 MINUTE", mysql_server.node_alive_interval_sql())
        self.assertIn("NOW() - INTERVAL '3 minutes'", postgres_server.node_alive_interval_sql())

    def test_get_ip_location_uses_requests_response(self):
        server_main = load_server_main()

        self.assertEqual(
            server_main.get_ip_location("8.8.8.8"),
            {
                "country": "中国",
                "province": "广东",
                "city": "深圳",
                "lat": "22.5431",
                "lng": "114.0579",
            },
        )

    def test_database_initializer_executes_init_sql_without_selected_database(self):
        server_main = load_server_main(DB_ENGINE="mysql")
        calls = []

        class FakeCursor:
            def execute(self, sql):
                calls.append(sql)

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def close(self):
                calls.append("close")

        def fake_connect(**kwargs):
            calls.append(kwargs)
            return FakeConnection()

        server_main.connect_database.__globals__["pymysql"].connect = fake_connect

        self.assertTrue(server_main.ensure_database_initialized())
        self.assertNotIn("database", calls[0])
        self.assertTrue(any("CREATE DATABASE IF NOT EXISTS" in sql for sql in calls))
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS `user_node`" in sql for sql in calls))

    def test_mysql_initializer_ignores_duplicate_file_column_alters(self):
        server_main = load_server_main(DB_ENGINE="mysql")
        calls = []

        class FakeCursor:
            def execute(self, sql):
                calls.append(sql)
                if sql.startswith("ALTER TABLE `file_chain_record` ADD COLUMN `owner_user_id`"):
                    raise Exception("Duplicate column name 'owner_user_id'")

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def close(self):
                calls.append("close")

        def fake_connect(**kwargs):
            calls.append(kwargs)
            return FakeConnection()

        server_main.connect_database.__globals__["pymysql"].connect = fake_connect

        self.assertTrue(server_main.ensure_database_initialized())
        self.assertIn("close", calls)

    def test_mysql_initializer_ignores_duplicate_owner_index_creation(self):
        server_main = load_server_main(DB_ENGINE="mysql")
        calls = []

        class FakeCursor:
            def execute(self, sql):
                calls.append(sql)
                if sql == "CREATE INDEX idx_file_chain_owner ON `file_chain_record` (`owner_user_id`)":
                    raise Exception("Duplicate key name 'idx_file_chain_owner'")

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def close(self):
                calls.append("close")

        def fake_connect(**kwargs):
            calls.append(kwargs)
            return FakeConnection()

        server_main.connect_database.__globals__["pymysql"].connect = fake_connect

        self.assertTrue(server_main.ensure_database_initialized())
        self.assertIn("close", calls)

    def test_database_initializer_failure_updates_server_error(self):
        server_main = load_server_main(DB_ENGINE="mysql")
        missing_path = Path("tests/missing-init-file.sql")

        self.assertFalse(server_main.ensure_database_initialized(sql_path=missing_path))
        self.assertIn("missing-init-file.sql", server_main.db_error)

    def test_admin_api_requires_token_before_mutation(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        client = server_main.app.test_client()

        response = client.post(
            "/api/set_ratio",
            json={"self_ratio": 0.2, "node_ratio": 0.8},
        )

        self.assertEqual(response.status_code, 401)

    def test_admin_api_accepts_valid_token(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None

            def fetchall(self):
                return []

        server_main.db = object()
        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        response = client.post(
            "/api/set_ratio",
            headers={"X-Admin-Token": "secret-token"},
            json={"self_ratio": 0.2, "node_ratio": 0.8},
        )

        self.assertEqual(response.status_code, 200)

    def test_admin_page_uses_login_session_instead_of_inline_token_form(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        self.assertNotIn("prompt(", server_main.ADMIN_HTML)
        self.assertNotIn('id="adminTokenInput"', server_main.ADMIN_HTML)
        self.assertNotIn("saveAdminToken", server_main.ADMIN_HTML)
        self.assertNotIn("clearAdminToken", server_main.ADMIN_HTML)
        self.assertIn('id="adminTokenInput"', server_main.ADMIN_LOGIN_HTML)
        self.assertIn("/api/admin/login", server_main.ADMIN_LOGIN_HTML)

    def test_admin_login_page_renders_token_login_form_without_database(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        server_main.init_db = lambda: self.fail("admin login page should not require database")

        response = server_main.app.test_client().get("/admin/login")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("后台登录", body)
        self.assertIn("/api/admin/login", body)
        self.assertIn("admin_token", body)

    def test_public_homepage_links_business_user_admin_and_node_flows(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        server_main.init_db = lambda: self.fail("public homepage should not require database")

        response = server_main.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Web3 节点激励与文件分享系统", body)
        self.assertIn("企业级分布式存储", body)
        self.assertNotIn('class="navlinks"', body)
        for label in ("开始使用", "上传并创建分享", "进入服务端后台"):
            self.assertIn(label, body)
        for path in (
            "/user/login",
            "/user/upload",
            "/user/dashboard",
            "/admin/login",
            "/admin",
            "/api/health",
        ):
            self.assertIn(path, body)
        self.assertNotIn('id="nodeTable"', body)

    def test_admin_dashboard_is_available_at_admin_without_database(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        server_main.init_db = lambda: self.fail("admin dashboard shell should not require database")

        response = server_main.app.test_client().get("/admin")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="nodeTable"', body)
        self.assertIn("/admin/login", body)

    def test_admin_login_api_validates_token_without_admin_header(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        server_main.init_db = lambda: self.fail("admin login api should not require database")
        client = server_main.app.test_client()

        bad_response = client.post("/api/admin/login", json={"token": "bad-token"})
        ok_response = client.post("/api/admin/login", json={"token": "secret-token"})

        self.assertEqual(bad_response.status_code, 401)
        self.assertEqual(ok_response.status_code, 200)
        self.assertTrue(ok_response.get_json()["authenticated"])

    def test_admin_page_guides_missing_token_to_login_page(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        self.assertIn("/admin/login", server_main.ADMIN_HTML)
        self.assertIn('window.location.href = "/admin"', server_main.ADMIN_LOGIN_HTML)
        self.assertIn("requireAdminLogin", server_main.ADMIN_HTML)

    def test_admin_page_auto_refreshes_dashboard_data(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        self.assertIn("ADMIN_REFRESH_INTERVAL_MS", server_main.ADMIN_HTML)
        self.assertIn("startAdminAutoRefresh", server_main.ADMIN_HTML)
        self.assertIn('id="adminAutoRefreshStatus"', server_main.ADMIN_HTML)
        self.assertIn("setInterval(refreshAdminData", server_main.ADMIN_HTML)
        self.assertIn("getIpfsStatus();", server_main.ADMIN_HTML)
        self.assertIn("DOMContentLoaded", server_main.ADMIN_HTML)
        self.assertIn("const ADMIN_REFRESH_INTERVAL_MS = 10000", server_main.ADMIN_HTML)

    def test_admin_page_uses_configurable_map_key_with_fallback(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        server_main.init_db = lambda: self.fail("admin dashboard shell should not require database")

        response = server_main.app.test_client().get("/admin")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn("6f17f9896974a8686929496921212479", body)
        self.assertNotIn("webapi.amap.com/maps?v=2.0&key=", body)
        self.assertIn("AMAP_WEB_KEY", body)
        self.assertIn("renderMapFallback", body)
        self.assertIn('id="nodeDistributionFallback"', body)

    def test_admin_page_does_not_load_amap_when_security_jscode_is_missing(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token", AMAP_WEB_KEY="valid-map-key")
        server_main.init_db = lambda: self.fail("admin dashboard shell should not require database")

        response = server_main.app.test_client().get("/admin")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn("webapi.amap.com/maps?v=2.0&key=valid-map-key", body)
        self.assertIn("AMAP_SECURITY_JSCODE", body)
        self.assertIn("renderMapFallback", body)

    def test_admin_page_loads_amap_with_security_jscode_when_configured(self):
        server_main = load_server_main(
            ADMIN_API_TOKEN="secret-token",
            AMAP_WEB_KEY="valid-map-key",
            AMAP_SECURITY_JSCODE="valid-security-code",
        )
        server_main.init_db = lambda: self.fail("admin dashboard shell should not require database")

        response = server_main.app.test_client().get("/admin")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("window._AMapSecurityConfig", body)
        self.assertIn('"valid-security-code"', body)
        self.assertIn("webapi.amap.com/maps?v=2.0&key=valid-map-key", body)

    def test_main_pages_share_modern_commercial_shell(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token", SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        for path in ("/", "/admin/login", "/admin", "/user/login", "/user/upload", "/user/dashboard", "/s/demo-share"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            body = response.get_data(as_text=True)
            self.assertIn("commercial-page", body, path)
            self.assertIn("modern-nav", body, path)
            self.assertIn("commercial-card", body, path)

    def test_commercial_shell_uses_premium_button_system(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token", SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        homepage = client.get("/").get_data(as_text=True)
        admin = client.get("/admin").get_data(as_text=True)
        admin_login = client.get("/admin/login").get_data(as_text=True)
        login = client.get("/user/login").get_data(as_text=True)

        self.assertEqual(homepage.count(":root{--ink"), 1)
        for body in (homepage, admin, admin_login, login):
            self.assertIn("premium-button", body)
            self.assertIn("button-shine", body)
            self.assertIn("hover-lift", body)
            self.assertIn("linear-gradient(135deg,#0f766e,#14b8a6 48%,#f0b429)", body)

    def test_select_node_rows_uses_request_cursor_not_mutable_global_cursor(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        class FailingGlobalCursor:
            def execute(self, *args, **kwargs):
                raise AssertionError("request query used mutable global cursor")

        class RequestCursor:
            def __init__(self):
                self.executed = False

            def execute(self, *args, **kwargs):
                self.executed = True

            def fetchall(self):
                return [(
                    "NODE_A",
                    "INV1",
                    "",
                    1,
                    2,
                    3,
                    server_main.datetime.now(),
                    None,
                    None,
                )]

        request_cursor = RequestCursor()
        server_main.cursor = FailingGlobalCursor()

        with server_main.app.test_request_context("/api/node_list"):
            server_main.g.cursor = request_cursor
            rows = server_main.select_node_rows()

        self.assertTrue(request_cursor.executed)
        self.assertEqual(rows[0][0], "NODE_A")

    def test_upload_check_rejects_unsafe_file_hash(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        response = client.post(
            "/api/upload_check",
            headers={"X-Admin-Token": "secret-token"},
            json={"fileHash": "../outside"},
        )

        self.assertEqual(response.status_code, 400)

    def test_settlement_once_initializes_database_before_settling(self):
        server_main = load_server_main()
        calls = []

        server_main.init_db = lambda: calls.append("init") or True
        server_main.auto_settle_reward = lambda: calls.append("settle") or True

        self.assertTrue(server_main.run_settlement_once())
        self.assertEqual(calls, ["init", "settle"])

    def test_windows_client_parses_invite_argument(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        old_argv = sys.argv[:]
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.argv = ["client.exe", "invite=ABC123"]
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")

            self.assertEqual(client_module.get_invite_arg(), "ABC123")
        finally:
            sys.argv = old_argv
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_quality_score_combines_storage_duration_bandwidth_and_location(self):
        server_main = load_server_main()

        score = server_main.calculate_quality_score(
            disk_used=20,
            online_duration=300,
            upload_bandwidth=5,
            has_location=True,
        )

        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)
        self.assertEqual(score, 88)

    def test_node_record_formats_online_status_and_quality(self):
        server_main = load_server_main()
        now = server_main.datetime.now()

        record = server_main.format_node_record(
            ("NODE_A", "INVITE1", "", 12.5, 90, 3.2, now, "中国", "深圳")
        )

        self.assertTrue(record["is_online"])
        self.assertEqual(record["online_status"], "在线")
        self.assertIn("quality_score", record)

    def test_node_record_formats_capacity_fields(self):
        server_main = load_server_main()
        now = server_main.datetime.now()

        record = server_main.format_node_record((
            "NODE_A", "INVITE1", "", 12.5, 90, 3.2, now, "中国", "深圳",
            "D:/web3-node-data", "ok", "", 512, 128, 384,
        ))

        self.assertEqual(record["storage_path"], "D:/web3-node-data")
        self.assertEqual(record["storage_status"], "ok")
        self.assertEqual(record["storage_total_gb"], 512)
        self.assertEqual(record["storage_used_gb"], 128)
        self.assertEqual(record["storage_free_gb"], 384)

        null_record = server_main.format_node_record((
            "NODE_B", "INVITE2", "", 1, 2, 3, now, "", "",
            None, None, None, None, None, None,
        ))
        self.assertEqual(null_record["storage_path"], "")
        self.assertEqual(null_record["storage_status"], "unknown")
        self.assertEqual(null_record["storage_error"], "")
        self.assertEqual(null_record["storage_total_gb"], 0)
        self.assertEqual(null_record["storage_used_gb"], 1)
        self.assertEqual(null_record["storage_free_gb"], 0)

    def test_admin_page_renders_capacity_and_withdrawal_sections(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        self.assertIn("总容量", server_main.ADMIN_HTML)
        self.assertIn("可用容量", server_main.ADMIN_HTML)
        self.assertIn("提现申请", server_main.ADMIN_HTML)
        self.assertIn("getAdminWithdrawals", server_main.ADMIN_HTML)
        self.assertIn("reviewWithdrawal", server_main.ADMIN_HTML)
        self.assertIn("escHtml(item.storage_status", server_main.ADMIN_HTML)
        self.assertIn("withdrawalNoteDrafts", server_main.ADMIN_HTML)
        self.assertIn("document.activeElement", server_main.ADMIN_HTML)

    def test_auto_settle_reward_uses_daily_snapshot_key(self):
        server_main = load_server_main()
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))
                self.last_sql = sql

            def fetchall(self):
                return [(
                    "NODE_A",
                    10,
                    30,
                )]

            def fetchone(self):
                if "parent_invite_code" in self.last_sql:
                    return ("PARENT1",)
                if "invite_code" in self.last_sql:
                    return ("NODE_PARENT",)
                return None

        server_main.cursor = FakeCursor()

        self.assertTrue(server_main.auto_settle_reward())
        node_select_sql = [sql for sql, _ in executed if "from node_power" in sql.lower()][0]
        self.assertNotIn("select *", node_select_sql.lower())
        self.assertIn("user_address", node_select_sql)
        self.assertIn("disk_used", node_select_sql)
        self.assertIn("online_duration", node_select_sql)
        reward_sql = [sql for sql, _ in executed if "insert into node_reward" in sql.lower()]
        self.assertTrue(reward_sql)
        self.assertTrue(all("settle_date" in sql for sql in reward_sql))
        self.assertTrue(all("source_user_address" in sql for sql in reward_sql))
        self.assertTrue(all("ON CONFLICT" in sql or "ON DUPLICATE KEY UPDATE" in sql for sql in reward_sql))

    def test_invite_tree_builds_parent_child_structure(self):
        server_main = load_server_main()
        rows = [
            ("ROOT", "R1", "", 10, 20, 1, server_main.datetime.now(), None, None),
            ("CHILD", "C1", "R1", 5, 10, 1, server_main.datetime.now(), None, None),
        ]

        tree = server_main.build_invite_tree(rows)

        self.assertEqual(tree[0]["user_addr"], "ROOT")
        self.assertEqual(tree[0]["children"][0]["user_addr"], "CHILD")

    def test_leaderboard_sorts_by_quality_score(self):
        server_main = load_server_main()
        rows = [
            ("LOW", "L1", "", 1, 10, 1, server_main.datetime.now(), None, None),
            ("HIGH", "H1", "", 50, 500, 8, server_main.datetime.now(), "中国", "深圳"),
        ]

        leaderboard = server_main.build_leaderboard(rows)

        self.assertEqual(leaderboard[0]["user_addr"], "HIGH")
        self.assertEqual(leaderboard[0]["rank"], 1)

    def test_client_config_file_overrides_defaults(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        config_path = Path("tests/node_config.json")
        config_path.write_text(
            '{"server_url":"http://example.com:9000","parent_invite":"INV1","heartbeat_interval":5,"reconnect_interval":2,"storage_dir":"D:/web3-node-data"}',
            encoding="utf-8",
        )
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")

            config = client_module.load_client_config(config_path)
            self.assertEqual(config["server_url"], "http://example.com:9000")
            self.assertEqual(config["parent_invite"], "INV1")
            self.assertEqual(config["heartbeat_interval"], 5)
            self.assertEqual(config["reconnect_interval"], 2)
            self.assertEqual(config["storage_dir"], "D:/web3-node-data")
        finally:
            config_path.unlink(missing_ok=True)
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_config_supports_manage_port(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        config_path = Path("tests/node_config.json")
        config_path.write_text('{"manage_port":8788,"storage_dir":"D:/node"}', encoding="utf-8")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            config = client_module.load_client_config(config_path)
            self.assertEqual(config["manage_port"], 8788)
        finally:
            config_path.unlink(missing_ok=True)
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_config_tracks_explicit_storage_and_quota(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        empty_config_path = Path("tests/empty-node-config.json")
        quota_config_path = Path("tests/quota-node-config.json")
        empty_config_path.write_text("{}", encoding="utf-8")
        quota_config_path.write_text(
            '{"storage_dir":"D:/node","storage_quota_gb":128}',
            encoding="utf-8",
        )
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")

            empty_config = client_module.load_client_config(empty_config_path)
            quota_config = client_module.load_client_config(quota_config_path)

            self.assertFalse(empty_config["storage_explicit"])
            self.assertEqual(empty_config["storage_quota_gb"], 0)
            self.assertTrue(quota_config["storage_explicit"])
            self.assertEqual(quota_config["storage_quota_gb"], 128)
        finally:
            empty_config_path.unlink(missing_ok=True)
            quota_config_path.unlink(missing_ok=True)
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_prepare_storage_root_writes_lock_and_store_dir(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            with tempfile.TemporaryDirectory() as tmp:
                result = client_module.prepare_storage_root(tmp, "NODE_A", "MAC_A")
                lock_data = json.loads((Path(tmp) / ".web3_nodes.lock").read_text(encoding="utf-8"))

                self.assertEqual(result["store_dir"], str(Path(tmp) / ".web3_nodes_store"))
                self.assertTrue((Path(tmp) / ".web3_nodes_store").is_dir())
                self.assertEqual(lock_data["user_addr"], "NODE_A")
                self.assertEqual(lock_data["node_mac"], "MAC_A")
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_prepare_storage_root_rejects_lock_mismatch(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            with tempfile.TemporaryDirectory() as tmp:
                client_module.prepare_storage_root(tmp, "NODE_A", "MAC_A")

                with self.assertRaisesRegex(RuntimeError, "locked"):
                    client_module.prepare_storage_root(tmp, "NODE_B", "MAC_B")
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_manage_port_env_and_cli_override(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        old_env = os.environ.get("NODE_MANAGE_PORT")
        old_argv = sys.argv[:]
        try:
            os.environ["NODE_MANAGE_PORT"] = "8799"
            sys.argv = ["client.py", "--manage-port=8801"]
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")

            config = client_module.load_client_config("tests/missing-node-config.json")

            self.assertEqual(config["manage_port"], 8799)
            self.assertEqual(client_module.get_manage_port_arg(), 8801)
        finally:
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop("NODE_MANAGE_PORT", None)
            else:
                os.environ["NODE_MANAGE_PORT"] = old_env
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_console_html_contains_node_operations(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            html = client_module.CLIENT_MANAGE_HTML
            for marker in ("节点控制台", "总容量", "提交提现", "添加目录", "停止节点", "重启节点"):
                self.assertIn(marker, html)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_console_calls_node_earnings_and_withdrawal_apis(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")

        class FakeResponse:
            def __init__(self, payload, status_code=200):
                self._payload = payload
                self.status_code = status_code

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"http {self.status_code}")

            def json(self):
                return self._payload

        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            html = client_module.CLIENT_MANAGE_HTML
            for marker in ("/api/earnings", "/api/withdrawals", "/api/control/stop", "/api/control/restart"):
                self.assertIn(marker, html)

            get_calls = []
            post_calls = []

            def fake_get(url, params=None, timeout=10):
                get_calls.append((url, params, timeout))
                if url.endswith("/api/node/earnings"):
                    return FakeResponse({"code": 200, "data": {"available_earnings": "12.50", "withdrawn_earnings": "3.00"}})
                if url.endswith("/api/node/withdrawals"):
                    return FakeResponse({"code": 200, "data": [{"id": 7, "amount": "5.00", "status": "pending"}]})
                raise AssertionError(f"unexpected GET {url}")

            def fake_post(url, json=None, timeout=10):
                post_calls.append((url, json, timeout))
                if url.endswith("/api/node/withdrawals"):
                    return FakeResponse({"code": 200, "data": {"id": 9, "status": "pending", "amount": json["amount"]}})
                raise AssertionError(f"unexpected POST {url}")

            client_module.requests = types.SimpleNamespace(get=fake_get, post=fake_post)
            client_module.inspect_storage_dir = lambda storage_dir: {
                "storage_path": storage_dir,
                "storage_status": "ok",
                "storage_total_gb": 100,
                "storage_used_gb": 20,
                "storage_free_gb": 80,
            }
            state = client_module.create_client_state("http://server.example", "NODE_A", "MAC_A", "D:/node", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(f"{base_url}/api/earnings", timeout=5) as response:
                    earnings_payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(earnings_payload["ok"])
                self.assertEqual(earnings_payload["data"]["available_earnings"], "12.50")

                with urllib.request.urlopen(f"{base_url}/api/withdrawals", timeout=5) as response:
                    withdrawals_payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(withdrawals_payload["ok"])
                self.assertEqual(withdrawals_payload["data"][0]["id"], 7)

                withdrawal_request = urllib.request.Request(
                    f"{base_url}/api/withdrawals",
                    data=json.dumps(
                        {
                            "amount": "5.00",
                            "wallet_address": "0xabc",
                            "withdrawal_channel": "bank",
                            "withdrawal_account": "acct-1",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with urllib.request.urlopen(withdrawal_request, timeout=5) as response:
                    create_payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(create_payload["ok"])
                self.assertEqual(create_payload["data"]["id"], 9)

                missing_token = urllib.request.Request(
                    f"{base_url}/api/withdrawals",
                    data=json.dumps({"amount": "1.00", "wallet_address": "0xdef"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as missing_token_error:
                    urllib.request.urlopen(missing_token, timeout=5)
                self.assertEqual(missing_token_error.exception.code, 403)
                missing_token_error.exception.read()
                missing_token_error.exception.close()

                bad_content_type = urllib.request.Request(
                    f"{base_url}/api/withdrawals",
                    data=b"amount=1.00",
                    headers={"Content-Type": "text/plain", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as bad_type_error:
                    urllib.request.urlopen(bad_content_type, timeout=5)
                self.assertEqual(bad_type_error.exception.code, 400)
                bad_type_error.exception.read()
                bad_type_error.exception.close()

                def failing_get(url, params=None, timeout=10):
                    get_calls.append((url, params, timeout))
                    return FakeResponse({"code": 400, "msg": "节点身份校验失败"}, status_code=400)

                def failing_post(url, json=None, timeout=10):
                    post_calls.append((url, json, timeout))
                    return FakeResponse({"code": 400, "msg": "可提现余额不足"}, status_code=400)

                client_module.requests = types.SimpleNamespace(get=failing_get, post=failing_post)
                with self.assertRaises(urllib.error.HTTPError) as earnings_error:
                    urllib.request.urlopen(f"{base_url}/api/earnings", timeout=5)
                self.assertEqual(earnings_error.exception.code, 400)
                earnings_body = json.loads(earnings_error.exception.read().decode("utf-8"))
                earnings_error.exception.close()
                self.assertFalse(earnings_body["ok"])
                self.assertEqual(earnings_body["error"], "节点身份校验失败")

                failing_withdrawal = urllib.request.Request(
                    f"{base_url}/api/withdrawals",
                    data=json.dumps({"amount": "999", "wallet_address": "0xabc"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as withdrawal_error:
                    urllib.request.urlopen(failing_withdrawal, timeout=5)
                self.assertEqual(withdrawal_error.exception.code, 400)
                withdrawal_body = json.loads(withdrawal_error.exception.read().decode("utf-8"))
                withdrawal_error.exception.close()
                self.assertFalse(withdrawal_body["ok"])
                self.assertEqual(withdrawal_body["error"], "可提现余额不足")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(
                get_calls[:2],
                [
                    ("http://server.example/api/node/earnings", {"user_addr": "NODE_A", "node_mac": "MAC_A"}, 10),
                    ("http://server.example/api/node/withdrawals", {"user_addr": "NODE_A", "node_mac": "MAC_A"}, 10),
                ],
            )
            self.assertEqual(len(get_calls), 3)
            self.assertEqual(len(post_calls), 2)
            self.assertEqual(post_calls[0][0], "http://server.example/api/node/withdrawals")
            self.assertEqual(
                post_calls[0][1],
                {
                    "user_addr": "NODE_A",
                    "node_mac": "MAC_A",
                    "amount": "5.00",
                    "wallet_address": "0xabc",
                    "withdrawal_channel": "bank",
                    "withdrawal_account": "acct-1",
                },
            )
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_console_stop_and_restart_controls_are_safe_in_dev(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/node", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                stop_request = urllib.request.Request(
                    f"{base_url}/api/control/stop",
                    data=b"{}",
                    headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with urllib.request.urlopen(stop_request, timeout=5) as response:
                    stop_payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(stop_payload["ok"])
                self.assertFalse(state["running"])

                restart_request = urllib.request.Request(
                    f"{base_url}/api/control/restart",
                    data=b"{}",
                    headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with urllib.request.urlopen(restart_request, timeout=5) as response:
                    restart_payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(restart_payload["ok"])
                self.assertIn("开发模式暂不支持自动重启", restart_payload["message"])
                self.assertFalse(state["running"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_console_status_payload_includes_capacity(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/node", 8787)
            state["storage"] = {"storage_status":"ok","storage_total_gb":100,"storage_used_gb":20,"storage_free_gb":80}
            payload = client_module.client_status_payload(state)
            self.assertEqual(payload["storage"]["storage_free_gb"], 80)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_heartbeat_payload_uses_state_storage_dir(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            inspected = []

            def fake_inspect(storage_dir):
                inspected.append(storage_dir)
                return {
                    "storage_status": "ok",
                    "storage_total_gb": 200,
                    "storage_used_gb": 30,
                    "storage_free_gb": 170,
                }

            client_module.inspect_storage_dir = fake_inspect
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
            inspected.clear()
            state["storage_dir"] = "D:/new"

            payload = client_module.build_heartbeat_payload(state, 1.5)

            self.assertEqual(inspected, ["D:/new"])
            self.assertEqual(payload["disk_used"], 30)
            self.assertEqual(state["storage"]["storage_free_gb"], 170)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_heartbeat_http_error_updates_failure_state(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            client_module.inspect_storage_dir = lambda storage_dir: {
                "storage_status": "ok",
                "storage_total_gb": 100,
                "storage_used_gb": 20,
                "storage_free_gb": 80,
            }
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/node", 8787)
            state["last_heartbeat"] = ""

            response = types.SimpleNamespace(status_code=500, text="server error")
            ok, payload = client_module.report_heartbeat(state, 2.0, post_func=lambda *args, **kwargs: response)

            self.assertFalse(ok)
            self.assertEqual(payload["disk_used"], 20)
            self.assertTrue(state["running"])
            self.assertFalse(state["heartbeat_ok"])
            self.assertEqual(state["last_heartbeat"], "")
            self.assertIn("500", state["last_error"])
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_shard_write_read_round_trip(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            file_hash = "a" * 64
            chunk = b"encrypted-shard"
            chunk_hash = client_module.hashlib.sha256(chunk).hexdigest()
            with tempfile.TemporaryDirectory() as tmp:
                metadata = client_module.write_local_shard(
                    tmp,
                    "NODE_A",
                    "MAC_A",
                    file_hash,
                    0,
                    1,
                    chunk,
                    chunk_hash,
                )

                self.assertEqual(metadata["chunk_hash"], chunk_hash)
                self.assertEqual(client_module.read_local_shard(tmp, file_hash, 0), chunk)
                manifest = client_module.read_local_manifest(tmp, file_hash)
                self.assertEqual(manifest["chunks"]["0"]["chunk_size"], len(chunk))
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_shard_path_rejects_invalid_hash_and_index(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    client_module.write_local_shard(tmp, "NODE_A", "MAC_A", "../bad", 0, 1, b"x")
                with self.assertRaises(ValueError):
                    client_module.write_local_shard(tmp, "NODE_A", "MAC_A", "a" * 64, -1, 1, b"x")
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_management_storage_shard_routes_round_trip(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            file_hash = "b" * 64
            chunk = b"route-shard"
            chunk_hash = client_module.hashlib.sha256(chunk).hexdigest()
            with tempfile.TemporaryDirectory() as tmp:
                state = client_module.create_client_state(
                    "http://server",
                    "NODE_A",
                    "MAC_A",
                    tmp,
                    8787,
                    10,
                    True,
                )
                server = client_module.ThreadingHTTPServer(
                    ("127.0.0.1", 0),
                    client_module.make_manage_handler(state),
                )
                thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    write_request = urllib.request.Request(
                        f"{base_url}/api/node/storage/shards",
                        data=json.dumps({
                            "file_hash": file_hash,
                            "chunk_index": 0,
                            "chunk_total": 1,
                            "chunk_b64": base64.b64encode(chunk).decode("ascii"),
                            "chunk_hash": chunk_hash,
                        }).encode("utf-8"),
                        headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                        method="POST",
                    )
                    with urllib.request.urlopen(write_request, timeout=5) as response:
                        write_payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(write_payload["ok"])

                    with urllib.request.urlopen(
                        f"{base_url}/api/node/storage/shards/{file_hash}/0",
                        timeout=5,
                    ) as response:
                        read_payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(base64.b64decode(read_payload["data"]["chunk_b64"]), chunk)
                    self.assertEqual(read_payload["data"]["chunk_hash"], chunk_hash)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_management_routes_return_console_status_and_storage_updates(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            inspected = []

            def fake_inspect(storage_dir):
                inspected.append(storage_dir)
                used = 20 if storage_dir == "D:/node" else 40
                return {
                    "storage_path": storage_dir,
                    "storage_status": "ok",
                    "storage_total_gb": 100,
                    "storage_used_gb": used,
                    "storage_free_gb": 100 - used,
                }

            client_module.inspect_storage_dir = fake_inspect
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/node", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("节点控制台", html)
                self.assertIn(state["csrf_token"], html)

                with urllib.request.urlopen(f"{base_url}/api/status?x=1", timeout=5) as response:
                    status_payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(status_payload["data"]["server_configured"])
                self.assertNotIn("server_url", status_payload["data"])
                self.assertNotIn("user_addr", status_payload["data"])
                self.assertNotIn("node_mac", status_payload["data"])
                self.assertEqual(status_payload["data"]["storage"]["storage_total_gb"], 100)
                self.assertEqual(status_payload["data"]["storage"]["storage_free_gb"], 80)

                storage_request = urllib.request.Request(
                    f"{base_url}/api/storage",
                    data=json.dumps({"storage_dir": "D:/new"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with urllib.request.urlopen(storage_request, timeout=5) as response:
                    storage_payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(state["storage_dir"], "D:/new")
                self.assertEqual(storage_payload["data"]["storage"]["storage_path"], "D:/new")
                self.assertEqual(storage_payload["data"]["storage"]["storage_used_gb"], 40)

                refresh_request = urllib.request.Request(
                    f"{base_url}/api/refresh",
                    data=b"{}",
                    headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with urllib.request.urlopen(refresh_request, timeout=5) as response:
                    refresh_payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(refresh_payload["data"]["storage"]["storage_path"], "D:/new")
                self.assertEqual(refresh_payload["data"]["storage"]["storage_free_gb"], 60)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_route_update_feeds_next_heartbeat_payload(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            inspected = []

            def fake_inspect(storage_dir):
                inspected.append(storage_dir)
                used = 10 if storage_dir == "D:/old" else 55
                return {
                    "storage_path": storage_dir,
                    "storage_status": "ok",
                    "storage_total_gb": 120,
                    "storage_used_gb": used,
                    "storage_free_gb": 120 - used,
                }

            client_module.inspect_storage_dir = fake_inspect
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/storage",
                    data=json.dumps({"storage_dir": "D:/console"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-CSRF-Token": state["csrf_token"]},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)

                inspected.clear()
                heartbeat_payload = client_module.build_heartbeat_payload(state, 2.5)

                self.assertEqual(inspected, ["D:/console"])
                self.assertEqual(heartbeat_payload["storage_path"], "D:/console")
                self.assertEqual(heartbeat_payload["disk_used"], 55)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_run_starts_management_server_and_prints_local_url(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        old_argv = sys.argv[:]
        prints = []
        started_states = []
        posts = []

        class StopAfterHeartbeat(Exception):
            pass

        class FakeManageServer:
            def __init__(self):
                self.shutdown_called = False
                self.close_called = False

            def shutdown(self):
                self.shutdown_called = True

            def server_close(self):
                self.close_called = True

        fake_server = FakeManageServer()

        def fake_post(url, json=None, timeout=10):
            posts.append((url, json, timeout))
            return types.SimpleNamespace(status_code=200)

        try:
            sys.argv = ["client.py"]
            sys.modules["requests"] = types.SimpleNamespace(post=fake_post, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            client_module.load_client_config = lambda: {
                "server_url": "http://example.com",
                "parent_invite": "",
                "heartbeat_interval": 60,
                "reconnect_interval": 1,
                "storage_dir": "D:/node",
                "manage_port": 8899,
            }
            client_module.get_device_mac = lambda: "MAC_A"
            client_module.wait_for_registration = lambda *args, **kwargs: True
            client_module.inspect_storage_dir = lambda storage_dir: {
                "storage_status": "ok",
                "storage_total_gb": 100,
                "storage_used_gb": 20,
                "storage_free_gb": 80,
            }
            client_module.random.uniform = lambda *args, **kwargs: 1.0
            client_module.safe_print = lambda message: prints.append(message)

            def fake_start_manage_server(state):
                started_states.append(dict(state))
                return fake_server

            client_module.start_manage_server = fake_start_manage_server
            client_module.time.sleep = lambda seconds: (_ for _ in ()).throw(StopAfterHeartbeat())

            with self.assertRaises(StopAfterHeartbeat):
                client_module.client_run()

            self.assertEqual(started_states[0]["manage_port"], 8899)
            self.assertTrue(any("http://127.0.0.1:8899" in item for item in prints))
            self.assertTrue(any(url.endswith("/heartbeat") for url, _, _ in posts))
            self.assertTrue(fake_server.shutdown_called)
            self.assertTrue(fake_server.close_called)
        finally:
            sys.argv = old_argv
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_route_rejects_missing_token_and_preserves_state(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            client_module.inspect_storage_dir = lambda storage_dir: {
                "storage_path": storage_dir,
                "storage_status": "ok",
                "storage_total_gb": 100,
                "storage_used_gb": 20,
                "storage_free_gb": 80,
            }
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request(
                    "POST",
                    "/api/storage",
                    body=json.dumps({"storage_dir": "D:/new"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                body = json.loads(response.read().decode("utf-8"))
                connection.close()

                self.assertEqual(response.status, 403)
                self.assertFalse(body["ok"])
                self.assertEqual(state["storage_dir"], "D:/old")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_route_rejects_non_json_posts(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request(
                    "POST",
                    "/api/storage",
                    body=b"storage_dir=D:/new",
                    headers={"Content-Type": "text/plain", "X-CSRF-Token": state["csrf_token"]},
                )
                response = connection.getresponse()
                body = json.loads(response.read().decode("utf-8"))
                connection.close()

                self.assertEqual(response.status, 400)
                self.assertFalse(body["ok"])
                self.assertEqual(state["storage_dir"], "D:/old")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_route_rejects_invalid_content_length_cleanly(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.putrequest("POST", "/api/storage")
                connection.putheader("Content-Type", "application/json")
                connection.putheader("X-CSRF-Token", state["csrf_token"])
                connection.putheader("Content-Length", "not-a-number")
                connection.endheaders()

                response = connection.getresponse()
                body = json.loads(response.read().decode("utf-8"))

                self.assertEqual(response.status, 400)
                self.assertFalse(body["ok"])
                self.assertEqual(state["storage_dir"], "D:/old")
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_console_rejects_hostile_host_without_token_exposure(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                for host in (f"attacker.example:{server.server_port}", "[::1]evil"):
                    with self.subTest(host=host):
                        connection.putrequest("GET", "/", skip_host=True)
                        connection.putheader("Host", host)
                        connection.endheaders()

                        response = connection.getresponse()
                        body = response.read().decode("utf-8")

                        self.assertEqual(response.status, 403)
                        self.assertNotIn(state["csrf_token"], body)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_console_accepts_localhost_host(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
            server = client_module.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                client_module.make_manage_handler(state),
            )
            thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.putrequest("GET", "/", skip_host=True)
                connection.putheader("Host", f"localhost:{server.server_port}")
                connection.endheaders()

                response = connection.getresponse()
                body = response.read().decode("utf-8")

                self.assertEqual(response.status, 200)
                self.assertIn("节点控制台", body)
                self.assertIn(state["csrf_token"], body)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_route_rejects_hostile_origin_or_referer(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            client_module.inspect_storage_dir = lambda storage_dir: {
                "storage_path": storage_dir,
                "storage_status": "ok",
                "storage_total_gb": 100,
                "storage_used_gb": 20,
                "storage_free_gb": 80,
            }
            bad_headers = (
                ("Origin", "http://attacker.example/console"),
                ("Referer", "http://attacker.example/console"),
                ("Origin", "null"),
                ("Origin", "attacker.example"),
                ("Referer", "attacker.example/path"),
                ("Origin", "http://[::1"),
                ("Origin", "http://[::1]evil"),
            )
            for header_name, header_value in bad_headers:
                with self.subTest(header_name=header_name, header_value=header_value):
                    state = client_module.create_client_state("http://server", "NODE_A", "MAC_A", "D:/old", 8787)
                    server = client_module.ThreadingHTTPServer(
                        ("127.0.0.1", 0),
                        client_module.make_manage_handler(state),
                    )
                    thread = client_module.threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    try:
                        connection.request(
                            "POST",
                            "/api/storage",
                            body=json.dumps({"storage_dir": "D:/new"}).encode("utf-8"),
                            headers={
                                "Host": f"127.0.0.1:{server.server_port}",
                                "Content-Type": "application/json",
                                "X-CSRF-Token": state["csrf_token"],
                                header_name: header_value,
                            },
                        )
                        response = connection.getresponse()
                        body = json.loads(response.read().decode("utf-8"))

                        self.assertEqual(response.status, 403)
                        self.assertFalse(body["ok"])
                        self.assertEqual(state["storage_dir"], "D:/old")
                    finally:
                        connection.close()
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=5)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_probe_reports_unavailable_directory(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            client_module.get_local_disk_use = lambda storage_dir="": 0.1
            result = client_module.inspect_storage_dir("")
            self.assertEqual(result["storage_status"], "required")
            self.assertIn("storage_error", result)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_probe_preserves_existing_fixed_probe_file(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            with tempfile.TemporaryDirectory() as tmp:
                storage_dir = Path(tmp)
                existing_probe = storage_dir / ".filezall_write_probe"
                existing_probe.write_text("user data", encoding="utf-8")

                result = client_module.inspect_storage_dir(str(storage_dir))

                self.assertEqual(result["storage_status"], "ok")
                self.assertTrue(existing_probe.exists())
                self.assertEqual(existing_probe.read_text(encoding="utf-8"), "user data")
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_storage_probe_without_directory_preserves_ipfs_fallback(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        try:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            client_module.get_local_disk_use = lambda storage_dir="": 12.34

            result = client_module.inspect_storage_dir("")

            self.assertEqual(result["storage_status"], "required")
            self.assertEqual(result["storage_error"], "未指定存储目录")
            self.assertEqual(result["storage_used_gb"], 12.34)
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_does_not_auto_open_pywebview_map_by_default(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        old_env = {key: os.environ.get(key) for key in ("NODE_OPEN_MAP_WINDOW", "AMAP_WEB_KEY", "AMAP_SECURITY_JSCODE")}
        try:
            for key in old_env:
                os.environ.pop(key, None)
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = types.SimpleNamespace(
                create_window=lambda *args, **kwargs: None,
                start=lambda *args, **kwargs: None,
            )
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")

            self.assertFalse(client_module.should_open_map_window())
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_map_window_requires_amap_security_config(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        old_env = {key: os.environ.get(key) for key in ("AMAP_WEB_KEY", "AMAP_SECURITY_JSCODE")}
        windows = []
        try:
            for key in old_env:
                os.environ.pop(key, None)
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = types.SimpleNamespace(
                create_window=lambda title, html="", **kwargs: windows.append((title, html, kwargs)),
                start=lambda *args, **kwargs: None,
            )
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")

            client_module.open_map_window()

            self.assertTrue(windows)
            self.assertNotIn("webapi.amap.com/maps?v=2.0&key=", windows[-1][1])
            self.assertIn("地图未启用", windows[-1][1])
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_run_reports_bad_storage_path_in_heartbeat(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        old_argv = sys.argv[:]
        heartbeat_payloads = []

        def fake_post(url, json=None, timeout=10):
            if url.endswith("/heartbeat"):
                heartbeat_payloads.append(json)
            return types.SimpleNamespace(status_code=200)

        try:
            sys.argv = ["client.py"]
            sys.modules["requests"] = types.SimpleNamespace(post=fake_post, get=lambda *args, **kwargs: None)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")
            with tempfile.TemporaryDirectory() as tmp:
                blocker = Path(tmp) / "not-a-dir"
                blocker.write_text("block mkdir", encoding="utf-8")
                bad_storage_dir = blocker / "child"
                client_module.load_client_config = lambda: {
                    "server_url": "http://example.com",
                    "parent_invite": "",
                    "heartbeat_interval": 60,
                    "reconnect_interval": 1,
                    "storage_dir": str(bad_storage_dir),
                    "manage_port": 8787,
                }
                client_module.wait_for_registration = lambda *args, **kwargs: True
                client_module.get_device_mac = lambda: "12345"
                client_module.random.uniform = lambda *args, **kwargs: 1.0
                client_module.time.sleep = lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt())

                with self.assertRaises(KeyboardInterrupt):
                    client_module.client_run()

            self.assertEqual(len(heartbeat_payloads), 1)
            self.assertEqual(heartbeat_payloads[0]["storage_status"], "unavailable")
            self.assertIn("storage_error", heartbeat_payloads[0])
        finally:
            sys.argv = old_argv
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_client_registration_retries_until_service_recovers(self):
        old_requests = sys.modules.get("requests")
        old_webview = sys.modules.get("webview")
        calls = []
        sleeps = []

        def fake_post(url, json=None, timeout=10):
            calls.append((url, json, timeout))
            if len(calls) == 1:
                raise RuntimeError("service down")
            return types.SimpleNamespace(status_code=200)

        try:
            sys.modules["requests"] = types.SimpleNamespace(post=fake_post)
            sys.modules["webview"] = None
            sys.modules.pop("client", None)
            client_module = importlib.import_module("client")

            registered = client_module.wait_for_registration(
                "http://server",
                "NODE_A",
                "MAC_A",
                "INV1",
                reconnect_interval=3,
                post_func=fake_post,
                sleep_func=lambda seconds: sleeps.append(seconds),
                max_attempts=2,
            )

            self.assertTrue(registered)
            self.assertEqual(len(calls), 2)
            self.assertEqual(sleeps, [3])
            self.assertEqual(calls[1][1]["parent_invite"], "INV1")
        finally:
            sys.modules.pop("client", None)
            if old_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = old_requests
            if old_webview is None:
                sys.modules.pop("webview", None)
            else:
                sys.modules["webview"] = old_webview

    def test_file_record_format_includes_access_and_download_fields(self):
        server_main = load_server_main()
        row = (
            1,
            "demo.txt",
            "hash1",
            "cid1",
            1.25,
            2,
            "NODE_A",
            '["NODE_A","NODE_B"]',
            server_main.datetime.now(),
            "private",
            "token123",
            None,
        )

        record = server_main.format_file_record(row)

        self.assertEqual(record["file_name"], "demo.txt")
        self.assertEqual(record["visibility"], "private")
        self.assertEqual(record["access_token"], "token123")
        self.assertEqual(record["download_url"], "/api/file_download/hash1?token=token123")
        self.assertEqual(record["nodes"], ["NODE_A", "NODE_B"])

    def test_user_file_record_format_includes_owner_and_download_fields(self):
        files = importlib.import_module("files")
        now = importlib.import_module("datetime").datetime.now()
        row = (
            1,
            "demo.txt",
            "hash",
            "cid",
            2.5,
            3,
            "NODE_A",
            "[]",
            now,
            "public",
            "",
            None,
            7,
            "0xabc",
            4,
            now,
        )

        record = files.format_user_file_record(row)

        self.assertEqual(record["owner_user_id"], 7)
        self.assertEqual(record["download_count"], 4)
        self.assertEqual(record["file_name"], "demo.txt")
        self.assertEqual(record["download_url"], "")

    def test_user_files_requires_user_token(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/api/user/files")

        self.assertEqual(response.status_code, 401)

    def test_user_withdrawal_create_uses_current_user_wallet_and_available_earnings(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                lowered = self.last_sql.lower()
                if "from app_user" in lowered and "for update" in lowered:
                    return (7,)
                if "from app_user" in lowered:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from point_ledger" in lowered:
                    return (250,)
                if "status='paid'" in lowered:
                    return (0,)
                if "status in ('pending','approved')" in lowered:
                    return (1,)
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = types.SimpleNamespace(commit=lambda: None, rollback=lambda: None)
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/user/withdrawals",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": "1.500000", "user_id": 999, "wallet_address": "0xevil"},
        )

        self.assertEqual(response.status_code, 200)
        insert_queries = [
            params
            for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("insert into withdrawal_request")
        ]
        self.assertEqual(insert_queries[-1][:3], (7, "0xabc", "1.500000"))
        executed_sql = [sql.lower() for sql, _ in fake_cursor.executed]
        lock_index = next(i for i, sql in enumerate(executed_sql) if "from app_user" in sql and "for update" in sql)
        point_index = next(i for i, sql in enumerate(executed_sql) if "from point_ledger" in sql)
        insert_index = next(i for i, sql in enumerate(executed_sql) if sql.strip().startswith("insert into withdrawal_request"))
        self.assertLess(lock_index, point_index)
        self.assertLess(lock_index, insert_index)

    def test_user_withdrawal_over_withdraw_returns_400_without_insert(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                lowered = self.last_sql.lower()
                if "from app_user" in lowered and "for update" in lowered:
                    return (7,)
                if "from app_user" in lowered:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from point_ledger" in lowered:
                    return (100,)
                if "from withdrawal_request" in lowered:
                    return (0,)
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = types.SimpleNamespace(commit=lambda: None, rollback=lambda: None)
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/user/withdrawals",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 2},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["msg"], "可提现余额不足")
        self.assertFalse(any(
            sql.strip().lower().startswith("insert into withdrawal_request")
            for sql, _ in fake_cursor.executed
        ))

    def test_user_withdrawal_tiny_amount_returns_400_without_insert(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql.lower():
                    return (7, "alice", "hash", "0xabc", "active")
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = types.SimpleNamespace(commit=lambda: None, rollback=lambda: None)
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/user/withdrawals",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": "1e-400"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["msg"], "提现金额不能小于0.000001")
        self.assertFalse(any(
            sql.strip().lower().startswith("insert into withdrawal_request")
            for sql, _ in fake_cursor.executed
        ))

    def test_calculate_user_earnings_reports_withdrawn_and_pending_breakdown(self):
        server_main = load_server_main()

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql.lower()

            def fetchone(self):
                if "from point_ledger" in self.last_sql:
                    return (250,)
                if "status='paid'" in self.last_sql:
                    return (1,)
                if "status in ('pending','approved')" in self.last_sql:
                    return (0.5,)
                return (0,)

        server_main.cursor = FakeCursor()

        summary = server_main.calculate_user_earnings(7)

        self.assertEqual(summary["total_earnings"], 2.5)
        self.assertEqual(summary["withdrawn_earnings"], 1.0)
        self.assertEqual(summary["pending_withdrawals"], 0.5)
        self.assertEqual(summary["locked_withdrawals"], 1.5)
        self.assertEqual(summary["available_earnings"], 1.0)

    def test_format_withdrawal_row_supports_legacy_and_node_fields(self):
        server_main = load_server_main()

        legacy = server_main.format_withdrawal_row((
            1,
            7,
            "0xwallet",
            1.5,
            "pending",
            "",
            server_main.datetime(2026, 6, 27, 12, 0, 0),
            None,
        ))
        current = server_main.format_withdrawal_row((
            2,
            None,
            "0xnode-wallet",
            2.5,
            "approved",
            "ok",
            server_main.datetime(2026, 6, 27, 12, 1, 0),
            server_main.datetime(2026, 6, 27, 12, 2, 0),
            "NODE_A",
            "wallet",
            "0xnode-wallet",
        ))

        self.assertEqual(legacy["node_address"], "")
        self.assertEqual(legacy["withdrawal_channel"], "wallet")
        self.assertEqual(legacy["withdrawal_account"], "")
        self.assertEqual(current["node_address"], "NODE_A")
        self.assertEqual(current["withdrawal_channel"], "wallet")
        self.assertEqual(current["withdrawal_account"], "0xnode-wallet")

    def test_node_identity_requires_registered_mac_pair(self):
        server_main = load_server_main()

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""
                self.executed = []

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                return None

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get(
            "/api/node/me?user_addr=NODE_A&node_mac=BAD"
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], 401)

    def test_node_me_maps_identity_fields_without_column_shift(self):
        server_main = load_server_main()
        identity_time = server_main.datetime(2026, 6, 27, 12, 3, 4)

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                if "from user_node" in self.last_sql.lower() and "join node_power" in self.last_sql.lower():
                    return (
                        "NODE_A",
                        "INVITE1",
                        "PARENT1",
                        "MAC_A",
                        512.0,
                        128.0,
                        42,
                        8.5,
                        identity_time,
                        "/data/node-a",
                        "ready",
                        "none",
                        600.0,
                        256.0,
                        344.0,
                    )
                return None

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get(
            "/api/node/me?user_addr=NODE_A&node_mac=MAC_A"
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["node_mac"], "MAC_A")
        self.assertEqual(data["update_time"], str(identity_time))
        self.assertEqual(data["storage_path"], "/data/node-a")
        self.assertEqual(data["storage_status"], "ready")
        self.assertEqual(data["storage_error"], "none")
        self.assertEqual(data["storage_total_gb"], 600.0)
        self.assertEqual(data["storage_used_gb"], 256.0)
        self.assertEqual(data["storage_free_gb"], 344.0)

    def test_calculate_node_earnings_reports_withdrawn_and_pending_breakdown(self):
        server_main = load_server_main()

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql.lower()

            def fetchone(self):
                if "from node_reward" in self.last_sql:
                    return (10,)
                if "status='paid'" in self.last_sql:
                    return (2,)
                if "status in ('pending','approved')" in self.last_sql:
                    return (1.5,)
                return (0,)

        server_main.cursor = FakeCursor()

        summary = server_main.calculate_node_earnings("NODE_A")

        self.assertEqual(summary["node_address"], "NODE_A")
        self.assertEqual(summary["total_earnings"], 10.0)
        self.assertEqual(summary["withdrawn_earnings"], 2.0)
        self.assertEqual(summary["pending_withdrawals"], 1.5)
        self.assertEqual(summary["locked_withdrawals"], 3.5)
        self.assertEqual(summary["available_earnings"], 6.5)

    def test_node_withdrawal_create_inserts_node_request(self):
        server_main = load_server_main()
        identity_time = server_main.datetime(2026, 6, 27, 12, 0, 0)

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                lowered = self.last_sql.lower()
                if "from user_node" in lowered and "join node_power" in lowered:
                    return (
                        "NODE_A",
                        "INVITE1",
                        "PARENT1",
                        "MAC_A",
                        512.0,
                        128.0,
                        42,
                        8.5,
                        identity_time,
                        "/data/node-a",
                        "ready",
                        "none",
                        256.0,
                        128.0,
                        128.0,
                    )
                if "from node_reward" in lowered:
                    return (10,)
                if "status='paid'" in lowered:
                    return (2,)
                if "status in ('pending','approved')" in lowered:
                    return (1.5,)
                if "for update" in lowered:
                    return (0,)
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = types.SimpleNamespace(
            commit=lambda: None,
            rollback=lambda: None,
            get_autocommit=lambda: True,
            autocommit=lambda value: None,
            begin=lambda: None,
        )
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            "/api/node/withdrawals",
            json={
                "user_addr": "NODE_A",
                "node_mac": "MAC_A",
                "wallet_address": "0xnode-wallet",
                "amount": "2.500000",
            },
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.get_json()["data"]
        self.assertEqual(response_data["node_address"], "NODE_A")
        self.assertEqual(response_data["wallet_address"], "0xnode-wallet")
        self.assertEqual(response_data["withdrawal_account"], "0xnode-wallet")
        insert_queries = [
            params
            for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("insert into withdrawal_request")
        ]
        self.assertTrue(insert_queries)
        self.assertIn(insert_queries[-1][0], (None, 0))
        self.assertEqual(
            insert_queries[-1][1:],
            ("0xnode-wallet", "2.500000", "pending", "NODE_A", "wallet", "0xnode-wallet"),
        )
        node_me = server_main.app.test_client().get(
            "/api/node/me?user_addr=NODE_A&node_mac=MAC_A"
        )
        self.assertEqual(node_me.status_code, 200)
        identity = node_me.get_json()["data"]
        self.assertEqual(identity["node_mac"], "MAC_A")
        self.assertEqual(identity["update_time"], str(identity_time))
        self.assertEqual(identity["storage_path"], "/data/node-a")
        self.assertEqual(identity["storage_status"], "ready")
        self.assertEqual(identity["storage_error"], "none")
        self.assertEqual(identity["storage_total_gb"], 256.0)
        self.assertEqual(identity["storage_used_gb"], 128.0)
        self.assertEqual(identity["storage_free_gb"], 128.0)
        executed_sql = [sql.lower() for sql, _ in fake_cursor.executed]
        lock_index = next(i for i, sql in enumerate(executed_sql) if "for update" in sql and "from user_node" in sql)
        paid_index = next(i for i, sql in enumerate(executed_sql) if "from withdrawal_request" in sql and "status='paid'" in sql)
        pending_index = next(i for i, sql in enumerate(executed_sql) if "from withdrawal_request" in sql and "status in ('pending','approved')" in sql)
        insert_index = next(i for i, sql in enumerate(executed_sql) if sql.strip().startswith("insert into withdrawal_request"))
        self.assertLess(lock_index, paid_index)
        self.assertLess(lock_index, pending_index)
        self.assertLess(lock_index, insert_index)

    def test_admin_withdrawals_requires_admin_token(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/api/admin/withdrawals")

        self.assertEqual(response.status_code, 401)

    def test_admin_withdrawal_review_rejects_invalid_transitions(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        class FakeCursor:
            def __init__(self, current_status):
                self.current_status = current_status
                self.last_sql = ""
                self.executed = []
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from withdrawal_request" in self.last_sql.lower():
                    return (9, self.current_status)
                return None

        for current_status, target_status in (("paid", "rejected"), ("pending", "pending")):
            fake_cursor = FakeCursor(current_status)
            server_main.cursor = fake_cursor
            server_main.db = types.SimpleNamespace(commit=lambda: None, rollback=lambda: None)
            server_main.init_db = lambda: True

            response = server_main.app.test_client().post(
                "/api/admin/withdrawals/9/review",
                headers={"X-Admin-Token": "secret-token"},
                json={"status": target_status},
            )

            self.assertEqual(response.status_code, 400)
            self.assertFalse(any(
                sql.strip().lower().startswith("update withdrawal_request")
                for sql, _ in fake_cursor.executed
            ))

    def test_admin_withdrawal_review_allows_valid_transitions(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        class FakeCursor:
            def __init__(self, current_status):
                self.current_status = current_status
                self.last_sql = ""
                self.executed = []
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from withdrawal_request" in self.last_sql.lower():
                    return (9, self.current_status)
                return None

        for current_status, target_status in (("pending", "approved"), ("approved", "paid")):
            fake_cursor = FakeCursor(current_status)
            server_main.cursor = fake_cursor
            server_main.db = types.SimpleNamespace(commit=lambda: None, rollback=lambda: None)
            server_main.init_db = lambda: True

            response = server_main.app.test_client().post(
                "/api/admin/withdrawals/9/review",
                headers={"X-Admin-Token": "secret-token"},
                json={"status": target_status},
            )

            self.assertEqual(response.status_code, 200)
            update_params = [
                params
                for sql, params in fake_cursor.executed
                if sql.strip().lower().startswith("update withdrawal_request")
            ]
            self.assertEqual(update_params[-1][0], target_status)

    def test_user_upload_page_posts_to_user_file_api_with_bearer_token(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/user/upload?campaign=summer")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("/api/user/files", body)
        self.assertIn('/api/user/files/${encodeURIComponent(fileHash)}/shares', body)
        self.assertIn("/s/", body)
        self.assertIn("Authorization", body)
        self.assertIn("user_token", body)
        self.assertIn("requireUserLogin", body)
        self.assertIn("redirectToLogin", body)
        self.assertIn('searchParams.set("next"', body)
        self.assertIn('window.location.href = loginUrl.toString()', body)

    def test_user_login_page_renders_forms_and_token_storage(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/user/login")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("钱包登录", body)
        for marker in (
            'data-auth-tab="login"',
            'data-auth-tab="register"',
            'data-auth-tab="phone"',
            'data-auth-tab="email"',
            'data-auth-tab="wallet"',
            'data-auth-tab="wechat"',
            'data-auth-tab="qq"',
            'id="loginPanel"',
            'id="registerPanel"',
            'id="phonePanel"',
            'id="emailPanel"',
            'id="walletPanel"',
            'id="wechatPanel"',
            'id="qqPanel"',
            "switchAuthTab",
            "redirectAfterLogin",
            "URLSearchParams",
        ):
            self.assertIn(marker, body)
        for provider in ("163.com", "gmail.com", "outlook.com", "icloud.com"):
            self.assertIn(provider, body)
        self.assertIn("/api/auth/register", body)
        self.assertIn("/api/auth/login", body)
        self.assertIn("/api/wallet/login", body)
        self.assertIn("saveSession(payload, true)", body)
        self.assertIn('localStorage.setItem("user_token"', body)

    def test_user_dashboard_page_uses_user_product_apis(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/user/dashboard")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        for api_path in (
            "/api/auth/me",
            "/api/user/files",
            "/api/user/shares",
            "/api/user/points",
            "/api/user/earnings",
            "/api/user/withdrawals",
        ):
            self.assertIn(api_path, body)
        self.assertIn("user_token", body)

    def test_public_share_page_downloads_with_inline_extract_code(self):
        server_main = load_server_main(SESSION_SECRET="session-secret")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/s/demo-share")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("下载", body)
        self.assertIn("/api/share/demo-share", body)
        self.assertIn("/api/share/${encodeURIComponent(shareCode)}/download", body)
        self.assertIn("extract_code", body)

    def test_user_files_list_selects_only_current_owner(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        now = server_main.datetime.now()
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                return None

            def fetchall(self):
                return [(
                    1,
                    "demo.txt",
                    "hash",
                    "cid",
                    2.5,
                    3,
                    "NODE_A",
                    "[]",
                    now,
                    "public",
                    "",
                    None,
                    7,
                    "0xabc",
                    4,
                    now,
                )]

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.init_db = lambda: True
        response = server_main.app.test_client().get(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"][0]["owner_user_id"], 7)
        file_queries = [
            (sql, params)
            for sql, params in fake_cursor.executed
            if "from file_chain_record" in sql
        ]
        self.assertEqual(file_queries[-1][1], (7,))
        self.assertIn("owner_user_id=%s", file_queries[-1][0])
        self.assertIn("deleted_at is null", file_queries[-1][0])

    def test_user_file_upload_duplicate_returns_409_before_ipfs(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        now = server_main.datetime.now()
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        duplicate_hash = "a" * 64
        ipfs_called = []

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return (
                        1,
                        "demo.txt",
                        duplicate_hash,
                        "cid",
                        2.5,
                        3,
                        "NODE_A",
                        "[]",
                        now,
                        "public",
                        "",
                        None,
                        7,
                        "0xabc",
                        4,
                        now,
                    )
                return None

        server_main.cursor = FakeCursor()
        server_main.db = types.SimpleNamespace(commit=lambda: None)
        server_main.init_db = lambda: True
        server_main.aes_encrypt = lambda data: b"encrypted"
        server_main.file_shard = lambda data: [data]
        server_main.get_file_hash = lambda data: duplicate_hash

        def fail_if_called():
            ipfs_called.append(True)
            raise AssertionError("IPFS should not be called for duplicate uploads")

        server_main.get_ipfs_client = fail_if_called

        response = server_main.app.test_client().post(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(b"plain"), "demo.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.content_type, "application/json")
        self.assertIn("文件已存在", response.get_json()["msg"])
        self.assertFalse(ipfs_called)

    def test_build_encrypted_shard_manifest_records_hashes(self):
        server_main = load_server_main()
        old_shard_size = server_main.SHARD_SIZE
        try:
            server_main.SHARD_SIZE = 4
            encrypted = b"abcdefghij"
            manifest = server_main.build_encrypted_shard_manifest("a" * 64, encrypted)

            self.assertEqual(manifest["file_hash"], "a" * 64)
            self.assertEqual(manifest["encrypted_hash"], server_main.hashlib.sha256(encrypted).hexdigest())
            self.assertEqual(len(manifest["shards"]), 3)
            self.assertEqual(manifest["shards"][0]["chunk_hash"], server_main.hashlib.sha256(b"abcd").hexdigest())
            self.assertEqual(manifest["shards"][2]["chunk_size"], 2)
        finally:
            server_main.SHARD_SIZE = old_shard_size

    def test_persist_file_to_storage_nodes_dispatches_shards_to_clients(self):
        server_main = load_server_main()
        old_shard_size = server_main.SHARD_SIZE
        sent = []
        fallback_writes = []
        try:
            server_main.SHARD_SIZE = 4
            server_main.write_server_fallback_copy = lambda file_hash, encrypted_data: fallback_writes.append((file_hash, encrypted_data))
            server_main.post_client_shard = lambda node, shard, request_id="": sent.append((node, shard["chunk_index"], shard["chunk_bytes"])) or True

            stored_nodes = server_main.persist_file_to_storage_nodes("b" * 64, b"abcdefgh", ["NODE_A", "NODE_B"])

            self.assertEqual(stored_nodes, ["NODE_A", "NODE_B"])
            self.assertEqual(fallback_writes, [("b" * 64, b"abcdefgh")])
            self.assertEqual(sent, [("NODE_A", 0, b"abcd"), ("NODE_B", 1, b"efgh")])
        finally:
            server_main.SHARD_SIZE = old_shard_size

    def test_persist_file_to_storage_nodes_requires_real_client_success(self):
        server_main = load_server_main()
        server_main.write_server_fallback_copy = lambda file_hash, encrypted_data: None
        server_main.post_client_shard = lambda node, shard, request_id="": False

        with self.assertRaisesRegex(RuntimeError, "真实客户端"):
            server_main.persist_file_to_storage_nodes("c" * 64, b"encrypted", ["NODE_A"])

    def test_user_file_upload_db_failure_rolls_back(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        new_hash = "b" * 64
        rolled_back = []

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                if sql.strip().lower().startswith("update node_power"):
                    raise Exception("node update failed")

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return None
                return None

        class FakeConnection:
            def commit(self):
                raise AssertionError("commit should not happen after mutation failure")

            def rollback(self):
                rolled_back.append(True)

        class FakeIPFSClient:
            def add_bytes(self, data):
                return "cid"

            def close(self):
                pass

        server_main.cursor = FakeCursor()
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.aes_encrypt = lambda data: b"encrypted"
        server_main.file_shard = lambda data: [data]
        server_main.get_file_hash = lambda data: new_hash
        server_main.get_backup_nodes = lambda: ["NODE_A"]
        server_main.persist_file_to_storage_nodes = lambda file_hash, encrypted, nodes: nodes
        server_main.get_ipfs_client = lambda: FakeIPFSClient()

        response = server_main.app.test_client().post(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(b"plain"), "demo.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content_type, "application/json")
        self.assertTrue(rolled_back)

    def test_user_file_upload_uses_transaction_and_restores_autocommit(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        new_hash = "c" * 64

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return None
                return None

        class FakeConnection:
            def __init__(self):
                self.autocommit_state = True
                self.events = []

            def get_autocommit(self):
                self.events.append(("get_autocommit", self.autocommit_state))
                return self.autocommit_state

            def autocommit(self, value):
                self.autocommit_state = value
                self.events.append(("autocommit", value))

            def commit(self):
                self.events.append(("commit", self.autocommit_state))

            def rollback(self):
                self.events.append(("rollback", self.autocommit_state))

        class FakeIPFSClient:
            def add_bytes(self, data):
                return "cid"

            def close(self):
                pass

        fake_db = FakeConnection()
        server_main.cursor = FakeCursor()
        server_main.db = fake_db
        server_main.init_db = lambda: True
        server_main.aes_encrypt = lambda data: b"encrypted"
        server_main.file_shard = lambda data: [data]
        server_main.get_file_hash = lambda data: new_hash
        server_main.get_backup_nodes = lambda: ["NODE_A"]
        server_main.persist_file_to_storage_nodes = lambda file_hash, encrypted, nodes: nodes
        server_main.get_ipfs_client = lambda: FakeIPFSClient()

        response = server_main.app.test_client().post(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(b"plain"), "demo.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(("autocommit", False), fake_db.events)
        self.assertIn(("commit", False), fake_db.events)
        self.assertEqual(fake_db.events[-1], ("autocommit", True))

    def test_user_file_upload_uses_user_nodes_when_ipfs_backup_fails(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        new_hash = "f" * 64
        stored_payloads = []

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""
                self.executed = []

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return None
                return None

        class FakeConnection:
            def __init__(self):
                self.autocommit_state = True

            def get_autocommit(self):
                return self.autocommit_state

            def autocommit(self, value):
                self.autocommit_state = value

            def commit(self):
                pass

            def rollback(self):
                pass

        server_main.cursor = FakeCursor()
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.aes_encrypt = lambda data: b"encrypted"
        server_main.file_shard = lambda data: [data]
        server_main.get_file_hash = lambda data: new_hash
        server_main.get_backup_nodes = lambda: ["NODE_A", "NODE_B", "SERVER_BACKUP_NODE"]
        server_main.persist_file_to_storage_nodes = lambda file_hash, encrypted, nodes: stored_payloads.append((file_hash, encrypted, nodes)) or nodes
        server_main.get_ipfs_client = lambda: (_ for _ in ()).throw(Exception("ipfs down"))

        response = server_main.app.test_client().post(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(b"plain"), "demo.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["storage_nodes"], ["NODE_A", "NODE_B"])
        self.assertEqual(payload["ipfs_backup_status"], "failed")
        self.assertEqual(payload["ipfs_cid"], "")
        self.assertEqual(stored_payloads, [(new_hash, b"encrypted", ["NODE_A", "NODE_B"])])
        insert_params = [
            params
            for sql, params in server_main.cursor.executed
            if sql.strip().lower().startswith("insert into file_chain_record")
        ][0]
        self.assertEqual(insert_params[2], "")
        self.assertEqual(json.loads(insert_params[6]), ["NODE_A", "NODE_B"])

    def test_user_file_upload_records_shard_metadata_and_audit(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        new_hash = "d" * 64

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""
                self.executed = []

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return None
                return None

        class FakeConnection:
            def __init__(self):
                self.autocommit_state = True

            def get_autocommit(self):
                return self.autocommit_state

            def autocommit(self, value):
                self.autocommit_state = value

            def commit(self):
                pass

            def rollback(self):
                pass

        class FakeIPFSClient:
            def add_bytes(self, data):
                return "cid"

            def close(self):
                pass

        old_shard_size = server_main.SHARD_SIZE
        try:
            server_main.SHARD_SIZE = 4
            server_main.cursor = FakeCursor()
            server_main.db = FakeConnection()
            server_main.init_db = lambda: True
            server_main.aes_encrypt = lambda data: b"abcdefgh"
            server_main.get_file_hash = lambda data: new_hash
            server_main.get_backup_nodes = lambda: ["NODE_A"]
            server_main.persist_file_to_storage_nodes = lambda file_hash, encrypted, nodes, request_id="": ["NODE_A"]
            server_main.get_ipfs_client = lambda: FakeIPFSClient()

            response = server_main.app.test_client().post(
                "/api/user/files",
                headers={"Authorization": f"Bearer {token}"},
                data={"file": (io.BytesIO(b"plain"), "demo.txt")},
                content_type="multipart/form-data",
            )
        finally:
            server_main.SHARD_SIZE = old_shard_size

        self.assertEqual(response.status_code, 200)
        shard_inserts = [
            params for sql, params in server_main.cursor.executed
            if sql.strip().lower().startswith("insert into file_shard_record")
        ]
        audit_inserts = [
            params for sql, params in server_main.cursor.executed
            if sql.strip().lower().startswith("insert into storage_audit_log")
        ]
        self.assertEqual(len(shard_inserts), 2)
        self.assertTrue(any(params[0] == "upload.sharded" for params in audit_inserts))
        self.assertTrue(any(params[0] == "fallback.ipfs.write.success" for params in audit_inserts))

    def test_user_file_upload_still_attempts_ipfs_after_real_node_success(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        new_hash = "e" * 64
        events = []

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return None
                return None

        class FakeConnection:
            def get_autocommit(self):
                return True

            def autocommit(self, value):
                pass

            def commit(self):
                pass

            def rollback(self):
                pass

        class FakeIPFSClient:
            def add_bytes(self, data):
                events.append("ipfs")
                return "cid"

            def close(self):
                pass

        server_main.cursor = FakeCursor()
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.aes_encrypt = lambda data: b"encrypted"
        server_main.file_shard = lambda data: [data]
        server_main.get_file_hash = lambda data: new_hash
        server_main.get_backup_nodes = lambda: ["NODE_A"]
        server_main.persist_file_to_storage_nodes = lambda file_hash, encrypted, nodes, request_id="": events.append("client") or ["NODE_A"]
        server_main.get_ipfs_client = lambda: FakeIPFSClient()

        response = server_main.app.test_client().post(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(b"plain"), "demo.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[:2], ["client", "ipfs"])

    def test_user_file_upload_requires_real_user_storage_nodes(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return None
                return None

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True
        server_main.aes_encrypt = lambda data: b"encrypted"
        server_main.file_shard = lambda data: [data]
        server_main.get_file_hash = lambda data: "a" * 64
        server_main.get_backup_nodes = lambda: ["SERVER_BACKUP_NODE"]
        server_main.persist_file_to_storage_nodes = lambda *args: self.fail("should not persist without user nodes")
        server_main.get_ipfs_client = lambda: self.fail("should not upload only to IPFS without user nodes")

        response = server_main.app.test_client().post(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(b"plain"), "demo.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("暂无可用用户节点", response.get_json()["msg"])

    def test_user_file_upload_duplicate_insert_failure_returns_409(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        duplicate_hash = "d" * 64
        rolled_back = []

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""
                self.insert_seen = False

            def execute(self, sql, params=None):
                self.last_sql = sql
                if sql.strip().lower().startswith("insert into file_chain_record"):
                    self.insert_seen = True
                    raise Exception("Duplicate entry 'hash' for key 'file_hash'")
                if sql.strip().lower().startswith("update node_power"):
                    raise AssertionError("node updates should not run after duplicate insert")

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return None
                return None

        class FakeConnection:
            def __init__(self):
                self.autocommit_state = True
                self.events = []

            def get_autocommit(self):
                self.events.append(("get_autocommit", self.autocommit_state))
                return self.autocommit_state

            def autocommit(self, value):
                self.autocommit_state = value
                self.events.append(("autocommit", value))

            def commit(self):
                raise AssertionError("commit should not happen after duplicate insert")

            def rollback(self):
                self.events.append(("rollback", self.autocommit_state))
                rolled_back.append(True)

        class FakeIPFSClient:
            def add_bytes(self, data):
                return "cid"

            def close(self):
                pass

        server_main.cursor = FakeCursor()
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.aes_encrypt = lambda data: b"encrypted"
        server_main.file_shard = lambda data: [data]
        server_main.get_file_hash = lambda data: duplicate_hash
        server_main.get_backup_nodes = lambda: ["NODE_A"]
        server_main.persist_file_to_storage_nodes = lambda file_hash, encrypted, nodes: nodes
        server_main.get_ipfs_client = lambda: FakeIPFSClient()

        response = server_main.app.test_client().post(
            "/api/user/files",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(b"plain"), "demo.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.content_type, "application/json")
        self.assertIn("文件已存在", response.get_json()["msg"])
        self.assertTrue(rolled_back)
        self.assertEqual(server_main.db.events[-2:], [("rollback", False), ("autocommit", True)])

    def test_user_file_detail_and_delete_reject_malformed_hash(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        detail_response = client.get(
            "/api/user/files/not-a-hash",
            headers={"Authorization": f"Bearer {token}"},
        )
        delete_response = client.delete(
            "/api/user/files/not-a-hash",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(detail_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 400)
        file_queries = [
            sql for sql, _ in fake_cursor.executed if "from file_chain_record" in sql
        ]
        self.assertEqual(file_queries, [])

    def test_create_share_requires_owned_file_and_hashes_extract_code(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        file_hash = "a" * 64

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return (file_hash, 7)
                return None

            def fetchall(self):
                return []

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = types.SimpleNamespace(commit=lambda: None)
        server_main.init_db = lambda: True

        response = server_main.app.test_client().post(
            f"/api/user/files/{file_hash}/shares",
            headers={"Authorization": f"Bearer {token}"},
            json={"extract_code": "ABCD", "max_downloads": 2},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["file_hash"], file_hash)
        self.assertTrue(data["share_url"].startswith("/s/"))
        self.assertTrue(data["extract_code_required"])
        self.assertNotIn("extract_code_hash", data)
        insert_params = [
            params for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("insert into file_share")
        ][0]
        self.assertEqual(insert_params[1], file_hash)
        self.assertEqual(insert_params[2], 7)
        self.assertNotEqual(insert_params[4], "ABCD")

    def test_create_share_retries_duplicate_share_code_collision(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        file_hash = "e" * 64
        generated_codes = iter(["dupe-code", "fresh-code"])
        events = []

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))
                if sql.strip().lower().startswith("insert into file_share") and params[0] == "dupe-code":
                    raise Exception("Duplicate entry 'dupe-code' for key 'idx_file_share_code'")

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_chain_record" in self.last_sql:
                    return (file_hash, 7)
                return None

        class FakeConnection:
            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.shares.create_share_code = lambda: next(generated_codes)

        response = server_main.app.test_client().post(
            f"/api/user/files/{file_hash}/shares",
            headers={"Authorization": f"Bearer {token}"},
            json={"extract_code": "ABCD", "max_downloads": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["share_code"], "fresh-code")
        insert_codes = [
            params[0] for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("insert into file_share")
        ]
        self.assertEqual(insert_codes, ["dupe-code", "fresh-code"])
        self.assertIn("rollback", events)
        self.assertEqual(events[-1], "commit")

    def test_user_shares_list_uses_current_owner_and_hides_extract_hash(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        now = server_main.datetime.now()
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                return None

            def fetchall(self):
                return [(
                    "share123",
                    "b" * 64,
                    7,
                    "public",
                    "sha256$salt$digest",
                    None,
                    0,
                    0,
                    "active",
                    now,
                    "demo.txt",
                    1.5,
                )]

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get(
            "/api/user/shares",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        share = response.get_json()["data"][0]
        self.assertTrue(share["extract_code_required"])
        self.assertNotIn("extract_code_hash", share)
        share_queries = [
            (sql, params) for sql, params in fake_cursor.executed if "from file_share" in sql
        ]
        self.assertEqual(share_queries[-1][1], (7,))

    def test_update_and_delete_share_are_owner_only(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_share" in self.last_sql:
                    return ("share123",)
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = types.SimpleNamespace(commit=lambda: None)
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        patch_response = client.patch(
            "/api/user/shares/share123",
            headers={"Authorization": f"Bearer {token}"},
            json={"extract_code": "WXYZ", "status": "inactive", "max_downloads": 5},
        )
        delete_response = client.delete(
            "/api/user/shares/share123",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(delete_response.status_code, 200)
        update_queries = [
            (sql, params) for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("update file_share")
        ]
        self.assertEqual(len(update_queries), 2)
        self.assertIn("owner_user_id=%s", update_queries[0][0])
        self.assertIn("owner_user_id=%s", update_queries[1][0])

    def test_update_share_returns_404_when_update_rowcount_is_zero(self):
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                if sql.strip().lower().startswith("update file_share"):
                    self.rowcount = 0

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_share" in self.last_sql:
                    return ("share123",)
                return None

        server_main.cursor = FakeCursor()
        server_main.db = types.SimpleNamespace(commit=lambda: None)
        server_main.init_db = lambda: True

        response = server_main.app.test_client().patch(
            "/api/user/shares/share123",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "inactive"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["msg"], "分享不存在")

    def test_update_share_persists_offset_expiry_as_local_naive_datetime(self):
        auth = importlib.import_module("auth")
        datetime_module = importlib.import_module("datetime")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        token = auth.create_session_token({"user_id": 7, "username": "alice"}, "session-secret")
        aware = datetime_module.datetime(
            2026,
            6,
            27,
            3,
            0,
            0,
            tzinfo=datetime_module.timezone.utc,
        )

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from app_user" in self.last_sql:
                    return (7, "alice", "hash", "0xabc", "active")
                if "from file_share" in self.last_sql:
                    return ("share123",)
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = types.SimpleNamespace(commit=lambda: None)
        server_main.init_db = lambda: True

        response = server_main.app.test_client().patch(
            "/api/user/shares/share123",
            headers={"Authorization": f"Bearer {token}"},
            json={"expires_at": aware.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        update_params = [
            params for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("update file_share")
        ][0]
        persisted_expires_at = update_params[0]
        self.assertIsNone(persisted_expires_at.tzinfo)
        self.assertEqual(persisted_expires_at, aware.astimezone().replace(tzinfo=None))

    def test_public_share_missing_returns_json_404(self):
        server_main = load_server_main()

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                return None

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/api/share/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(response.get_json()["msg"], "分享不存在")

    def test_public_share_metadata_validates_access_and_hides_extract_hash(self):
        shares = importlib.import_module("shares")
        server_main = load_server_main()
        now = server_main.datetime.now()
        share_hash = shares.hash_extract_code("ABCD", salt="fixedsalt")

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "c" * 64,
                        7,
                        "public",
                        share_hash,
                        None,
                        0,
                        0,
                        "active",
                        now,
                        "demo.txt",
                        1.5,
                    )
                return None

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/api/share/share123")

        self.assertEqual(response.status_code, 200)
        share = response.get_json()["data"]
        self.assertTrue(share["extract_code_required"])
        self.assertNotIn("extract_code_hash", share)
        self.assertNotIn("file_hash", share)
        self.assertNotIn("owner_user_id", share)
        self.assertEqual(share["file_name"], "demo.txt")

    def test_public_share_verify_checks_extract_code(self):
        shares = importlib.import_module("shares")
        server_main = load_server_main()
        now = server_main.datetime.now()
        share_hash = shares.hash_extract_code("ABCD", salt="fixedsalt")

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "d" * 64,
                        7,
                        "public",
                        share_hash,
                        None,
                        0,
                        0,
                        "active",
                        now,
                        "demo.txt",
                        1.5,
                    )
                return None

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True
        client = server_main.app.test_client()

        wrong_response = client.post("/api/share/share123/verify", json={"extract_code": "BAD"})
        correct_response = client.post("/api/share/share123/verify", json={"extract_code": "ABCD"})

        self.assertEqual(wrong_response.status_code, 403)
        self.assertEqual(correct_response.status_code, 200)
        self.assertTrue(correct_response.get_json()["verified"])

    def test_share_download_logs_download_and_point_ledger_entries(self):
        shares = importlib.import_module("shares")
        auth = importlib.import_module("auth")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        now = server_main.datetime.now()
        share_hash = shares.hash_extract_code("ABCD", salt="fixedsalt")
        token = auth.create_session_token({"user_id": 9, "username": "bob"}, "session-secret")
        events = []

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))
                self.rowcount = 1

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "f" * 64,
                        7,
                        "public",
                        share_hash,
                        None,
                        0,
                        0,
                        "active",
                        now,
                        "demo.txt",
                        "cid1",
                        10,
                        '["NODE_A", "NODE_B"]',
                        "0xowner",
                    )
                if "from app_user" in self.last_sql:
                    return (9, "bob", "hash", "0xbob", "active")
                return None

        class FakeConnection:
            def get_autocommit(self):
                return True

            def autocommit(self, value):
                events.append(("autocommit", value))

            def begin(self):
                events.append("begin")

            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

        class FakeIPFSClient:
            def cat(self, cid):
                return b"encrypted"

            def close(self):
                pass

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.get_ipfs_client = lambda: FakeIPFSClient()
        server_main.aes_decrypt = lambda data: b"plain-data"

        response = server_main.app.test_client().get(
            "/api/share/share123/download?extract_code=ABCD",
            headers={"Authorization": f"Bearer {token}"},
            environ_base={"REMOTE_ADDR": "203.0.113.9"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"plain-data")
        statements = [sql.strip().lower() for sql, _ in fake_cursor.executed]
        joined = "\n".join(statements)
        self.assertIn("update file_share", joined)
        self.assertIn("update file_chain_record", joined)
        self.assertIn("insert into file_download_log", joined)
        self.assertIn("insert into point_ledger", joined)
        share_update_sql = [
            sql.strip().lower() for sql, _ in fake_cursor.executed
            if sql.strip().lower().startswith("update file_share")
        ][0]
        self.assertIn("status='active'", share_update_sql)
        self.assertIn("download_count < max_downloads", share_update_sql)
        ledger_params = [
            params for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("insert into point_ledger")
        ]
        self.assertEqual(len(ledger_params), 3)
        self.assertEqual(ledger_params[0][0], 7)
        self.assertEqual(ledger_params[0][3], 1)
        self.assertEqual(ledger_params[1][1], "NODE_A")
        self.assertEqual(ledger_params[1][3], 1.0)
        log_params = [
            params for sql, params in fake_cursor.executed
            if sql.strip().lower().startswith("insert into file_download_log")
        ][0]
        self.assertEqual(log_params[0], "share123")
        self.assertEqual(log_params[3], 9)
        self.assertEqual(events.count("commit"), 1)
        self.assertNotIn("rollback", events)

    def test_share_download_prefers_user_node_storage_before_ipfs(self):
        shares = importlib.import_module("shares")
        server_main = load_server_main(SESSION_SECRET="session-secret")
        now = server_main.datetime.now()
        share_hash = shares.hash_extract_code("ABCD", salt="fixedsalt")

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))
                self.rowcount = 1

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "f" * 64,
                        7,
                        "public",
                        share_hash,
                        None,
                        0,
                        0,
                        "active",
                        now,
                        "demo.txt",
                        "cid1",
                        10,
                        '["NODE_A"]',
                        "0xowner",
                    )
                return None

        class FakeConnection:
            def get_autocommit(self):
                return True

            def autocommit(self, value):
                pass

            def commit(self):
                pass

            def rollback(self):
                pass

        server_main.cursor = FakeCursor()
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.read_file_from_storage_nodes = lambda file_hash, nodes: b"encrypted-from-node"
        server_main.get_ipfs_client = lambda: self.fail("IPFS should not be used when user node storage is available")
        server_main.aes_decrypt = lambda data: b"plain-from-node"

        response = server_main.app.test_client().get("/api/share/share123/download?extract_code=ABCD")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"plain-from-node")

    def test_share_download_falls_back_to_ipfs_when_user_node_storage_missing(self):
        server_main = load_server_main()
        now = server_main.datetime.now()

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))
                self.rowcount = 1

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "f" * 64,
                        7,
                        "public",
                        "",
                        None,
                        0,
                        0,
                        "active",
                        now,
                        "demo.txt",
                        "cid1",
                        10,
                        '["NODE_A"]',
                        "0xowner",
                    )
                return None

        class FakeConnection:
            def get_autocommit(self):
                return True

            def autocommit(self, value):
                pass

            def commit(self):
                pass

            def rollback(self):
                pass

        class FakeIPFSClient:
            def cat(self, cid):
                return b"encrypted-from-ipfs"

            def close(self):
                pass

        server_main.cursor = FakeCursor()
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.read_file_from_storage_nodes = lambda file_hash, nodes: None
        server_main.get_ipfs_client = lambda: FakeIPFSClient()
        server_main.aes_decrypt = lambda data: b"plain-from-ipfs"

        response = server_main.app.test_client().get("/api/share/share123/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"plain-from-ipfs")

    def test_share_download_atomic_rowcount_zero_aborts_before_side_effects(self):
        server_main = load_server_main()
        now = server_main.datetime.now()
        events = []

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""
                self.rowcount = 1

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))
                if sql.strip().lower().startswith("update file_share"):
                    self.rowcount = 0
                else:
                    self.rowcount = 1

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "f" * 64,
                        7,
                        "public",
                        "",
                        None,
                        1,
                        0,
                        "active",
                        now,
                        "demo.txt",
                        "cid1",
                        10,
                        '["NODE_A"]',
                        "0xowner",
                    )
                return None

        class FakeConnection:
            def get_autocommit(self):
                return True

            def autocommit(self, value):
                events.append(("autocommit", value))

            def begin(self):
                events.append("begin")

            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

        class FakeIPFSClient:
            def cat(self, cid):
                return b"encrypted"

            def close(self):
                pass

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.db = FakeConnection()
        server_main.init_db = lambda: True
        server_main.get_ipfs_client = lambda: FakeIPFSClient()
        server_main.aes_decrypt = lambda data: b"plain-data"

        response = server_main.app.test_client().get("/api/share/share123/download")

        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/json")
        self.assertIn(response.status_code, {404, 409, 410, 429})
        side_effect_inserts = [
            sql for sql, _ in fake_cursor.executed
            if sql.strip().lower().startswith("insert into file_download_log")
            or sql.strip().lower().startswith("insert into point_ledger")
        ]
        self.assertEqual(side_effect_inserts, [])
        self.assertIn("rollback", events)
        self.assertNotIn("commit", events)

    def test_share_download_ipfs_cat_failure_returns_json_without_side_effects(self):
        server_main = load_server_main()
        now = server_main.datetime.now()

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "f" * 64,
                        7,
                        "public",
                        "",
                        None,
                        0,
                        0,
                        "active",
                        now,
                        "demo.txt",
                        "cid1",
                        10,
                        '["NODE_A"]',
                        "0xowner",
                    )
                return None

        class FakeIPFSClient:
            def cat(self, cid):
                raise Exception("ipfs unavailable")

            def close(self):
                pass

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.init_db = lambda: True
        server_main.get_ipfs_client = lambda: FakeIPFSClient()

        response = server_main.app.test_client().get("/api/share/share123/download")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.content_type, "application/json")
        side_effects = [
            sql for sql, _ in fake_cursor.executed
            if sql.strip().lower().startswith(("update ", "insert "))
        ]
        self.assertEqual(side_effects, [])

    def test_share_download_blocks_exhausted_share_before_side_effects(self):
        server_main = load_server_main()
        now = server_main.datetime.now()

        class FakeCursor:
            def __init__(self):
                self.executed = []
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql
                self.executed.append((sql, params))

            def fetchone(self):
                if "from file_share" in self.last_sql:
                    return (
                        "share123",
                        "f" * 64,
                        7,
                        "public",
                        "",
                        None,
                        1,
                        1,
                        "active",
                        now,
                        "demo.txt",
                        "cid1",
                        10,
                        '["NODE_A"]',
                        "0xowner",
                    )
                return None

        fake_cursor = FakeCursor()
        server_main.cursor = fake_cursor
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/api/share/share123/download")

        self.assertEqual(response.status_code, 429)
        side_effects = [
            sql for sql, _ in fake_cursor.executed
            if sql.strip().lower().startswith(("update ", "insert "))
        ]
        self.assertEqual(side_effects, [])

    def test_filter_file_records_searches_and_paginates(self):
        server_main = load_server_main()
        rows = [
            (1, "alpha.txt", "h1", "cid1", 1, 1, "U", "[]", server_main.datetime.now(), "public", "", None),
            (2, "beta.txt", "h2", "cid2", 1, 1, "U", "[]", server_main.datetime.now(), "public", "", None),
            (3, "alpha-2.txt", "h3", "cid3", 1, 1, "U", "[]", server_main.datetime.now(), "public", "", None),
        ]

        result = server_main.filter_file_records(rows, keyword="alpha", page=1, page_size=1)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["page"], 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["file_name"], "alpha.txt")

    def test_private_file_access_requires_matching_token(self):
        server_main = load_server_main()
        private_record = {"visibility": "private", "access_token": "token123"}
        public_record = {"visibility": "public", "access_token": ""}

        self.assertFalse(server_main.file_access_allowed(private_record, "wrong"))
        self.assertTrue(server_main.file_access_allowed(private_record, "token123"))
        self.assertTrue(server_main.file_access_allowed(public_record, ""))

    def test_file_health_counts_alive_storage_nodes(self):
        server_main = load_server_main()
        record = {
            "nodes": ["NODE_A", "NODE_B", "NODE_C"],
            "shard": 3,
        }

        health = server_main.calculate_file_health(record, {"NODE_A", "NODE_C"})

        self.assertEqual(health["stored_count"], 3)
        self.assertEqual(health["alive_count"], 2)
        self.assertEqual(health["status"], "degraded")

    def test_ipfs_status_reports_online_peer_and_repo_data(self):
        server_main = load_server_main()

        class FakeIPFSClient:
            def id(self):
                return {"ID": "peer1", "Addresses": ["/ip4/127.0.0.1/tcp/4001"]}

            def repo_stat(self):
                return {"RepoSize": 1024, "StorageMax": 2048, "NumObjects": 3}

            def close(self):
                pass

        status = server_main.read_ipfs_status(lambda: FakeIPFSClient())

        self.assertTrue(status["online"])
        self.assertEqual(status["peer_id"], "peer1")
        self.assertEqual(status["repo_size"], 1024)

    def test_file_download_endpoint_returns_decrypted_attachment(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None

            def fetchone(self):
                return (
                    1,
                    "demo.txt",
                    "hash1",
                    "cid1",
                    1,
                    1,
                    "NODE_A",
                    "[]",
                    server_main.datetime.now(),
                    "public",
                    "",
                    None,
                )

        class FakeIPFSClient:
            def cat(self, cid):
                return b"encrypted"

            def close(self):
                pass

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True
        server_main.get_ipfs_client = lambda: FakeIPFSClient()
        server_main.aes_decrypt = lambda data: b"plain-data"

        response = server_main.app.test_client().get("/api/file_download/hash1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"plain-data")
        self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_user_owned_public_file_download_requires_share_route(self):
        server_main = load_server_main()

        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None

            def fetchone(self):
                return (
                    1,
                    "demo.txt",
                    "hash1",
                    "cid1",
                    1,
                    1,
                    "NODE_A",
                    "[]",
                    server_main.datetime.now(),
                    "public",
                    "",
                    None,
                    7,
                )

        server_main.cursor = FakeCursor()
        server_main.init_db = lambda: True
        server_main.get_ipfs_client = lambda: self.fail("raw user file download should not read IPFS")

        response = server_main.app.test_client().get("/api/file_download/hash1")

        self.assertEqual(response.status_code, 403)
        self.assertIn("分享链接", response.get_json()["msg"])


if __name__ == "__main__":
    unittest.main()
