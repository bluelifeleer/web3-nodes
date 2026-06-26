import importlib
import os
import sys
import types
import unittest
from pathlib import Path


ENV_KEYS = (
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
)


def load_server_main(**env):
    old_env = {key: os.environ.get(key) for key in ENV_KEYS}
    old_pymysql = sys.modules.get("pymysql")
    old_requests = sys.modules.get("requests")

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
        sys.modules["pymysql"] = types.SimpleNamespace(connect=lambda **kwargs: None)
        sys.modules["requests"] = types.SimpleNamespace(
            get=lambda url, timeout: FakeResponse()
        )
        sys.modules.pop("server_main", None)
        return importlib.import_module("server_main")
    finally:
        if old_pymysql is None:
            sys.modules.pop("pymysql", None)
        else:
            sys.modules["pymysql"] = old_pymysql
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
    def test_mysql_environment_variables_are_preferred(self):
        server_main = load_server_main(
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


if __name__ == "__main__":
    unittest.main()
