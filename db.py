from pathlib import Path
from flask import g
import os
import pymysql

try:
    import psycopg
except ImportError:
    psycopg = None


BASE_DIR = Path(__file__).resolve().parent


def load_env_file(env_path=None):
    env_path = Path(env_path) if env_path else BASE_DIR / ".env"
    if not env_path.exists():
        return False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return True


if os.getenv("WEB3_NODES_SKIP_DOTENV") != "1":
    load_env_file()


def current_cursor(global_cursor=None):
    try:
        request_cursor = getattr(g, "cursor", None)
    except RuntimeError:
        request_cursor = None
    return request_cursor or global_cursor


def get_env(primary_key, legacy_key, default):
    return os.getenv(primary_key) or os.getenv(legacy_key) or default


DB_ENGINE = os.getenv("DB_ENGINE", "postgresql").strip().lower()
if DB_ENGINE not in ("postgresql", "mysql"):
    DB_ENGINE = "postgresql"


def build_db_config():
    if DB_ENGINE == "mysql":
        return {
            "host": get_env("MYSQL_HOST", "DB_HOST", "127.0.0.1"),
            "user": get_env("MYSQL_USER", "DB_USER", "root"),
            "password": get_env("MYSQL_PASSWORD", "DB_PASSWORD", ""),
            "database": get_env("MYSQL_DB_NAME", "DB_NAME", "web3_modes_store"),
            "port": int(get_env("MYSQL_PORT", "DB_PORT", "3306")),
            "charset": "utf8mb4",
            "autocommit": True,
            "connect_timeout": 3,
            "read_timeout": 10,
            "write_timeout": 10,
        }
    return {
        "host": get_env("POSTGRES_HOST", "DB_HOST", "127.0.0.1"),
        "user": get_env("POSTGRES_USER", "DB_USER", "postgres"),
        "password": get_env("POSTGRES_PASSWORD", "DB_PASSWORD", ""),
        "database": get_env("POSTGRES_DB_NAME", "DB_NAME", "web3_modes_store"),
        "port": int(get_env("POSTGRES_PORT", "DB_PORT", "5432")),
        "connect_timeout": 3,
    }


DB_CONFIG = build_db_config()
INIT_SQL_PATH = BASE_DIR / ("init_mysql.sql" if DB_ENGINE == "mysql" else "init_postgresql.sql")
db_error = ""


def connect_database(config):
    if DB_ENGINE == "mysql":
        return pymysql.connect(**config)
    if psycopg is None:
        raise RuntimeError("缺少 psycopg 依赖，请执行：pip install psycopg[binary]")
    pg_config = {
        "host": config["host"],
        "port": config["port"],
        "user": config["user"],
        "password": config["password"],
        "dbname": config["database"],
        "connect_timeout": config.get("connect_timeout", 3),
    }
    connection = psycopg.connect(**pg_config)
    connection.autocommit = True
    return connection


def server_config(database=None):
    config = DB_CONFIG.copy()
    if DB_ENGINE == "mysql":
        config.pop("database", None)
    else:
        config["database"] = database or "postgres"
    return config


def split_sql_statements(sql_text):
    statements = []
    current = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current).rstrip(";").strip())
            current = []
    if current:
        statements.append("\n".join(current).strip())
    return statements


def mysql_duplicate_column_error(exc):
    message = str(exc).lower()
    return "duplicate column" in message or "duplicate column name" in message


def mysql_duplicate_index_error(exc):
    message = str(exc).lower()
    return "duplicate key name" in message or "duplicate index" in message


def should_ignore_mysql_init_error(statement, exc):
    if DB_ENGINE != "mysql":
        return False
    normalized = statement.strip().lower()
    duplicate_column = (
        (
            normalized.startswith("alter table `file_chain_record` add column")
            or normalized.startswith("alter table file_chain_record add column")
            or normalized.startswith("alter table node_power add column")
        )
        and mysql_duplicate_column_error(exc)
    )
    duplicate_owner_index = (
        normalized == "create index idx_file_chain_owner on `file_chain_record` (`owner_user_id`)"
        and mysql_duplicate_index_error(exc)
    )
    return duplicate_column or duplicate_owner_index


