# User File Sharing and Rewards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build user registration/login, wallet signature identity, user-owned uploads, share links with extract-code/expiry/download limits, points, withdrawals, and admin review panels.

**Architecture:** Keep the app as a Flask monolith while extracting feature logic from `server_main.py` into focused modules. Preserve PostgreSQL-first behavior and MySQL compatibility by updating both init SQL files and using dialect helper functions where SQL differs.

**Tech Stack:** Python 3, Flask, PyMySQL, psycopg, PyCryptodome, ipfshttpclient, unittest. Add `eth-account` for Ethereum-compatible `personal_sign` wallet verification.

---

## Scope Check

This plan implements one integrated product slice: identity, user files, sharing, points, withdrawals, and admin visibility. Each task below leaves the system runnable and testable. Full team collaboration, paid billing, and real chain withdrawals remain out of scope.

## File Structure

Create these modules:

- `db.py`: database config, connection, current cursor, SQL splitting, DB initialization, dialect helpers.
- `auth.py`: password hashing, session token helpers, auth decorators, nonce helpers, wallet signature verification.
- `files.py`: user file formatting, file ownership filtering, user upload orchestration helpers.
- `shares.py`: share code generation, extract-code hashing, share validation, share response formatting.
- `points.py`: point rule constants, point ledger writing, earnings summary helpers.
- `withdrawals.py`: withdrawal validation, formatting, status transitions.

Modify these existing files:

- `server_main.py`: import modules, register new routes, keep legacy admin and node behavior working.
- `init_postgresql.sql`: add new product tables and enhanced file columns.
- `init_mysql.sql`: add MySQL tables and enhanced file columns with the same logical fields as PostgreSQL.
- `requirements.txt`: add `eth-account`.
- `README.md`: document user product flow and wallet login.
- `tests/test_mysql_config.py`: keep current compatibility tests and add focused tests for new helpers and routes.

Create these pages as route-rendered HTML strings first:

- `/user/login`
- `/user/dashboard`
- `/user/upload`
- `/s/<share_code>`

Avoid adding a front-end build system in this phase.

---

### Task 1: Database Schema and DB Module Extraction

**Files:**
- Create: `db.py`
- Modify: `server_main.py`
- Modify: `init_postgresql.sql`
- Modify: `init_mysql.sql`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing schema tests**

Add tests that assert both SQL files contain the new tables and enhanced columns:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_user_product_tables_exist_in_postgresql_init_sql tests.test_mysql_config.MysqlConfigTest.test_user_product_tables_exist_in_mysql_init_sql
```

Expected: fail because the new tables and columns are missing.

- [ ] **Step 3: Create `db.py` with moved DB helpers**

Move DB-related functions from `server_main.py` into `db.py` with these public names:

```python
from pathlib import Path
from flask import g
import os

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

def current_cursor(global_cursor=None):
    try:
        request_cursor = getattr(g, "cursor", None)
    except RuntimeError:
        request_cursor = None
    return request_cursor or global_cursor
```

Move these existing functions into `db.py` without changing behavior:

- `get_env`
- `build_db_config`
- `connect_database`
- `server_config`
- `split_sql_statements`
- `reward_upsert_sql`
- `node_location_upsert_sql`
- `node_alive_interval_sql`
- `ensure_database_initialized`
- `ensure_postgresql_database_exists`

Expose `DB_ENGINE`, `DB_CONFIG`, `INIT_SQL_PATH`, `SCHEMA_MIGRATIONS`, and `POSTGRES_SCHEMA_MIGRATIONS`.

- [ ] **Step 4: Update `server_main.py` imports**

Replace local DB helper definitions with imports:

```python
from db import (
    BASE_DIR,
    DB_CONFIG,
    DB_ENGINE,
    INIT_SQL_PATH,
    connect_database,
    current_cursor as get_current_cursor,
    ensure_database_initialized,
    load_env_file,
    node_alive_interval_sql,
    node_location_upsert_sql,
    reward_upsert_sql,
)

def current_cursor():
    return get_current_cursor(cursor)
