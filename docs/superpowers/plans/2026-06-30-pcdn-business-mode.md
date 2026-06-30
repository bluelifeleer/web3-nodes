# PCDN Business Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable PCDN partner business mode that runs on a mock third-party adapter first, while preserving the existing storage/share business as a switchable mode.

**Architecture:** Add a lightweight business mode service, then isolate PCDN-specific behavior under `app/services/pcdn` and `app/routes/pcdn.py`. Common node registration, heartbeat, earnings, withdrawals, and admin shell stay shared; mode-specific menus, APIs, labels, and settlement logic live behind `BUSINESS_MODE` and `PCDN_PROVIDER`.

**Tech Stack:** Flask, existing Python service modules, SQL schema files, Jinja templates, plain JavaScript/CSS, `unittest` in `tests/test_mysql_config.py`.

---

## File Structure

- Create `app/services/business.py`: normalize business mode/provider and expose helpers used by routes/templates.
- Modify `app/config.py`: add `business_mode` and `pcdn_provider` to `ServerConfig`.
- Modify `app/schema/init_mysql.sql` and `app/schema/init_postgresql.sql`: add `pcdn_` tables.
- Create `app/services/pcdn/__init__.py`: package marker and public exports.
- Create `app/services/pcdn/adapters/__init__.py`: adapter registry exports.
- Create `app/services/pcdn/adapters/base.py`: adapter interface and normalized helpers.
- Create `app/services/pcdn/adapters/mock.py`: deterministic mock third-party PCDN adapter.
- Create `app/services/pcdn/adapters/registry.py`: provider selection.
- Create `app/services/pcdn/service.py`: DB-facing PCDN task, metric, sync, and settlement helpers.
- Create `app/routes/pcdn.py`: `/api/pcdn/*` routes.
- Modify `app/routes/__init__.py`: register PCDN blueprint.
- Modify `app/routes/pages.py`: pass business mode/provider into templates.
- Modify `app/templates/admin_dashboard.html`: add PCDN dashboard section and mode-aware menu markers.
- Modify `app/static/js/admin-dashboard.js`: load PCDN status/tasks/metrics/settlement in PCDN mode.
- Modify `app/static/css/admin-dashboard.css`: add PCDN dashboard table/card styles and hide inactive business menus.
- Modify `client/config.py`, `client/main.py`, and `client/console.py`: include business mode in client state/status and relabel storage as cache in PCDN mode.
- Modify `README.md`: document `BUSINESS_MODE`, `PCDN_PROVIDER`, and switching examples.
- Modify `tests/test_mysql_config.py`: add all regression tests before implementation.

---

### Task 1: Business Mode Config

**Files:**
- Create: `app/services/business.py`
- Modify: `app/config.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests for mode normalization and config**

Add these tests inside `MysqlConfigTest` in `tests/test_mysql_config.py` near other config tests:

```python
    def test_business_mode_helpers_normalize_modes_and_provider(self):
        business = importlib.import_module("app.services.business")

        self.assertEqual(business.normalize_business_mode("pcdn_partner"), "pcdn_partner")
        self.assertEqual(business.normalize_business_mode(" PCDN "), "pcdn_partner")
        self.assertEqual(business.normalize_business_mode("storage_share"), "storage_share")
        self.assertEqual(business.normalize_business_mode("unknown"), "storage_share")
        self.assertTrue(business.business_mode_is_pcdn("pcdn_partner"))
        self.assertFalse(business.business_mode_is_pcdn("storage_share"))
        self.assertEqual(business.normalize_pcdn_provider(""), "mock")
        self.assertEqual(business.normalize_pcdn_provider(" Vendor-A "), "vendor-a")

    def test_server_config_reads_business_mode_and_pcdn_provider(self):
        server_main = load_server_main(BUSINESS_MODE="pcdn_partner", PCDN_PROVIDER="mock")

        self.assertEqual(server_main.SERVER_CONFIG.business_mode, "pcdn_partner")
        self.assertEqual(server_main.SERVER_CONFIG.pcdn_provider, "mock")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_business_mode_helpers_normalize_modes_and_provider tests.test_mysql_config.MysqlConfigTest.test_server_config_reads_business_mode_and_pcdn_provider
```

Expected: failure because `app.services.business` does not exist or `ServerConfig` lacks the new fields.

- [ ] **Step 3: Implement `app/services/business.py`**

Create:

```python
import os

STORAGE_SHARE_MODE = "storage_share"
PCDN_PARTNER_MODE = "pcdn_partner"
SUPPORTED_BUSINESS_MODES = {STORAGE_SHARE_MODE, PCDN_PARTNER_MODE}


def normalize_business_mode(value=""):
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in ("pcdn", "pcdn_partner", "partner_pcdn"):
        return PCDN_PARTNER_MODE
    if raw in SUPPORTED_BUSINESS_MODES:
        return raw
    return STORAGE_SHARE_MODE


def normalize_pcdn_provider(value=""):
    raw = str(value or "").strip().lower().replace("_", "-")
    return raw or "mock"


def current_business_mode(environ=os.environ):
    return normalize_business_mode(environ.get("BUSINESS_MODE", STORAGE_SHARE_MODE))


