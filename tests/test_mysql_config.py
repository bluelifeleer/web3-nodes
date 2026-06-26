import importlib
import os
import sys
import types
import unittest
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

    def test_login_can_issue_token_with_admin_api_token_secret(self):
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

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.get_json())

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

    def test_admin_page_uses_inline_token_form_instead_of_prompt_popup(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

        self.assertNotIn("prompt(", server_main.ADMIN_HTML)
        self.assertIn('id="adminTokenInput"', server_main.ADMIN_HTML)
        self.assertIn("saveAdminToken", server_main.ADMIN_HTML)

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

    def test_auto_settle_reward_uses_daily_snapshot_key(self):
        server_main = load_server_main()
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))
                self.last_sql = sql

            def fetchall(self):
                return [(
                    1,
                    "NODE_A",
                    "MAC_A",
                    100,
                    10,
                    30,
                    2,
                    server_main.datetime.now(),
                )]

            def fetchone(self):
                if "parent_invite_code" in self.last_sql:
                    return ("PARENT1",)
                if "invite_code" in self.last_sql:
                    return ("NODE_PARENT",)
                return None

        server_main.cursor = FakeCursor()

        self.assertTrue(server_main.auto_settle_reward())
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
            '{"server_url":"http://example.com:9000","parent_invite":"INV1","heartbeat_interval":5}',
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


if __name__ == "__main__":
    unittest.main()