```

Keep `db = None`, `cursor = None`, `db_error = ""`, and `init_db()` in `server_main.py` for this task so the route behavior remains stable.

- [ ] **Step 5: Add schema to PostgreSQL init SQL**

Append PostgreSQL definitions:

```sql
ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS owner_user_id integer DEFAULT NULL;
ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS owner_wallet_address varchar(128) DEFAULT '';
ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS download_count integer DEFAULT 0;
ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS last_download_at timestamp DEFAULT NULL;

CREATE TABLE IF NOT EXISTS app_user (
    id SERIAL PRIMARY KEY,
    username varchar(64) NOT NULL UNIQUE,
    password_hash varchar(255) NOT NULL,
    wallet_address varchar(128) UNIQUE,
    status varchar(16) DEFAULT 'active',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    last_login_at timestamp DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS wallet_nonce (
    id SERIAL PRIMARY KEY,
    wallet_address varchar(128) NOT NULL,
    nonce varchar(128) NOT NULL,
    expires_at timestamp NOT NULL,
    used_at timestamp DEFAULT NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_share (
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
);

CREATE TABLE IF NOT EXISTS file_download_log (
    id SERIAL PRIMARY KEY,
    share_code varchar(32) DEFAULT '',
    file_hash varchar(128) NOT NULL,
    downloader_ip varchar(64) DEFAULT '',
    downloader_user_id integer DEFAULT NULL,
    node_address varchar(128) DEFAULT '',
    file_size numeric(18,6) DEFAULT 0,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS point_ledger (
    id SERIAL PRIMARY KEY,
    user_id integer DEFAULT NULL,
    wallet_address varchar(128) DEFAULT '',
    point_type varchar(32) NOT NULL,
    amount numeric(18,6) NOT NULL,
    source_type varchar(32) DEFAULT '',
    source_id varchar(128) DEFAULT '',
    remark varchar(255) DEFAULT '',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS withdrawal_request (
    id SERIAL PRIMARY KEY,
    user_id integer NOT NULL,
    wallet_address varchar(128) NOT NULL,
    amount numeric(18,6) NOT NULL,
    status varchar(16) DEFAULT 'pending',
    admin_note varchar(255) DEFAULT '',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    reviewed_at timestamp DEFAULT NULL
);
```

- [ ] **Step 6: Add matching schema to MySQL init SQL**

Append MySQL definitions:

```sql
ALTER TABLE `file_chain_record` ADD COLUMN `owner_user_id` int DEFAULT NULL;
ALTER TABLE `file_chain_record` ADD COLUMN `owner_wallet_address` varchar(128) DEFAULT '';
ALTER TABLE `file_chain_record` ADD COLUMN `download_count` int DEFAULT 0;
ALTER TABLE `file_chain_record` ADD COLUMN `last_download_at` datetime DEFAULT NULL;

CREATE TABLE IF NOT EXISTS `app_user` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Add the remaining MySQL tables:

```sql
CREATE TABLE IF NOT EXISTS `wallet_nonce` (
  `id` int NOT NULL AUTO_INCREMENT,
  `wallet_address` varchar(128) NOT NULL,
  `nonce` varchar(128) NOT NULL,
  `expires_at` datetime NOT NULL,
  `used_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wallet_nonce_address` (`wallet_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `file_share` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `file_download_log` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `point_ledger` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `withdrawal_request` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `wallet_address` varchar(128) NOT NULL,
  `amount` decimal(18,6) NOT NULL,
  `status` varchar(16) DEFAULT 'pending',
  `admin_note` varchar(255) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `reviewed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_withdrawal_user` (`user_id`),
  KEY `idx_withdrawal_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 7: Update migrations**

Add PostgreSQL `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` statements and MySQL best-effort migration strings for enhanced file columns and new table creation. The MySQL migration can ignore duplicate-column errors using the existing try/except migration loop.

- [ ] **Step 8: Run tests**

Run:

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','db.py','tests/test_mysql_config.py']]"
git diff --check
```

Expected: all tests pass, syntax parse succeeds, diff check has no output.

- [ ] **Step 9: Commit**

```powershell
git add db.py server_main.py init_postgresql.sql init_mysql.sql tests/test_mysql_config.py
git commit -m "Add user product database schema"
```

---

### Task 2: Account and Wallet Authentication

**Files:**
- Create: `auth.py`
- Modify: `server_main.py`
- Modify: `requirements.txt`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Add dependency**

Add this line to `requirements.txt`:

```text
eth-account
```

- [ ] **Step 2: Write failing auth helper tests**

Add tests:

```python
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


def test_wallet_login_message_contains_nonce_and_purpose(self):
    auth = importlib.import_module("auth")

    message = auth.build_wallet_message("abc123", "login")

    self.assertIn("abc123", message)
    self.assertIn("login", message)
    self.assertIn("Web3 Nodes", message)
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_password_hash_verification_accepts_correct_password tests.test_mysql_config.MysqlConfigTest.test_session_token_round_trip tests.test_mysql_config.MysqlConfigTest.test_wallet_login_message_contains_nonce_and_purpose
```

Expected: fail because `auth.py` does not exist.

- [ ] **Step 4: Create `auth.py`**

Implement:

```python
import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import wraps
from flask import jsonify, request, g

SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"

def verify_password(password, password_hash):
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except ValueError:
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
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64(signature)}"

def verify_session_token(token, secret):
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_unb64(encoded))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None

def build_wallet_message(nonce, purpose):
    return f"Web3 Nodes {purpose}\\nNonce: {nonce}\\nThis signature expires soon and does not transfer assets."

def normalize_wallet_address(address):
    return (address or "").strip().lower()
```

If `eth_account` is installed, add:

```python
def recover_wallet_address(message, signature):
    from eth_account.messages import encode_defunct
    from eth_account import Account
    return normalize_wallet_address(Account.recover_message(encode_defunct(text=message), signature=signature))
```

- [ ] **Step 5: Add route tests for registration and login**

Use fake cursor classes to simulate DB rows. Add tests:

```python
def test_register_rejects_missing_username(self):
    server_main = load_server_main()
    server_main.init_db = lambda: True
    response = server_main.app.test_client().post("/api/auth/register", json={"password": "pw"})
    self.assertEqual(response.status_code, 400)

def test_auth_me_requires_user_token(self):
    server_main = load_server_main()
    server_main.init_db = lambda: True
    response = server_main.app.test_client().get("/api/auth/me")
    self.assertEqual(response.status_code, 401)
```

- [ ] **Step 6: Implement minimal auth routes in `server_main.py`**

Add constants:

```python
SESSION_SECRET = os.getenv("SESSION_SECRET", os.getenv("ADMIN_API_TOKEN", "dev-session-secret"))
```

Add helper:

```python
def get_bearer_token():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("user_token", "")
```

Add `require_user()` decorator using `auth.verify_session_token()`.

Implement `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, `/api/auth/logout`, `/api/wallet/nonce`, `/api/wallet/bind`, `/api/wallet/login`.

- [ ] **Step 7: Run tests**

Run:

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','auth.py','tests/test_mysql_config.py']]"
git diff --check
```

- [ ] **Step 8: Commit**

```powershell
git add auth.py server_main.py requirements.txt tests/test_mysql_config.py
git commit -m "Add account and wallet authentication"
```

---

### Task 3: User File Ownership and Upload Routes

**Files:**
- Create: `files.py`
- Modify: `server_main.py`
- Modify: `upload.html`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing file helper tests**

Add tests:

```python
def test_user_file_record_exposes_owner_download_and_share_fields(self):
    files = importlib.import_module("files")
    now = datetime.now()
    row = (1, "demo.txt", "hash", "cid", 2.5, 3, "NODE_A", "[]", now, "public", "", None, 7, "0xabc", 4, now)

    record = files.format_user_file_record(row)

    self.assertEqual(record["owner_user_id"], 7)
    self.assertEqual(record["download_count"], 4)
    self.assertEqual(record["file_name"], "demo.txt")
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_user_file_record_exposes_owner_download_and_share_fields
```

Expected: fail because `files.py` does not exist.

- [ ] **Step 3: Create `files.py`**

Implement:

```python
def format_user_file_record(row):
    return {
        "id": row[0],
        "file_name": row[1],
        "file_hash": row[2],
        "ipfs_cid": row[3],
        "size": row[4] or 0,
        "shard": row[5] or 0,
        "uploader": row[6],
        "created_at": str(row[8]) if row[8] else "",
        "visibility": row[9] or "public",
        "owner_user_id": row[12],
        "owner_wallet_address": row[13] or "",
        "download_count": row[14] or 0,
        "last_download_at": str(row[15]) if row[15] else "",
    }
```

- [ ] **Step 4: Add user file API route tests**

Add tests that assert unauthenticated access is blocked:

```python
def test_user_files_requires_login(self):
    server_main = load_server_main()
    server_main.init_db = lambda: True

    response = server_main.app.test_client().get("/api/user/files")

    self.assertEqual(response.status_code, 401)
```

- [ ] **Step 5: Implement user file routes**

Add:

- `POST /api/user/files`: same storage logic as `/api/upload_file`, but owner is `g.user["user_id"]`.
- `GET /api/user/files`: selects only `owner_user_id=%s`.
- `GET /api/user/files/<file_hash>`: selects only owner file.
- `DELETE /api/user/files/<file_hash>`: soft deletes only owner file.

Use this SELECT projection consistently:

```sql
select id,file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes,create_time,
visibility,access_token,deleted_at,owner_user_id,owner_wallet_address,download_count,last_download_at
from file_chain_record
```

- [ ] **Step 6: Update `/user/upload` page**

Render a user-facing upload page that uses `Authorization: Bearer <token>` from local storage and calls `/api/user/files`. Keep the existing `upload.html` admin-token flow intact for backward compatibility, or change the route so old `upload.html` remains available as `/admin/upload`.

- [ ] **Step 7: Run tests and commit**

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','files.py','tests/test_mysql_config.py']]"
git diff --check
git add files.py server_main.py upload.html tests/test_mysql_config.py
git commit -m "Add user-owned file APIs"
```

---

### Task 4: Share Links, Extract Codes, Expiry, and Download Limits

**Files:**
- Create: `shares.py`
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing share helper tests**

Add tests:

```python
def test_extract_code_hash_verification(self):
    shares = importlib.import_module("shares")

    code_hash = shares.hash_extract_code("123456")

    self.assertTrue(shares.verify_extract_code("123456", code_hash))
    self.assertFalse(shares.verify_extract_code("000000", code_hash))

def test_share_validation_detects_expired_and_exhausted(self):
    shares = importlib.import_module("shares")
    expired = {"status": "active", "expires_at": datetime.now() - timedelta(minutes=1), "max_downloads": 0, "download_count": 0}
    exhausted = {"status": "active", "expires_at": None, "max_downloads": 2, "download_count": 2}

    self.assertEqual(shares.validate_share_access(expired), (False, 410, "分享已过期"))
    self.assertEqual(shares.validate_share_access(exhausted), (False, 429, "下载次数已用完"))
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_extract_code_hash_verification tests.test_mysql_config.MysqlConfigTest.test_share_validation_detects_expired_and_exhausted
```

- [ ] **Step 3: Create `shares.py`**

Implement:

```python
import hashlib
import hmac
import secrets
from datetime import datetime

def create_share_code():
    return secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12]

def hash_extract_code(code, salt=None):
    if not code:
        return ""
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256((salt + ":" + code).encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"

def verify_extract_code(code, code_hash):
    if not code_hash:
        return True
    try:
        algorithm, salt, expected = code_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "sha256":
        return False
    actual = hashlib.sha256((salt + ":" + (code or "")).encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual, expected)

def validate_share_access(share):
    if share.get("status") != "active":
        return False, 404, "分享不存在"
    expires_at = share.get("expires_at")
    if expires_at and expires_at < datetime.now():
        return False, 410, "分享已过期"
    max_downloads = int(share.get("max_downloads") or 0)
    download_count = int(share.get("download_count") or 0)
    if max_downloads > 0 and download_count >= max_downloads:
        return False, 429, "下载次数已用完"
    return True, 200, "ok"
```

- [ ] **Step 4: Add share route tests**

Add tests:

```python
def test_share_page_returns_404_for_missing_share(self):
    server_main = load_server_main()

    class FakeCursor:
        def execute(self, *args, **kwargs): pass
        def fetchone(self): return None

    server_main.init_db = lambda: True
    server_main.cursor = FakeCursor()

    response = server_main.app.test_client().get("/api/share/missing")

    self.assertEqual(response.status_code, 404)
```

- [ ] **Step 5: Implement share APIs**

Implement:

- `POST /api/user/files/<file_hash>/shares`: validate ownership, create share.
- `GET /api/user/shares`: list current user's shares.
- `PATCH /api/user/shares/<share_code>`: update extract code, expiry, max downloads, status.
- `DELETE /api/user/shares/<share_code>`: set status `deleted`.
- `GET /api/share/<share_code>`: public metadata.
- `POST /api/share/<share_code>/verify`: verify extract code and return temporary permission token or simple success.

- [ ] **Step 6: Run tests and commit**

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','shares.py','tests/test_mysql_config.py']]"
git diff --check
git add shares.py server_main.py tests/test_mysql_config.py
git commit -m "Add share link access controls"
```

---

### Task 5: Share Download Logging and Point Ledger

**Files:**
- Create: `points.py`
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing point helper tests**

Add tests:

```python
def test_download_point_amounts_use_file_size(self):
    points = importlib.import_module("points")

    self.assertEqual(points.share_download_points(), 1)
    self.assertEqual(points.node_download_points(10), 1.0)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_download_point_amounts_use_file_size
```

- [ ] **Step 3: Create `points.py`**

Implement:

```python
SHARE_DOWNLOAD_POINTS = 1
NODE_POINTS_PER_MB = 0.1
POINTS_PER_EARNING_UNIT = 100

def share_download_points():
    return SHARE_DOWNLOAD_POINTS

def node_download_points(file_size_mb):
    return round(float(file_size_mb or 0) * NODE_POINTS_PER_MB, 6)

def points_to_earning_units(points):
    return round(float(points or 0) / POINTS_PER_EARNING_UNIT, 6)
```

- [ ] **Step 4: Implement download success transaction**

In `/api/share/<share_code>/download`:

1. Load share and file.
2. Validate share state and extract code proof.
3. Fetch encrypted content from IPFS.
4. Decrypt bytes.
5. Update `file_share.download_count`.
6. Update `file_chain_record.download_count` and `last_download_at`.
7. Insert `file_download_log`.
8. Insert owner point ledger entry.
9. Insert node point ledger entries for stored nodes.
10. Return `send_file(...)`.

Use `BytesIO` and keep the existing file download behavior for `/api/file_download/<file_hash>`.

- [ ] **Step 5: Add tests for success side effects**

Use a fake cursor that records SQL strings. Assert the endpoint executes inserts into:

- `file_download_log`
- `point_ledger`

and updates:

- `file_share`
- `file_chain_record`

- [ ] **Step 6: Run tests and commit**

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','points.py','tests/test_mysql_config.py']]"
git diff --check
git add points.py server_main.py tests/test_mysql_config.py
git commit -m "Record download logs and points"
```

---

### Task 6: Withdrawals and Admin Review

**Files:**
- Create: `withdrawals.py`
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing withdrawal helper tests**

Add tests:

```python
def test_withdrawal_amount_validation(self):
    withdrawals = importlib.import_module("withdrawals")

    self.assertEqual(withdrawals.validate_withdrawal_amount(1), (True, "ok"))
    self.assertEqual(withdrawals.validate_withdrawal_amount(0), (False, "提现金额必须大于0"))
```

- [ ] **Step 2: Create `withdrawals.py`**

Implement:

```python
VALID_WITHDRAWAL_STATUSES = {"pending", "approved", "rejected", "paid"}

def validate_withdrawal_amount(amount):
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return False, "提现金额格式错误"
    if value <= 0:
        return False, "提现金额必须大于0"
    return True, "ok"

def validate_review_status(status):
    if status not in VALID_WITHDRAWAL_STATUSES:
        return False, "提现状态无效"
    return True, "ok"
```

- [ ] **Step 3: Implement user withdrawal APIs**

Add:

- `POST /api/user/withdrawals`
- `GET /api/user/withdrawals`
- `GET /api/user/points`
- `GET /api/user/earnings`

Earnings summary should sum `point_ledger.amount` by `user_id` and convert using `points.points_to_earning_units()`.

- [ ] **Step 4: Implement admin withdrawal APIs**

Add:

- `GET /api/admin/withdrawals`
- `POST /api/admin/withdrawals/<id>/review`
- `GET /api/admin/users`
- `GET /api/admin/shares`
- `GET /api/admin/downloads`
- `GET /api/admin/points`

All routes must be added to `ADMIN_PROTECTED_PATHS` or handled by a prefix-based admin guard.

- [ ] **Step 5: Run tests and commit**

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','withdrawals.py','tests/test_mysql_config.py']]"
git diff --check
git add withdrawals.py server_main.py tests/test_mysql_config.py
git commit -m "Add withdrawals and admin review APIs"
```

---

### Task 7: User and Share Pages

**Files:**
- Modify: `server_main.py`
- Modify: `README.md`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Add page smoke tests**

Add tests:

```python
def test_user_login_page_renders(self):
    server_main = load_server_main()
    response = server_main.app.test_client().get("/user/login")
    self.assertEqual(response.status_code, 200)
    self.assertIn("钱包登录", response.get_data(as_text=True))

def test_share_page_route_renders_shell(self):
    server_main = load_server_main()
    response = server_main.app.test_client().get("/s/demo-share")
    self.assertEqual(response.status_code, 200)
    self.assertIn("下载", response.get_data(as_text=True))
```

- [ ] **Step 2: Implement `/user/login`**

Render `/user/login` as a route-level HTML page with:

- Register form.
- Username/password login form.
- Wallet login form with nonce and signature fields.
- Local storage of returned `user_token`.

- [ ] **Step 3: Implement `/user/dashboard`**

Render a page that calls:

- `/api/auth/me`
- `/api/user/files`
- `/api/user/shares`
- `/api/user/points`
- `/api/user/earnings`
- `/api/user/withdrawals`

- [ ] **Step 4: Implement `/user/upload`**

Render a page that:

- Requires local `user_token`.
- Uploads to `/api/user/files`.
- Creates share via `/api/user/files/<file_hash>/shares`.
- Displays `/s/<share_code>` link.

- [ ] **Step 5: Implement `/s/<share_code>`**

Render a public share page that:

- Calls `/api/share/<share_code>`.
- Asks for extract code when required.
- Downloads via `/api/share/<share_code>/download`.

- [ ] **Step 6: Update README**

Add a "User File Product" section documenting:

- Register/login.
- Wallet binding/login.
- Upload.
- Share link with extract code/expiry/download limit.
- Points and withdrawals.

- [ ] **Step 7: Run tests and commit**

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','tests/test_mysql_config.py']]"
git diff --check
git add server_main.py README.md tests/test_mysql_config.py
git commit -m "Add user file sharing pages"
```

---

### Task 8: Final Integration Verification

**Files:**
- Modify only files needed for defects found during verification.

- [ ] **Step 1: Run complete automated verification**

Run:

```powershell
python -B -m unittest discover
python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['server_main.py','db.py','auth.py','files.py','shares.py','points.py','withdrawals.py','tests/test_mysql_config.py']]"
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Run a local server smoke test**

Start:

```powershell
python server_main.py
```

Then check in browser or with HTTP client:

- `GET /api/health`
- `GET /user/login`
- `GET /user/dashboard`
- `GET /user/upload`
- `GET /s/demo`

Stop the server after the smoke test.

- [ ] **Step 3: Verify git state**

Run:

```powershell
git status --short
git log --oneline -5
```

Expected: only intentional final fixes are unstaged, or the working tree is clean.

- [ ] **Step 4: Commit final fixes if any**

If verification required changes:

```powershell
git add server_main.py db.py auth.py files.py shares.py points.py withdrawals.py init_postgresql.sql init_mysql.sql README.md requirements.txt tests/test_mysql_config.py
git commit -m "Polish user sharing rewards integration"
```

If no changes were required, do not create an empty commit.

---

## Self-Review Notes

Spec coverage:

- User registration/login: Task 2.
- Wallet binding and login: Task 2.
- User-owned uploads: Task 3.
- Share links with extract code, expiry, and download limits: Task 4.
- Download logging and point ledger: Task 5.
- Withdrawals and admin review: Task 6.
- User pages and README: Task 7.
- Existing behavior regression checks: Tasks 1 through 8.

No task includes real chain transfers, team spaces, paid billing, preview/transcoding, front-end framework migration, or storage repair redesign.

Implementation should prefer small commits after each task. If a task grows beyond one focused change, split it before coding.