def current_pcdn_provider(environ=os.environ):
    return normalize_pcdn_provider(environ.get("PCDN_PROVIDER", "mock"))


def business_mode_is_pcdn(mode):
    return normalize_business_mode(mode) == PCDN_PARTNER_MODE
```

- [ ] **Step 4: Modify `app/config.py`**

Add import:

```python
from app.services.business import current_business_mode, current_pcdn_provider
```

Add dataclass fields:

```python
    business_mode: str
    pcdn_provider: str
```

Add in `from_env`:

```python
            business_mode=current_business_mode(environ),
            pcdn_provider=current_pcdn_provider(environ),
```

- [ ] **Step 5: Run tests to verify pass**

Run the same targeted command from Step 2.

Expected: `OK`.

- [ ] **Step 6: Commit**

```powershell
git add app\config.py app\services\business.py tests\test_mysql_config.py
git commit -m "feat: add business mode config"
```

---

### Task 2: PCDN Schema Tables

**Files:**
- Modify: `app/schema/init_mysql.sql`
- Modify: `app/schema/init_postgresql.sql`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing schema tests**

Add near existing schema tests:

```python
    def test_pcdn_schema_tables_are_declared(self):
        mysql_sql = Path("app/schema/init_mysql.sql").read_text(encoding="utf-8")
        postgres_sql = Path("app/schema/init_postgresql.sql").read_text(encoding="utf-8")

        for sql in (mysql_sql, postgres_sql):
            for table in (
                "pcdn_task",
                "pcdn_node_metric",
                "pcdn_settlement",
                "pcdn_provider_sync_log",
            ):
                self.assertIn(table, sql)
            for field in (
                "provider",
                "vendor_task_id",
                "traffic_gb",
                "bandwidth_mbps",
                "cache_hit_rate",
                "raw_payload_json",
            ):
                self.assertIn(field, sql)
```

- [ ] **Step 2: Run test to verify failure**

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_pcdn_schema_tables_are_declared
```

Expected: failure because `pcdn_` tables are missing.

- [ ] **Step 3: Add MySQL schema**

Append to `app/schema/init_mysql.sql`:

```sql
CREATE TABLE IF NOT EXISTS `pcdn_task` (
  `id` int NOT NULL AUTO_INCREMENT,
  `task_name` varchar(128) DEFAULT '',
  `provider` varchar(64) DEFAULT 'mock',
  `vendor_task_id` varchar(128) DEFAULT '',
  `resource_url` varchar(512) DEFAULT '',
  `domain` varchar(255) DEFAULT '',
  `status` varchar(32) DEFAULT 'created',
  `created_by` varchar(128) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_pcdn_task_provider` (`provider`),
  KEY `idx_pcdn_task_vendor` (`vendor_task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `pcdn_node_metric` (
  `id` int NOT NULL AUTO_INCREMENT,
  `provider` varchar(64) DEFAULT 'mock',
  `vendor_task_id` varchar(128) DEFAULT '',
  `node_address` varchar(128) DEFAULT '',
  `resource_url` varchar(512) DEFAULT '',
  `domain` varchar(255) DEFAULT '',
  `bandwidth_mbps` float DEFAULT 0,
  `traffic_gb` float DEFAULT 0,
  `online_minutes` float DEFAULT 0,
  `cache_hit_rate` float DEFAULT 0,
  `started_at` datetime DEFAULT NULL,
  `ended_at` datetime DEFAULT NULL,
  `raw_payload_json` text,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_pcdn_metric_node` (`node_address`),
  KEY `idx_pcdn_metric_task` (`vendor_task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `pcdn_settlement` (
  `id` int NOT NULL AUTO_INCREMENT,
  `provider` varchar(64) DEFAULT 'mock',
  `vendor_task_id` varchar(128) DEFAULT '',
  `node_address` varchar(128) DEFAULT '',
  `metric_window` varchar(64) DEFAULT '',
  `contribution_score` float DEFAULT 0,
  `amount` float DEFAULT 0,
  `status` varchar(32) DEFAULT 'pending',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_pcdn_settlement_node` (`node_address`),
  KEY `idx_pcdn_settlement_task` (`vendor_task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `pcdn_provider_sync_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `provider` varchar(64) DEFAULT 'mock',
  `sync_type` varchar(64) DEFAULT '',
  `status` varchar(32) DEFAULT '',
  `message` varchar(512) DEFAULT '',
  `request_id` varchar(128) DEFAULT '',
  `raw_summary_json` text,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_pcdn_sync_provider` (`provider`),
  KEY `idx_pcdn_sync_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 4: Add PostgreSQL schema**

Append equivalent PostgreSQL DDL:

```sql
CREATE TABLE IF NOT EXISTS pcdn_task (
  id serial PRIMARY KEY,
  task_name varchar(128) DEFAULT '',
  provider varchar(64) DEFAULT 'mock',
  vendor_task_id varchar(128) DEFAULT '',
  resource_url varchar(512) DEFAULT '',
  domain varchar(255) DEFAULT '',
  status varchar(32) DEFAULT 'created',
  created_by varchar(128) DEFAULT '',
  created_at timestamp DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pcdn_task_provider ON pcdn_task (provider);
CREATE INDEX IF NOT EXISTS idx_pcdn_task_vendor ON pcdn_task (vendor_task_id);

CREATE TABLE IF NOT EXISTS pcdn_node_metric (
  id serial PRIMARY KEY,
  provider varchar(64) DEFAULT 'mock',
  vendor_task_id varchar(128) DEFAULT '',
  node_address varchar(128) DEFAULT '',
  resource_url varchar(512) DEFAULT '',
  domain varchar(255) DEFAULT '',
  bandwidth_mbps double precision DEFAULT 0,
  traffic_gb double precision DEFAULT 0,
  online_minutes double precision DEFAULT 0,
  cache_hit_rate double precision DEFAULT 0,
  started_at timestamp DEFAULT NULL,
  ended_at timestamp DEFAULT NULL,
  raw_payload_json text,
  created_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pcdn_metric_node ON pcdn_node_metric (node_address);
CREATE INDEX IF NOT EXISTS idx_pcdn_metric_task ON pcdn_node_metric (vendor_task_id);

CREATE TABLE IF NOT EXISTS pcdn_settlement (
  id serial PRIMARY KEY,
  provider varchar(64) DEFAULT 'mock',
  vendor_task_id varchar(128) DEFAULT '',
  node_address varchar(128) DEFAULT '',
  metric_window varchar(64) DEFAULT '',
  contribution_score double precision DEFAULT 0,
  amount double precision DEFAULT 0,
  status varchar(32) DEFAULT 'pending',
  created_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pcdn_settlement_node ON pcdn_settlement (node_address);
CREATE INDEX IF NOT EXISTS idx_pcdn_settlement_task ON pcdn_settlement (vendor_task_id);

CREATE TABLE IF NOT EXISTS pcdn_provider_sync_log (
  id serial PRIMARY KEY,
  provider varchar(64) DEFAULT 'mock',
  sync_type varchar(64) DEFAULT '',
  status varchar(32) DEFAULT '',
  message varchar(512) DEFAULT '',
  request_id varchar(128) DEFAULT '',
  raw_summary_json text,
  created_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pcdn_sync_provider ON pcdn_provider_sync_log (provider);
CREATE INDEX IF NOT EXISTS idx_pcdn_sync_status ON pcdn_provider_sync_log (status);
```

- [ ] **Step 5: Run test to verify pass**

Run the targeted test from Step 2.

Expected: `OK`.

- [ ] **Step 6: Commit**

```powershell
git add app\schema\init_mysql.sql app\schema\init_postgresql.sql tests\test_mysql_config.py
git commit -m "feat: add pcdn schema tables"
```

---

### Task 3: Mock PCDN Adapter

**Files:**
- Create: `app/services/pcdn/__init__.py`
- Create: `app/services/pcdn/adapters/__init__.py`
- Create: `app/services/pcdn/adapters/base.py`
- Create: `app/services/pcdn/adapters/mock.py`
- Create: `app/services/pcdn/adapters/registry.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing adapter tests**

Add:

```python
    def test_mock_pcdn_adapter_returns_deterministic_contract_data(self):
        registry = importlib.import_module("app.services.pcdn.adapters.registry")

        adapter = registry.get_pcdn_adapter("mock")
        health = adapter.health()
        resources = adapter.list_resources()
        task = adapter.create_task({"task_name": "demo", "resource_url": "https://example.com/video.mp4"})
        metrics = adapter.sync_usage()

        self.assertEqual(adapter.provider_name, "mock")
        self.assertTrue(health["online"])
        self.assertEqual(resources[0]["provider"], "mock")
        self.assertEqual(task["vendor_task_id"], "mock-task-demo")
        self.assertEqual(metrics[0]["provider"], "mock")
        self.assertIn("traffic_gb", metrics[0])
        self.assertIn("bandwidth_mbps", metrics[0])
        self.assertIn("cache_hit_rate", metrics[0])
```

- [ ] **Step 2: Run test to verify failure**

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_mock_pcdn_adapter_returns_deterministic_contract_data
```

Expected: import failure.

- [ ] **Step 3: Create adapter files**

`app/services/pcdn/adapters/base.py`:

```python
from abc import ABC, abstractmethod


class PcdnAdapter(ABC):
    provider_name = ""

    @abstractmethod
    def list_resources(self):
        raise NotImplementedError

    @abstractmethod
    def create_task(self, task):
        raise NotImplementedError

    @abstractmethod
    def get_task(self, task_id):
        raise NotImplementedError

    @abstractmethod
    def sync_usage(self, since=None, until=None):
        raise NotImplementedError

    @abstractmethod
    def health(self):
        raise NotImplementedError
```

`app/services/pcdn/adapters/mock.py`:

```python
from datetime import datetime, timedelta

from app.services.pcdn.adapters.base import PcdnAdapter


class MockPcdnAdapter(PcdnAdapter):
    provider_name = "mock"

    def list_resources(self):
        return [{
            "provider": self.provider_name,
            "resource_url": "https://mock.example.com/video.mp4",
            "domain": "mock.example.com",
            "status": "active",
            "cache_hit_rate": 0.91,
        }]

    def create_task(self, task):
        task_name = str(task.get("task_name") or "demo").strip() or "demo"
        resource_url = str(task.get("resource_url") or "https://mock.example.com/video.mp4").strip()
        return {
            "provider": self.provider_name,
            "vendor_task_id": f"mock-task-{task_name}",
            "task_name": task_name,
            "resource_url": resource_url,
            "domain": resource_url.split("/")[2] if "://" in resource_url else "",
            "status": "running",
        }

    def get_task(self, task_id):
        return {
            "provider": self.provider_name,
            "vendor_task_id": str(task_id or "mock-task-demo"),
            "task_name": "demo",
            "resource_url": "https://mock.example.com/video.mp4",
            "domain": "mock.example.com",
            "status": "running",
        }

    def sync_usage(self, since=None, until=None):
        ended_at = datetime.now().replace(microsecond=0)
        started_at = ended_at - timedelta(minutes=60)
        return [{
            "provider": self.provider_name,
            "vendor_task_id": "mock-task-demo",
            "node_address": "MOCK_NODE_A",
            "resource_url": "https://mock.example.com/video.mp4",
            "domain": "mock.example.com",
            "bandwidth_mbps": 12.5,
            "traffic_gb": 18.75,
            "online_minutes": 60,
            "cache_hit_rate": 0.91,
            "started_at": started_at.isoformat(sep=" "),
            "ended_at": ended_at.isoformat(sep=" "),
            "raw_payload_json": '{"mock":true}',
        }]

    def health(self):
        return {"provider": self.provider_name, "online": True, "status": "ok", "message": "mock adapter ready"}
```

`app/services/pcdn/adapters/registry.py`:

```python
from app.services.business import normalize_pcdn_provider
from app.services.pcdn.adapters.mock import MockPcdnAdapter


def get_pcdn_adapter(provider="mock"):
    normalized = normalize_pcdn_provider(provider)
    if normalized == "mock":
        return MockPcdnAdapter()
    return MockPcdnAdapter()
```

`app/services/pcdn/adapters/__init__.py`:

```python
from app.services.pcdn.adapters.registry import get_pcdn_adapter

__all__ = ["get_pcdn_adapter"]
```

`app/services/pcdn/__init__.py`:

```python
"""PCDN business services."""
```

- [ ] **Step 4: Run test to verify pass**

Run targeted command from Step 2.

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add app\services\pcdn tests\test_mysql_config.py
git commit -m "feat: add mock pcdn adapter"
```

---

### Task 4: PCDN Services And Routes

**Files:**
- Create: `app/services/pcdn/service.py`
- Create: `app/routes/pcdn.py`
- Modify: `app/routes/__init__.py`
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing route tests**

Add:

```python
    def test_pcdn_routes_return_mock_business_data_in_pcdn_mode(self):
        server_main = load_server_main(
            ADMIN_API_TOKEN="secret-token",
            BUSINESS_MODE="pcdn_partner",
            PCDN_PROVIDER="mock",
        )
        server_main.init_db = lambda: True
        client = server_main.app.test_client()
        headers = {"X-Admin-Token": "secret-token"}

        status = client.get("/api/pcdn/status", headers=headers)
        tasks = client.get("/api/pcdn/tasks", headers=headers)
        created = client.post(
            "/api/pcdn/tasks",
            headers=headers,
            json={"task_name": "demo", "resource_url": "https://example.com/video.mp4"},
        )
        sync = client.post("/api/pcdn/sync", headers=headers, json={})
        settlements = client.post("/api/pcdn/settlements/run", headers=headers, json={})

        self.assertEqual(status.status_code, 200)
        self.assertEqual(tasks.status_code, 200)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(sync.status_code, 200)
        self.assertEqual(settlements.status_code, 200)
        self.assertEqual(status.get_json()["data"]["business_mode"], "pcdn_partner")
        self.assertEqual(created.get_json()["data"]["vendor_task_id"], "mock-task-demo")
        self.assertTrue(sync.get_json()["data"]["metrics"])
        self.assertTrue(settlements.get_json()["data"]["settlements"])

    def test_pcdn_routes_reject_admin_requests_without_token(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token", BUSINESS_MODE="pcdn_partner")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/api/pcdn/status")

        self.assertEqual(response.status_code, 401)
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_pcdn_routes_return_mock_business_data_in_pcdn_mode tests.test_mysql_config.MysqlConfigTest.test_pcdn_routes_reject_admin_requests_without_token
```

Expected: 404 or import failure.

- [ ] **Step 3: Implement service**

Create `app/services/pcdn/service.py`:

```python
from app.services.business import business_mode_is_pcdn
from app.services.pcdn.adapters.registry import get_pcdn_adapter


def pcdn_status(server_config):
    adapter = get_pcdn_adapter(server_config.pcdn_provider)
    health = adapter.health()
    return {
        "business_mode": server_config.business_mode,
        "provider": server_config.pcdn_provider,
        "enabled": business_mode_is_pcdn(server_config.business_mode),
        "health": health,
    }


def list_tasks(server_config):
    adapter = get_pcdn_adapter(server_config.pcdn_provider)
    return [adapter.get_task("mock-task-demo")]


def create_task(server_config, payload):
    adapter = get_pcdn_adapter(server_config.pcdn_provider)
    return adapter.create_task(payload or {})


def sync_usage(server_config):
    adapter = get_pcdn_adapter(server_config.pcdn_provider)
    metrics = adapter.sync_usage()
    return {"provider": server_config.pcdn_provider, "metrics": metrics, "count": len(metrics)}


def build_settlements_from_metrics(metrics):
    settlements = []
    for item in metrics:
        traffic = float(item.get("traffic_gb") or 0)
        bandwidth = float(item.get("bandwidth_mbps") or 0)
        online = float(item.get("online_minutes") or 0)
        hit_rate = float(item.get("cache_hit_rate") or 0)
        score = round(traffic * 1.0 + bandwidth * 0.2 + online * 0.05 + hit_rate * 10, 4)
        settlements.append({
            "provider": item.get("provider") or "mock",
            "vendor_task_id": item.get("vendor_task_id") or "",
            "node_address": item.get("node_address") or "",
            "metric_window": f"{item.get('started_at') or ''} - {item.get('ended_at') or ''}",
            "contribution_score": score,
            "amount": round(score * 0.01, 4),
            "status": "settled",
        })
    return settlements


def run_settlement(server_config):
    metrics = get_pcdn_adapter(server_config.pcdn_provider).sync_usage()
    return {"provider": server_config.pcdn_provider, "settlements": build_settlements_from_metrics(metrics)}
```

- [ ] **Step 4: Implement routes**

Create `app/routes/pcdn.py`:

```python
from flask import Blueprint, jsonify

from app.services import pcdn


bp = Blueprint("pcdn_api", __name__)


def legacy_server():
    import server_main

    return server_main


def require_admin():
    legacy = legacy_server()
    response = legacy.require_admin_token()
    return response


@bp.route("/api/pcdn/status", methods=["GET"])
def pcdn_status():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({"code": 200, "data": pcdn.service.pcdn_status(legacy.SERVER_CONFIG)})


@bp.route("/api/pcdn/tasks", methods=["GET"])
def pcdn_tasks():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({"code": 200, "data": pcdn.service.list_tasks(legacy.SERVER_CONFIG)})


@bp.route("/api/pcdn/tasks", methods=["POST"])
def pcdn_task_create():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({"code": 200, "msg": "PCDN task created", "data": pcdn.service.create_task(legacy.SERVER_CONFIG, legacy.get_json_body())})


@bp.route("/api/pcdn/sync", methods=["POST"])
def pcdn_sync():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({"code": 200, "msg": "PCDN usage synced", "data": pcdn.service.sync_usage(legacy.SERVER_CONFIG)})


@bp.route("/api/pcdn/node_metrics", methods=["GET"])
def pcdn_node_metrics():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    data = pcdn.service.sync_usage(legacy.SERVER_CONFIG)
    return jsonify({"code": 200, "data": data["metrics"]})


@bp.route("/api/pcdn/settlements", methods=["GET"])
@bp.route("/api/pcdn/settlements/run", methods=["POST"])
def pcdn_settlements():
    guard = require_admin()
    if guard:
        return guard
    legacy = legacy_server()
    return jsonify({"code": 200, "msg": "PCDN settlements ready", "data": pcdn.service.run_settlement(legacy.SERVER_CONFIG)})
```

Update `app/services/pcdn/__init__.py`:

```python
from app.services.pcdn import service

__all__ = ["service"]
```

Update `app/routes/__init__.py` to import and register `pcdn.bp`.

- [ ] **Step 5: Expose route module in server compatibility**

If `tests/test_mysql_config.py` has a modularization test expecting route modules, add `pcdn_routes = importlib.import_module("app.routes.pcdn")` and assert relevant endpoints use that module.

- [ ] **Step 6: Run tests to verify pass**

Run targeted command from Step 2.

Expected: `OK`.

- [ ] **Step 7: Commit**

```powershell
git add app\routes\__init__.py app\routes\pcdn.py app\services\pcdn tests\test_mysql_config.py
git commit -m "feat: add pcdn mock api routes"
```

---

### Task 5: Mode-Aware Admin UI

**Files:**
- Modify: `app/routes/pages.py`
- Modify: `app/templates/admin_dashboard.html`
- Modify: `app/static/js/admin-dashboard.js`
- Modify: `app/static/css/admin-dashboard.css`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing admin UI tests**

Add:

```python
    def test_admin_dashboard_shows_pcdn_sections_in_pcdn_mode(self):
        server_main = load_server_main(ADMIN_API_TOKEN="secret-token", BUSINESS_MODE="pcdn_partner", PCDN_PROVIDER="mock")
        server_main.init_db = lambda: True

        response = server_main.app.test_client().get("/admin")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        admin_source = body + read_static_asset_or_empty("app/static/js/admin-dashboard.js") + read_static_asset_or_empty("app/static/css/admin-dashboard.css")
        self.assertIn('data-business-mode="pcdn_partner"', body)
        self.assertIn('id="pcdnDashboardSection"', body)
        self.assertIn('id="pcdnTaskTable"', body)
        self.assertIn("/api/pcdn/status", admin_source)
        self.assertIn("/api/pcdn/tasks", admin_source)
        self.assertIn("/api/pcdn/sync", admin_source)
        self.assertIn(".business-storage-share", admin_source)
        self.assertIn(".business-pcdn-partner", admin_source)
```

- [ ] **Step 2: Run test to verify failure**

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_admin_dashboard_shows_pcdn_sections_in_pcdn_mode
```

Expected: failure because dashboard has no PCDN section or mode markers.

- [ ] **Step 3: Pass config into admin template**

In `app/routes/pages.py` `admin_index()`, add:

```python
        business_mode=legacy.SERVER_CONFIG.business_mode,
        pcdn_provider=legacy.SERVER_CONFIG.pcdn_provider,
```

- [ ] **Step 4: Add admin template section**

In `app/templates/admin_dashboard.html`, change shell opening to:

```html
    <div class="unified-console-shell" data-console-role="admin" data-business-mode="{{ business_mode }}">
```

Add PCDN menu items with class `business-pcdn-partner` and existing file/share items with class `business-storage-share`.

Add section before file evidence section:

```html
    <div class="box commercial-card business-pcdn-partner" id="pcdnDashboardSection">
        <h3>PCDN 业务看板</h3>
        <div class="admin-status-bar">
            <strong>当前模式</strong>
            <span id="pcdnModeText">{{ business_mode }} / {{ pcdn_provider }}</span>
            <button onclick="syncPcdnUsage()">同步模拟厂商数据</button>
            <button onclick="runPcdnSettlement()">运行结算</button>
        </div>
        <div class="admin-node-grid">
            <table>
                <thead><tr><th>任务</th><th>资源</th><th>厂商任务</th><th>状态</th><th>Provider</th></tr></thead>
                <tbody id="pcdnTaskTable"></tbody>
            </table>
        </div>
        <div class="admin-node-grid" style="margin-top:12px">
            <table>
                <thead><tr><th>节点</th><th>流量GB</th><th>带宽Mbps</th><th>在线分钟</th><th>命中率</th></tr></thead>
                <tbody id="pcdnMetricTable"></tbody>
            </table>
        </div>
        <pre id="pcdnSyncLog" style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:6px;margin-top:10px;"></pre>
    </div>
```

- [ ] **Step 5: Add CSS mode visibility**

In `app/static/css/admin-dashboard.css`:

```css
.unified-console-shell[data-business-mode="storage_share"] .business-pcdn-partner{display:none;}
.unified-console-shell[data-business-mode="pcdn_partner"] .business-storage-share{display:none;}
```

- [ ] **Step 6: Add admin JS loaders**

In `app/static/js/admin-dashboard.js`, add:

```javascript
function getBusinessMode(){
    const shell = document.querySelector(".unified-console-shell");
    return shell ? shell.dataset.businessMode || "storage_share" : "storage_share";
}

function renderPcdnTasks(rows){
    const table = document.getElementById("pcdnTaskTable");
    if(!table){ return; }
    table.innerHTML = (rows || []).map(item => `<tr><td>${escHtml(item.task_name || "")}</td><td>${escHtml(item.resource_url || item.domain || "")}</td><td>${escHtml(item.vendor_task_id || "")}</td><td>${escHtml(item.status || "")}</td><td>${escHtml(item.provider || "")}</td></tr>`).join("") || '<tr><td colspan="5">暂无 PCDN 任务</td></tr>';
}

function renderPcdnMetrics(rows){
    const table = document.getElementById("pcdnMetricTable");
    if(!table){ return; }
    table.innerHTML = (rows || []).map(item => `<tr><td>${escHtml(item.node_address || "")}</td><td>${escHtml(item.traffic_gb || 0)}</td><td>${escHtml(item.bandwidth_mbps || 0)}</td><td>${escHtml(item.online_minutes || 0)}</td><td>${escHtml(item.cache_hit_rate || 0)}</td></tr>`).join("") || '<tr><td colspan="5">暂无 PCDN 指标</td></tr>';
}

function refreshPcdnDashboard(){
    if(getBusinessMode() !== "pcdn_partner"){ return; }
    adminFetch("/api/pcdn/tasks").then(res=>res.json()).then(data=>renderPcdnTasks(data.data || []));
    adminFetch("/api/pcdn/node_metrics").then(res=>res.json()).then(data=>renderPcdnMetrics(data.data || []));
    adminFetch("/api/pcdn/status").then(res=>res.json()).then(data=>{
        const log = document.getElementById("pcdnSyncLog");
        if(log){ log.innerText = JSON.stringify(data.data || {}, null, 2); }
    });
}

function syncPcdnUsage(){
    adminFetch("/api/pcdn/sync", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
    .then(res=>res.json()).then(data=>{
        const log = document.getElementById("pcdnSyncLog");
        if(log){ log.innerText = JSON.stringify(data, null, 2); }
        refreshPcdnDashboard();
    });
}

function runPcdnSettlement(){
    adminFetch("/api/pcdn/settlements/run", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
    .then(res=>res.json()).then(data=>{
        const log = document.getElementById("pcdnSyncLog");
        if(log){ log.innerText = JSON.stringify(data, null, 2); }
    });
}
```

Call `refreshPcdnDashboard();` inside `refreshAdminData()`.

- [ ] **Step 7: Run test to verify pass**

Run targeted command from Step 2.

Expected: `OK`.

- [ ] **Step 8: Commit**

```powershell
git add app\routes\pages.py app\templates\admin_dashboard.html app\static\js\admin-dashboard.js app\static\css\admin-dashboard.css tests\test_mysql_config.py
git commit -m "feat: add pcdn admin dashboard mode"
```

---

### Task 6: Client Business Mode And Cache Labels

**Files:**
- Modify: `client/config.py`
- Modify: `client/main.py`
- Modify: `client/console.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing client tests**

Add:

```python
    def test_client_config_and_status_include_business_mode(self):
        old_env = os.environ.get("NODE_BUSINESS_MODE")
        try:
            os.environ["NODE_BUSINESS_MODE"] = "pcdn_partner"
            sys.modules.pop("client.config", None)
            config_module = importlib.import_module("client.config")
            config = config_module.load_client_config("tests/missing-node-config.json")

            self.assertEqual(config["business_mode"], "pcdn_partner")
        finally:
            if old_env is None:
                os.environ.pop("NODE_BUSINESS_MODE", None)
            else:
                os.environ["NODE_BUSINESS_MODE"] = old_env
            sys.modules.pop("client.config", None)

    def test_client_console_contains_pcdn_cache_labels(self):
        console = importlib.import_module("client.console")
        html = console.CLIENT_MANAGE_HTML

        self.assertIn("data-business-mode", html)
        self.assertIn("PCDN 缓存目录", html)
        self.assertIn("Cache directory", html)
        self.assertIn("applyBusinessModeLabels", html)
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_client_config_and_status_include_business_mode tests.test_mysql_config.MysqlConfigTest.test_client_console_contains_pcdn_cache_labels
```

Expected: failure because client config/console do not include business mode labels.

- [ ] **Step 3: Modify `client/config.py`**

Add default:

```python
DEFAULT_BUSINESS_MODE = "storage_share"
```

Add to config dict:

```python
        "business_mode": DEFAULT_BUSINESS_MODE,
```

Add env override:

```python
    config["business_mode"] = os.getenv("NODE_BUSINESS_MODE", os.getenv("BUSINESS_MODE", config.get("business_mode", DEFAULT_BUSINESS_MODE))).strip() or DEFAULT_BUSINESS_MODE
```

- [ ] **Step 4: Modify `client/main.py`**

Pass `config["business_mode"]` into `create_client_state` by adding a parameter default:

```python
def create_client_state(..., business_mode="storage_share"):
```

Add to returned state:

```python
        "business_mode": business_mode or "storage_share",
```

Add to `public_status(state)`:

```python
        "business_mode": state.get("business_mode", "storage_share"),
```

When calling `create_client_state`, pass `config.get("business_mode", "storage_share")`.

- [ ] **Step 5: Modify `client/console.py`**

Add a shell attribute:

```html
<main class="node-console-shell" data-business-mode="storage_share">
```

Add hidden copy markers near the shell:

```html
<span hidden data-storage-label="storage">存储目录</span>
<span hidden data-storage-label="pcdn">PCDN 缓存目录</span>
<span hidden>Cache directory</span>
```

Add JS:

```javascript
function applyBusinessModeLabels(mode){
  const normalized = mode === "pcdn_partner" ? "pcdn_partner" : "storage_share";
  const shell = document.querySelector(".node-console-shell");
  if (shell) shell.dataset.businessMode = normalized;
  const storageTitle = document.querySelector("#storageSection h2");
  if (storageTitle) storageTitle.textContent = normalized === "pcdn_partner" ? "PCDN 缓存目录管理" : "存储目录管理";
  const localTitle = document.querySelector("#localShardSection h2");
  if (localTitle) localTitle.innerHTML = normalized === "pcdn_partner"
    ? '本机缓存记录 <span id="localShardUsage" class="usage-meter">0 B</span>'
    : '本机已存文件 <span id="localShardUsage" class="usage-meter">0 B</span>';
}
```

Call inside `applyStatus`:

```javascript
      applyBusinessModeLabels(data.business_mode || "storage_share");
```

- [ ] **Step 6: Run tests to verify pass**

Run targeted command from Step 2.

Expected: `OK`.

- [ ] **Step 7: Commit**

```powershell
git add client\config.py client\main.py client\console.py tests\test_mysql_config.py
git commit -m "feat: expose pcdn mode in client console"
```

---

### Task 7: PCDN Settlement Reward Integration

**Files:**
- Modify: `app/services/pcdn/service.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing settlement calculation test**

Add:

```python
    def test_pcdn_settlement_calculates_repeatable_rewards(self):
        service = importlib.import_module("app.services.pcdn.service")
        metrics = [{
            "provider": "mock",
            "vendor_task_id": "mock-task-demo",
            "node_address": "NODE_A",
            "traffic_gb": 10,
            "bandwidth_mbps": 5,
            "online_minutes": 20,
            "cache_hit_rate": 0.8,
            "started_at": "2026-06-30 10:00:00",
            "ended_at": "2026-06-30 11:00:00",
        }]

        settlements = service.build_settlements_from_metrics(metrics)

        self.assertEqual(settlements[0]["node_address"], "NODE_A")
        self.assertEqual(settlements[0]["contribution_score"], 20.0)
        self.assertEqual(settlements[0]["amount"], 0.2)
        self.assertEqual(settlements[0]["status"], "settled")
```

- [ ] **Step 2: Run test to verify failure or mismatch**

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_pcdn_settlement_calculates_repeatable_rewards
```

Expected: failure if Task 4 did not yet implement the exact calculation.

- [ ] **Step 3: Adjust settlement formula**

Ensure `build_settlements_from_metrics` calculates:

```python
score = round(traffic * 1.0 + bandwidth * 0.2 + online * 0.05 + hit_rate * 10, 4)
amount = round(score * 0.01, 4)
```

For the test input, score is `10 + 1 + 1 + 8 = 20.0`, amount is `0.2`.

- [ ] **Step 4: Run test to verify pass**

Run targeted command from Step 2.

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add app\services\pcdn\service.py tests\test_mysql_config.py
git commit -m "feat: calculate pcdn settlement rewards"
```

---

### Task 8: README And Full Regression

**Files:**
- Modify: `README.md`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing README coverage test**

Add:

```python
    def test_readme_documents_pcdn_business_mode_switching(self):
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("BUSINESS_MODE", readme)
        self.assertIn("storage_share", readme)
        self.assertIn("pcdn_partner", readme)
        self.assertIn("PCDN_PROVIDER", readme)
        self.assertIn("mock", readme)
```

- [ ] **Step 2: Run test to verify failure**

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_readme_documents_pcdn_business_mode_switching
```

Expected: failure until README is updated.

- [ ] **Step 3: Update README**

Add a section:

```markdown
## Business mode switching

The platform supports two business modes:

- `storage_share`: current encrypted file upload, shard storage, share links, downloads, and file-based node rewards.
- `pcdn_partner`: third-party PCDN mode. The first provider is `mock`, which runs locally without vendor credentials and is used to validate PCDN tasks, metrics, settlement, and withdrawal flows.

Example:

```powershell
$env:BUSINESS_MODE="pcdn_partner"
$env:PCDN_PROVIDER="mock"
python .\server_main.py
```

Switch back:

```powershell
$env:BUSINESS_MODE="storage_share"
python .\server_main.py
```

Client cache/node mode:

```powershell
$env:NODE_BUSINESS_MODE="pcdn_partner"
python .\client\main.py --storage-dir=D:\pcdn-cache --storage_quota_gb=100
```
```

- [ ] **Step 4: Run README test**

Run targeted command from Step 2.

Expected: `OK`.

- [ ] **Step 5: Run full regression**

```powershell
python -B -m unittest tests.test_mysql_config
```

Expected: `Ran ... tests ... OK`.

- [ ] **Step 6: Clean test cache side effects**

Run:

```powershell
git checkout -- __pycache__/server_main.cpython-314.pyc
```

Then clean source pycache directories if present:

```powershell
$root = (Resolve-Path -LiteralPath '.').Path
$dirs = @('app\__pycache__','app\routes\__pycache__','app\services\__pycache__','app\web\__pycache__','client\__pycache__','tests\__pycache__')
foreach ($dir in $dirs) {
  $target = Resolve-Path -LiteralPath $dir -ErrorAction SilentlyContinue
  if ($target -and $target.Path.StartsWith($root)) {
    Remove-Item -LiteralPath $target.Path -Recurse -Force
  }
}
```

- [ ] **Step 7: Commit**

```powershell
git add README.md tests\test_mysql_config.py
git commit -m "docs: document pcdn business mode switching"
```

---

## Final Verification

- [ ] Run:

```powershell
git status --short
```

Expected: only intentionally uncommitted user work remains, or clean if all feature work has been committed.

- [ ] Run:

```powershell
python -B -m unittest tests.test_mysql_config
```

Expected: all tests pass.

- [ ] Confirm manual smoke paths:

```powershell
$env:BUSINESS_MODE="pcdn_partner"
$env:PCDN_PROVIDER="mock"
python .\server_main.py
```

Open:

- `http://127.0.0.1:8000/admin`
- `http://127.0.0.1:8000/api/pcdn/status` with admin token header when testing API directly.

Switch back:

```powershell
$env:BUSINESS_MODE="storage_share"
python .\server_main.py
```

Open:

- `http://127.0.0.1:8000/user/upload`
- `http://127.0.0.1:8000/user/dashboard`

## Spec Coverage Self-Review

- Business modes and config: Task 1.
- PCDN schema isolation: Task 2.
- Mock third-party adapter: Task 3.
- PCDN APIs: Task 4.
- Mode-aware admin UI: Task 5.
- Client cache/PCDN labels: Task 6.
- Settlement flow: Task 7.
- README and regression: Task 8.
- Self-hosted PCDN remains out of scope and is represented by the adapter extension point in the spec.