USER_PRODUCT_MYSQL_TABLES = [
    """CREATE TABLE IF NOT EXISTS `app_user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(64) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `wallet_address` varchar(128) DEFAULT NULL,
  `status` varchar(16) DEFAULT 'active',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `last_login_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_app_user_username` (`username`),
  UNIQUE KEY `idx_app_user_wallet` (`wallet_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS `wallet_nonce` (
  `id` int NOT NULL AUTO_INCREMENT,
  `wallet_address` varchar(128) NOT NULL,
  `nonce` varchar(128) NOT NULL,
  `expires_at` datetime NOT NULL,
  `used_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wallet_nonce_address` (`wallet_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS `file_share` (
  `id` int NOT NULL AUTO_INCREMENT,
  `share_code` varchar(32) NOT NULL,
  `file_hash` varchar(128) NOT NULL,
  `owner_user_id` int NOT NULL,
  `visibility` varchar(16) DEFAULT 'public',
  `extract_code_hash` varchar(255) DEFAULT '',
  `expires_at` datetime DEFAULT NULL,
  `max_downloads` int DEFAULT 0,
  `download_count` int DEFAULT 0,
  `status` varchar(16) DEFAULT 'active',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_file_share_code` (`share_code`),
  KEY `idx_file_share_file` (`file_hash`),
  KEY `idx_file_share_owner` (`owner_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS `file_download_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `share_code` varchar(32) DEFAULT '',
  `file_hash` varchar(128) NOT NULL,
  `downloader_ip` varchar(64) DEFAULT '',
  `downloader_user_id` int DEFAULT NULL,
  `node_address` varchar(128) DEFAULT '',
  `file_size` decimal(18,6) DEFAULT 0,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_download_file` (`file_hash`),
  KEY `idx_download_share` (`share_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS `point_ledger` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL,
  `wallet_address` varchar(128) DEFAULT '',
  `point_type` varchar(32) NOT NULL,
  `amount` decimal(18,6) NOT NULL,
  `source_type` varchar(32) DEFAULT '',
  `source_id` varchar(128) DEFAULT '',
  `remark` varchar(255) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_point_user` (`user_id`),
  KEY `idx_point_wallet` (`wallet_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS `withdrawal_request` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL,
  `wallet_address` varchar(128) NOT NULL,
  `amount` decimal(18,6) NOT NULL,
  `status` varchar(16) DEFAULT 'pending',
  `admin_note` varchar(255) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `reviewed_at` datetime DEFAULT NULL,
  `node_address` varchar(128) DEFAULT '',
  `withdrawal_channel` varchar(32) DEFAULT 'wallet',
  `withdrawal_account` varchar(128) DEFAULT '',
  PRIMARY KEY (`id`),
  KEY `idx_withdrawal_user` (`user_id`),
  KEY `idx_withdrawal_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


USER_PRODUCT_POSTGRESQL_TABLES = [
    """CREATE TABLE IF NOT EXISTS app_user (
    id SERIAL PRIMARY KEY,
    username varchar(64) NOT NULL UNIQUE,
    password_hash varchar(255) NOT NULL,
    wallet_address varchar(128) UNIQUE,
    status varchar(16) DEFAULT 'active',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    last_login_at timestamp DEFAULT NULL
)""",
    """CREATE TABLE IF NOT EXISTS wallet_nonce (
    id SERIAL PRIMARY KEY,
    wallet_address varchar(128) NOT NULL,
    nonce varchar(128) NOT NULL,
    expires_at timestamp NOT NULL,
    used_at timestamp DEFAULT NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS file_share (
    id SERIAL PRIMARY KEY,
    share_code varchar(32) NOT NULL UNIQUE,
    file_hash varchar(128) NOT NULL,
    owner_user_id integer NOT NULL,
    visibility varchar(16) DEFAULT 'public',
    extract_code_hash varchar(255) DEFAULT '',
    expires_at timestamp DEFAULT NULL,
    max_downloads integer DEFAULT 0,
    download_count integer DEFAULT 0,
    status varchar(16) DEFAULT 'active',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS file_download_log (
    id SERIAL PRIMARY KEY,
    share_code varchar(32) DEFAULT '',
    file_hash varchar(128) NOT NULL,
    downloader_ip varchar(64) DEFAULT '',
    downloader_user_id integer DEFAULT NULL,
    node_address varchar(128) DEFAULT '',
    file_size numeric(18,6) DEFAULT 0,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS point_ledger (
    id SERIAL PRIMARY KEY,
    user_id integer DEFAULT NULL,
    wallet_address varchar(128) DEFAULT '',
    point_type varchar(32) NOT NULL,
    amount numeric(18,6) NOT NULL,
    source_type varchar(32) DEFAULT '',
    source_id varchar(128) DEFAULT '',
    remark varchar(255) DEFAULT '',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS withdrawal_request (
    id SERIAL PRIMARY KEY,
    user_id integer DEFAULT NULL,
    wallet_address varchar(128) NOT NULL,
    amount numeric(18,6) NOT NULL,
    status varchar(16) DEFAULT 'pending',
    admin_note varchar(255) DEFAULT '',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    reviewed_at timestamp DEFAULT NULL,
    node_address varchar(128) DEFAULT '',
    withdrawal_channel varchar(32) DEFAULT 'wallet',
    withdrawal_account varchar(128) DEFAULT ''
)""",
]


SCHEMA_MIGRATIONS = [
    "ALTER TABLE node_reward ADD COLUMN source_user_address varchar(64) DEFAULT '' COMMENT '收益来源节点'",
    "ALTER TABLE node_reward ADD COLUMN settle_date date DEFAULT NULL COMMENT '结算日期，防重复结算'",
    "ALTER TABLE node_reward ADD UNIQUE KEY idx_reward_once (user_address,reward_type,source_user_address,settle_date)",
    "ALTER TABLE node_power ADD COLUMN storage_path varchar(255) DEFAULT ''",
    "ALTER TABLE node_power ADD COLUMN storage_status varchar(32) DEFAULT 'unknown'",
    "ALTER TABLE node_power ADD COLUMN storage_error varchar(255) DEFAULT ''",
    "ALTER TABLE node_power ADD COLUMN storage_total_gb float DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN storage_used_gb float DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN storage_free_gb float DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN storage_quota_gb float DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN storage_available_gb float DEFAULT 0",
    "ALTER TABLE file_chain_record ADD COLUMN visibility varchar(16) DEFAULT 'public' COMMENT 'public公开 private凭token访问'",
    "ALTER TABLE file_chain_record ADD COLUMN access_token varchar(64) DEFAULT '' COMMENT '私有文件访问令牌'",
    "ALTER TABLE file_chain_record ADD COLUMN deleted_at datetime DEFAULT NULL COMMENT '软删除时间'",
    "ALTER TABLE file_chain_record ADD COLUMN owner_user_id int DEFAULT NULL",
    "ALTER TABLE file_chain_record ADD COLUMN owner_wallet_address varchar(128) DEFAULT ''",
    "ALTER TABLE file_chain_record ADD COLUMN download_count int DEFAULT 0",
    "ALTER TABLE file_chain_record ADD COLUMN last_download_at datetime DEFAULT NULL",
    "CREATE INDEX idx_file_chain_owner ON file_chain_record (owner_user_id)",
    """CREATE TABLE IF NOT EXISTS file_shard_record (
  id int NOT NULL AUTO_INCREMENT,
  file_hash varchar(128) NOT NULL,
  encrypted_hash varchar(128) DEFAULT '',
  chunk_index int NOT NULL,
  chunk_total int NOT NULL,
  chunk_hash varchar(128) NOT NULL,
  chunk_size int DEFAULT 0,
  node_address varchar(128) DEFAULT '',
  storage_status varchar(32) DEFAULT 'pending',
  stored_at datetime DEFAULT NULL,
  last_verified_at datetime DEFAULT NULL,
  error_message varchar(255) DEFAULT '',
  PRIMARY KEY (id),
  KEY idx_file_shard_file (file_hash),
  KEY idx_file_shard_node (node_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS storage_audit_log (
  id int NOT NULL AUTO_INCREMENT,
  event_type varchar(64) NOT NULL,
  file_hash varchar(128) DEFAULT '',
  chunk_index int DEFAULT NULL,
  node_address varchar(128) DEFAULT '',
  request_id varchar(64) DEFAULT '',
  status varchar(32) DEFAULT '',
  message varchar(255) DEFAULT '',
  metadata_json text,
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_storage_audit_file (file_hash),
  KEY idx_storage_audit_node (node_address),
  KEY idx_storage_audit_event (event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    *USER_PRODUCT_MYSQL_TABLES,
    "CREATE INDEX idx_wallet_nonce_address ON wallet_nonce (wallet_address)",
    "CREATE INDEX idx_file_share_file ON file_share (file_hash)",
    "CREATE INDEX idx_file_share_owner ON file_share (owner_user_id)",
    "CREATE INDEX idx_download_file ON file_download_log (file_hash)",
    "CREATE INDEX idx_download_share ON file_download_log (share_code)",
    "CREATE INDEX idx_point_user ON point_ledger (user_id)",
    "CREATE INDEX idx_point_wallet ON point_ledger (wallet_address)",
    "ALTER TABLE withdrawal_request MODIFY COLUMN user_id int DEFAULT NULL",
    "ALTER TABLE withdrawal_request ADD COLUMN node_address varchar(128) DEFAULT ''",
    "ALTER TABLE withdrawal_request ADD COLUMN withdrawal_channel varchar(32) DEFAULT 'wallet'",
    "ALTER TABLE withdrawal_request ADD COLUMN withdrawal_account varchar(128) DEFAULT ''",
    "CREATE INDEX idx_withdrawal_user ON withdrawal_request (user_id)",
    "CREATE INDEX idx_withdrawal_status ON withdrawal_request (status)",
]


POSTGRES_SCHEMA_MIGRATIONS = [
    "ALTER TABLE node_reward ADD COLUMN IF NOT EXISTS source_user_address varchar(64) DEFAULT ''",
    "ALTER TABLE node_reward ADD COLUMN IF NOT EXISTS settle_date date DEFAULT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_reward_once ON node_reward (user_address,reward_type,source_user_address,settle_date)",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_path varchar(255) DEFAULT ''",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_status varchar(32) DEFAULT 'unknown'",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_error varchar(255) DEFAULT ''",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_total_gb double precision DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_used_gb double precision DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_free_gb double precision DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_quota_gb double precision DEFAULT 0",
    "ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_available_gb double precision DEFAULT 0",
    "ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS visibility varchar(16) DEFAULT 'public'",
    "ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS access_token varchar(64) DEFAULT ''",
    "ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS deleted_at timestamp DEFAULT NULL",
    "ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS owner_user_id integer DEFAULT NULL",
    "ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS owner_wallet_address varchar(128) DEFAULT ''",
    "ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS download_count integer DEFAULT 0",
    "ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS last_download_at timestamp DEFAULT NULL",
    "CREATE INDEX IF NOT EXISTS idx_file_chain_owner ON file_chain_record (owner_user_id)",
    """CREATE TABLE IF NOT EXISTS file_shard_record (
  id SERIAL PRIMARY KEY,
  file_hash varchar(128) NOT NULL,
  encrypted_hash varchar(128) DEFAULT '',
  chunk_index integer NOT NULL,
  chunk_total integer NOT NULL,
  chunk_hash varchar(128) NOT NULL,
  chunk_size integer DEFAULT 0,
  node_address varchar(128) DEFAULT '',
  storage_status varchar(32) DEFAULT 'pending',
  stored_at timestamp DEFAULT NULL,
  last_verified_at timestamp DEFAULT NULL,
  error_message varchar(255) DEFAULT ''
)""",
    "CREATE INDEX IF NOT EXISTS idx_file_shard_file ON file_shard_record (file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_file_shard_node ON file_shard_record (node_address)",
    """CREATE TABLE IF NOT EXISTS storage_audit_log (
  id SERIAL PRIMARY KEY,
  event_type varchar(64) NOT NULL,
  file_hash varchar(128) DEFAULT '',
  chunk_index integer DEFAULT NULL,
  node_address varchar(128) DEFAULT '',
  request_id varchar(64) DEFAULT '',
  status varchar(32) DEFAULT '',
  message varchar(255) DEFAULT '',
  metadata_json text,
  created_at timestamp DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_storage_audit_file ON storage_audit_log (file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_storage_audit_node ON storage_audit_log (node_address)",
    "CREATE INDEX IF NOT EXISTS idx_storage_audit_event ON storage_audit_log (event_type)",
    *USER_PRODUCT_POSTGRESQL_TABLES,
    "CREATE INDEX IF NOT EXISTS idx_wallet_nonce_address ON wallet_nonce (wallet_address)",
    "CREATE INDEX IF NOT EXISTS idx_file_share_file ON file_share (file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_file_share_owner ON file_share (owner_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_download_file ON file_download_log (file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_download_share ON file_download_log (share_code)",
    "CREATE INDEX IF NOT EXISTS idx_point_user ON point_ledger (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_point_wallet ON point_ledger (wallet_address)",
    "ALTER TABLE withdrawal_request ALTER COLUMN user_id DROP NOT NULL",
    "ALTER TABLE withdrawal_request ADD COLUMN IF NOT EXISTS node_address varchar(128) DEFAULT ''",
    "ALTER TABLE withdrawal_request ADD COLUMN IF NOT EXISTS withdrawal_channel varchar(32) DEFAULT 'wallet'",
    "ALTER TABLE withdrawal_request ADD COLUMN IF NOT EXISTS withdrawal_account varchar(128) DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_withdrawal_user ON withdrawal_request (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_withdrawal_status ON withdrawal_request (status)",
]


def reward_upsert_sql():
    if DB_ENGINE == "postgresql":
        return """
            insert into node_reward(user_address,reward_type,reward_amount,node_contribution,source_user_address,settle_date)
            values(%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_address,reward_type,source_user_address,settle_date) DO UPDATE SET
            reward_amount=EXCLUDED.reward_amount,node_contribution=EXCLUDED.node_contribution,settle_time=CURRENT_TIMESTAMP
            """
    return """
            insert into node_reward(user_address,reward_type,reward_amount,node_contribution,source_user_address,settle_date)
            values(%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
            reward_amount=VALUES(reward_amount),node_contribution=VALUES(node_contribution),settle_time=CURRENT_TIMESTAMP
            """


def node_location_upsert_sql():
    if DB_ENGINE == "postgresql":
        return """
    INSERT INTO node_location(user_address,node_mac,ip_addr,country,province,city,lat,lng,online_status)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)
    ON CONFLICT (node_mac) DO UPDATE SET
    user_address=EXCLUDED.user_address,ip_addr=EXCLUDED.ip_addr,country=EXCLUDED.country,province=EXCLUDED.province,
    city=EXCLUDED.city,lat=EXCLUDED.lat,lng=EXCLUDED.lng,online_status=1,update_time=CURRENT_TIMESTAMP
    """
    return """
    INSERT INTO node_location(user_address,node_mac,ip_addr,country,province,city,lat,lng,online_status)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)
    ON DUPLICATE KEY UPDATE
    ip_addr=%s,country=%s,province=%s,city=%s,lat=%s,lng=%s,online_status=1
    """


def node_alive_interval_sql(minutes=3):
    if DB_ENGINE == "postgresql":
        return f"NOW() - INTERVAL '{int(minutes)} minutes'"
    return f"NOW() - INTERVAL {int(minutes)} MINUTE"


def ensure_database_initialized(sql_path=INIT_SQL_PATH):
    global db_error
    try:
        if DB_ENGINE == "postgresql":
            ensure_postgresql_database_exists()
        sql_text = Path(sql_path).read_text(encoding="utf-8")
        statements = split_sql_statements(sql_text)
        connection = connect_database(DB_CONFIG if DB_ENGINE == "postgresql" else server_config())
        try:
            init_cursor = connection.cursor()
            for statement in statements:
                try:
                    init_cursor.execute(statement)
                except Exception as exc:
                    if not should_ignore_mysql_init_error(statement, exc):
                        raise
            for statement in (POSTGRES_SCHEMA_MIGRATIONS if DB_ENGINE == "postgresql" else SCHEMA_MIGRATIONS):
                try:
                    init_cursor.execute(statement)
                except Exception:
                    pass
            if DB_ENGINE == "postgresql":
                connection.commit()
        finally:
            connection.close()
        db_error = ""
        return True
    except Exception as exc:
        db_error = str(exc)
        return False


def ensure_postgresql_database_exists():
    if DB_ENGINE != "postgresql":
        return True
    connection = connect_database(server_config(database="postgres"))
    try:
        connection.autocommit = True
        init_cursor = connection.cursor()
        init_cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB_CONFIG["database"],))
        if not init_cursor.fetchone():
            database_name = DB_CONFIG["database"].replace('"', '""')
            init_cursor.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        connection.close()
    return True
