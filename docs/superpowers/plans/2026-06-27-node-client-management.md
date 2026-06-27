# Node Client Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local customer node management console, capacity reporting, directory health reporting, node withdrawals, and server-side capacity/withdrawal operations.

**Architecture:** Keep server APIs and admin rendering in the existing `server_main.py` pattern, extend schema in `init_mysql.sql`, `init_postgresql.sql`, and `db.py`, and add a lightweight local HTTP console inside `client.py`. The client remains local-first: stop/restart and directory selection are only available on `127.0.0.1`.

**Tech Stack:** Python 3 standard library HTTP server/threading/shutil, Flask server APIs, existing PostgreSQL/MySQL compatibility helpers, `unittest` coverage in `tests/test_mysql_config.py`.

---

## File Structure

- Modify `client.py`: config parsing, directory validation helpers, heartbeat payload enrichment, local management HTTP server, local dashboard HTML.
- Modify `node_config.example.json`: add `manage_port`.
- Modify `server_main.py`: heartbeat storage fields, node identity helpers, node earnings/withdrawal APIs, admin capacity columns, withdrawal table UI.
- Modify `db.py`: schema migrations for node capacity fields and node withdrawal identity fields.
- Modify `init_mysql.sql`: new node capacity fields and compatible withdrawal identity fields.
- Modify `init_postgresql.sql`: same schema fields for PostgreSQL.
- Modify `tests/test_mysql_config.py`: focused tests for config, directory validation, heartbeat compatibility, admin rendering, and node withdrawal APIs.
- Modify `README.md`: startup and usage documentation for the client console.

## Task 1: Schema And Node Capacity Contract

**Files:**
- Modify: `init_mysql.sql`
- Modify: `init_postgresql.sql`
- Modify: `db.py`
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing schema tests**

Add tests near the existing SQL initialization tests:

```python
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
```

Add a heartbeat compatibility test:

```python
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
    self.assertTrue(any("storage_total_gb" in sql for sql, _ in executed))
    self.assertIn("D:/web3-node-data", executed[-1][1])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_node_power_capacity_fields_exist_in_init_sql_and_migrations tests.test_mysql_config.MysqlConfigTest.test_heartbeat_stores_capacity_fields_and_allows_old_payloads
```

Expected: FAIL because capacity fields are not yet present in schema or heartbeat SQL.

- [ ] **Step 3: Implement schema fields**

Add to `node_power` table definitions:

```sql
storage_path varchar(255) DEFAULT '',
storage_status varchar(32) DEFAULT 'unknown',
storage_error varchar(255) DEFAULT '',
storage_total_gb double precision DEFAULT 0,
storage_used_gb double precision DEFAULT 0,
storage_free_gb double precision DEFAULT 0,
```

Use MySQL `float DEFAULT 0` in `init_mysql.sql`.

Add migrations to `db.py`:

```python
"ALTER TABLE node_power ADD COLUMN storage_path varchar(255) DEFAULT ''",
"ALTER TABLE node_power ADD COLUMN storage_status varchar(32) DEFAULT 'unknown'",
"ALTER TABLE node_power ADD COLUMN storage_error varchar(255) DEFAULT ''",
"ALTER TABLE node_power ADD COLUMN storage_total_gb float DEFAULT 0",
"ALTER TABLE node_power ADD COLUMN storage_used_gb float DEFAULT 0",
"ALTER TABLE node_power ADD COLUMN storage_free_gb float DEFAULT 0",
```

For PostgreSQL:

```python
"ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_path varchar(255) DEFAULT ''",
"ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_status varchar(32) DEFAULT 'unknown'",
"ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_error varchar(255) DEFAULT ''",
"ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_total_gb double precision DEFAULT 0",
"ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_used_gb double precision DEFAULT 0",
"ALTER TABLE node_power ADD COLUMN IF NOT EXISTS storage_free_gb double precision DEFAULT 0",
```

- [ ] **Step 4: Implement heartbeat storage**

In `server_main.py`, update `node_heartbeat()` to read optional fields and update them:

```python
storage_path = str(data.get("storage_path") or "")[:255]
storage_status = str(data.get("storage_status") or "unknown")[:32]
storage_error = str(data.get("storage_error") or "")[:255]
storage_total_gb = float(data.get("storage_total_gb") or 0)
storage_used_gb = float(data.get("storage_used_gb") or disk_used or 0)
storage_free_gb = float(data.get("storage_free_gb") or 0)
```

Update SQL to set all new columns while keeping old clients valid.

- [ ] **Step 5: Verify**

Run the two tests from Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add init_mysql.sql init_postgresql.sql db.py server_main.py tests/test_mysql_config.py
git commit -m "Add node capacity heartbeat fields"
```

## Task 2: Server Node Record And Admin Capacity UI

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing admin node tests**

Add tests near `test_node_record_formats_online_status_and_quality`:

```python
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

def test_admin_page_renders_capacity_and_withdrawal_sections(self):
    server_main = load_server_main(ADMIN_API_TOKEN="secret-token")

    self.assertIn("总容量", server_main.ADMIN_HTML)
    self.assertIn("可用容量", server_main.ADMIN_HTML)
    self.assertIn("提现申请", server_main.ADMIN_HTML)
    self.assertIn("getAdminWithdrawals", server_main.ADMIN_HTML)
    self.assertIn("reviewWithdrawal", server_main.ADMIN_HTML)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_node_record_formats_capacity_fields tests.test_mysql_config.MysqlConfigTest.test_admin_page_renders_capacity_and_withdrawal_sections
```

Expected: FAIL because formatter and HTML do not expose those fields.

- [ ] **Step 3: Update node row selection and formatter**

Extend `select_node_rows()` projection after `nl.city`:

```sql
np.storage_path,np.storage_status,np.storage_error,
np.storage_total_gb,np.storage_used_gb,np.storage_free_gb
```

Extend `format_node_record()` to include:

```python
"storage_path": item[9] if len(item) > 9 else "",
"storage_status": item[10] if len(item) > 10 and item[10] else "unknown",
"storage_error": item[11] if len(item) > 11 else "",
"storage_total_gb": item[12] if len(item) > 12 and item[12] is not None else 0,
"storage_used_gb": item[13] if len(item) > 13 and item[13] is not None else item[3] or 0,
"storage_free_gb": item[14] if len(item) > 14 and item[14] is not None else 0,
```

- [ ] **Step 4: Update admin HTML**

Add columns to the node table:

```html
<th>总容量G</th>
<th>已用G</th>
<th>可用G</th>
<th>目录状态</th>
```

Render:

```javascript
<td>${item.storage_total_gb || 0}</td>
<td>${item.storage_used_gb || item.disk_used || 0}</td>
<td>${item.storage_free_gb || 0}</td>
<td>${item.storage_status || "unknown"} ${item.storage_error ? "｜" + item.storage_error : ""}</td>
```

Add a withdrawal section:

```html
<div class="box commercial-card">
  <h3>提现申请</h3>
  <button onclick="getAdminWithdrawals()">刷新提现</button>
  <table>
    <thead><tr><th>ID</th><th>用户/节点</th><th>钱包</th><th>金额</th><th>状态</th><th>备注</th><th>操作</th></tr></thead>
    <tbody id="withdrawalTable"></tbody>
  </table>
</div>
```

Add JS functions:

```javascript
function getAdminWithdrawals(){
    adminFetch("/api/admin/withdrawals")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        (data.data || []).forEach(item=>{
            const actions = item.status === "pending"
                ? `<button onclick="reviewWithdrawal(${item.id},'approved')">通过</button><button onclick="reviewWithdrawal(${item.id},'rejected')">驳回</button>`
                : item.status === "approved"
                    ? `<button onclick="reviewWithdrawal(${item.id},'paid')">标记已提现</button><button onclick="reviewWithdrawal(${item.id},'rejected')">驳回</button>`
                    : "已完成";
            html += `<tr><td>${item.id}</td><td>${item.user_id || item.node_address || ""}</td><td>${item.wallet_address}</td><td>${item.amount}</td><td>${item.status}</td><td>${item.admin_note || ""}</td><td>${actions}</td></tr>`;
        });
        document.getElementById("withdrawalTable").innerHTML = html || '<tr><td colspan="7">暂无提现申请</td></tr>';
    });
}
function reviewWithdrawal(id,status){
    const admin_note = window.prompt("审核备注，可留空", "") || "";
    adminFetch(`/api/admin/withdrawals/${id}/review`, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({status,admin_note})
    }).then(res=>res.json()).then(data=>{
        alert(data.msg || "操作完成");
        getAdminWithdrawals();
    });
}
```

Call `getAdminWithdrawals();` from `refreshAdminData()`.

- [ ] **Step 5: Verify**

Run tests from Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add server_main.py tests/test_mysql_config.py
git commit -m "Show node capacity and withdrawals in admin"
```

## Task 3: Client Directory Validation And Startup Options

**Files:**
- Modify: `client.py`
- Modify: `node_config.example.json`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing client tests**

Add tests near existing client config tests:

```python
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

def test_client_storage_probe_reports_unavailable_directory(self):
    old_requests = sys.modules.get("requests")
    old_webview = sys.modules.get("webview")
    try:
        sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
        sys.modules["webview"] = None
        sys.modules.pop("client", None)
        client_module = importlib.import_module("client")
        result = client_module.inspect_storage_dir("")
        self.assertEqual(result["storage_status"], "unavailable")
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_client_config_supports_manage_port tests.test_mysql_config.MysqlConfigTest.test_client_storage_probe_reports_unavailable_directory
```

Expected: FAIL because `manage_port` and `inspect_storage_dir` do not exist.

- [ ] **Step 3: Implement config and probe**

In `client.py`, add:

```python
import shutil
from dataclasses import dataclass
```

Add defaults:

```python
MANAGE_PORT = 8787
```

Add config/env/CLI support:

```python
"manage_port": MANAGE_PORT,
config["manage_port"] = int(os.getenv("NODE_MANAGE_PORT", config["manage_port"]))

def get_manage_port_arg():
    for arg in sys.argv[1:]:
        if arg.startswith("manage_port=") or arg.startswith("--manage-port=") or arg.startswith("--manage_port="):
            return int(arg.split("=", 1)[1].strip())
    return 0
```

Add storage probe:

```python
def inspect_storage_dir(storage_dir):
    if not storage_dir:
        return {"storage_path":"","storage_status":"unavailable","storage_error":"未指定存储目录","storage_total_gb":0,"storage_used_gb":0,"storage_free_gb":0}
    try:
        path = ensure_storage_dir(storage_dir)
        if path is None or not path.is_dir():
            raise RuntimeError("存储路径不是目录")
        probe = path / ".filezall_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        usage = shutil.disk_usage(path)
        dir_used = get_directory_size_bytes(path)
        return {"storage_path":str(path),"storage_status":"ok","storage_error":"","storage_total_gb":round(usage.total/(1024**3),2),"storage_used_gb":round(dir_used/(1024**3),2),"storage_free_gb":round(usage.free/(1024**3),2)}
    except Exception as exc:
        return {"storage_path":str(storage_dir),"storage_status":"unavailable","storage_error":str(exc),"storage_total_gb":0,"storage_used_gb":0,"storage_free_gb":0}
```

- [ ] **Step 4: Enrich heartbeat payload**

In `client_run()`, set `MANAGE_PORT` and include `inspect_storage_dir(NODE_STORAGE_DIR)` in heartbeat JSON:

```python
storage_info = inspect_storage_dir(NODE_STORAGE_DIR)
payload = {"user_addr": user_addr, "node_mac": device_mac, "disk_used": storage_info["storage_used_gb"], "upload_bw": upload_bw, **storage_info}
```

- [ ] **Step 5: Verify**

Run tests from Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add client.py node_config.example.json tests/test_mysql_config.py
git commit -m "Add client storage probe and manage port"
```

## Task 4: Local Client Management Console

**Files:**
- Modify: `client.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing console tests**

Add tests:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_client_console_html_contains_node_operations tests.test_mysql_config.MysqlConfigTest.test_client_console_status_payload_includes_capacity
```

Expected: FAIL because the console HTML and status helpers do not exist.

- [ ] **Step 3: Implement console helpers**

In `client.py`, add:

```python
CLIENT_MANAGE_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>节点控制台</title></head>
<body>
  <main>
    <h1>节点控制台</h1>
    <section id="overview">运行状态 / 服务连接 / 最后心跳</section>
    <section id="capacity">总容量 / 已使用 / 未使用 / 目录状态</section>
    <section id="storage">添加目录 / 重新检测</section>
    <section id="earnings">收益 / 提交提现 / 提现记录</section>
    <section id="controls">停止节点 / 重启节点</section>
  </main>
  <script>
    const api = (path, options) => fetch(path, options).then(res => res.json());
    async function refreshAll(){
      await Promise.all([api("/api/status"), api("/api/earnings"), api("/api/withdrawals")]);
    }
    async function stopNode(){ if(confirm("确认停止节点？")) await api("/api/control/stop", {method:"POST"}); }
    async function restartNode(){ if(confirm("确认重启节点？")) await api("/api/control/restart", {method:"POST"}); }
  </script>
</body>
</html>
"""

def create_client_state(server_url, user_addr, node_mac, storage_dir, manage_port):
    return {"server_url":server_url,"user_addr":user_addr,"node_mac":node_mac,"storage_dir":storage_dir,"manage_port":manage_port,"running":True,"last_heartbeat":"","last_error":"","storage":inspect_storage_dir(storage_dir)}

def client_status_payload(state):
    return {"server_url":state["server_url"],"user_addr":state["user_addr"],"node_mac":state["node_mac"],"running":state["running"],"last_heartbeat":state["last_heartbeat"],"last_error":state["last_error"],"storage":state["storage"]}
```

Add an HTTP handler using `http.server.ThreadingHTTPServer` and `BaseHTTPRequestHandler`:

```python
def start_manage_server(state):
    server = ThreadingHTTPServer(("127.0.0.1", int(state["manage_port"])), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
```

Implement endpoints listed in the spec with JSON responses.

- [ ] **Step 4: Wire into `client_run()`**

After user address is computed:

```python
state = create_client_state(SERVER_URL, user_addr, device_mac, NODE_STORAGE_DIR, MANAGE_PORT)
start_manage_server(state)
safe_print(f"🌐 节点管理页：http://127.0.0.1:{MANAGE_PORT}")
```

Update state after heartbeat success/failure.

- [ ] **Step 5: Verify**

Run tests from Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add client.py tests/test_mysql_config.py
git commit -m "Add local node management console"
```

## Task 5: Node Earnings And Withdrawal APIs

**Files:**
- Modify: `db.py`
- Modify: `init_mysql.sql`
- Modify: `init_postgresql.sql`
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing node API tests**

Add tests:

```python
def test_node_identity_requires_registered_mac_pair(self):
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
    response = server_main.app.test_client().get("/api/node/me?user_addr=NODE_A&node_mac=BAD")
    self.assertEqual(response.status_code, 401)

def test_node_withdrawal_create_inserts_node_request(self):
    server_main = load_server_main()
    executed = []

    class FakeCursor:
        def __init__(self):
            self.last_sql = ""
        def execute(self, sql, params=None):
            self.last_sql = sql
            executed.append((sql, params))
        def fetchone(self):
            if "from user_node" in self.last_sql:
                return ("NODE_A",)
            if "sum(reward_amount)" in self.last_sql:
                return (10,)
            if "from withdrawal_request" in self.last_sql:
                return (0,)
            return None

    class FakeConnection:
        def get_autocommit(self): return True
        def autocommit(self, value): pass
        def commit(self): pass
        def rollback(self): pass

    server_main.cursor = FakeCursor()
    server_main.db = FakeConnection()
    server_main.init_db = lambda: True
    response = server_main.app.test_client().post("/api/node/withdrawals", json={
        "user_addr":"NODE_A",
        "node_mac":"MAC_A",
        "wallet_address":"0xnode",
        "amount":"1.5",
    })
    self.assertEqual(response.status_code, 200)
    self.assertTrue(any("insert into withdrawal_request" in sql.lower() for sql, _ in executed))
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_node_identity_requires_registered_mac_pair tests.test_mysql_config.MysqlConfigTest.test_node_withdrawal_create_inserts_node_request
```

Expected: FAIL because node APIs do not exist.

- [ ] **Step 3: Add withdrawal identity fields**

Because existing `withdrawal_request.user_id` requires an app user, add nullable node fields while keeping app-user withdrawals working:

- `user_id` should become nullable or node withdrawals should use `user_id=0`.
- Add `node_address varchar(128) DEFAULT ''`.
- Add `withdrawal_channel varchar(32) DEFAULT 'wallet'`.
- Add `withdrawal_account varchar(128) DEFAULT ''`.

Prefer `user_id DEFAULT NULL` in PostgreSQL/MySQL and update code/tests to tolerate `None`.

- [ ] **Step 4: Implement node identity and earnings helpers**

In `server_main.py`:

```python
def require_node_identity():
    data = get_json_body() if request.method == "POST" else request.args
    user_addr = str(data.get("user_addr") or "").strip()
    node_mac = str(data.get("node_mac") or "").strip()
    current_cursor().execute("select user_address from user_node where user_address=%s", (user_addr,))
    if not current_cursor().fetchone():
        return None, None, (jsonify({"code":401,"msg":"节点身份无效"}), 401)
    current_cursor().execute("select user_address from node_power where user_address=%s and node_mac=%s", (user_addr,node_mac))
    if not current_cursor().fetchone():
        return None, None, (jsonify({"code":401,"msg":"节点身份无效"}), 401)
    return user_addr, node_mac, None
```

Add `calculate_node_earnings(node_address)` using `node_reward` plus node withdrawals.

- [ ] **Step 5: Add node APIs**

Add routes:

```python
@app.route("/api/node/me")
def node_me():
    user_addr, node_mac, error = require_node_identity()
    if error:
        return error
    current_cursor().execute(
        """
        select un.user_address,un.invite_code,np.disk_used,np.online_duration,np.upload_bandwidth,
               np.storage_path,np.storage_status,np.storage_error,np.storage_total_gb,np.storage_used_gb,np.storage_free_gb
        from user_node un
        left join node_power np on un.user_address=np.user_address
        where un.user_address=%s
        """,
        (user_addr,),
    )
    row = current_cursor().fetchone()
    return jsonify({"code":200,"data":{"user_addr":user_addr,"node_mac":node_mac,"row":row}})

@app.route("/api/node/earnings")
def node_earnings():
    user_addr, node_mac, error = require_node_identity()
    if error:
        return error
    return jsonify({"code":200,"data":calculate_node_earnings(user_addr)})

@app.route("/api/node/withdrawals")
def node_withdrawals():
    user_addr, node_mac, error = require_node_identity()
    if error:
        return error
    current_cursor().execute(
        """
        select id,user_id,wallet_address,amount,status,admin_note,created_at,reviewed_at,node_address,withdrawal_channel,withdrawal_account
        from withdrawal_request
        where node_address=%s
        order by created_at desc,id desc
        """,
        (user_addr,),
    )
    return jsonify({"code":200,"data":[format_withdrawal_row(row) for row in current_cursor().fetchall()]})

@app.route("/api/node/withdrawals", methods=["POST"])
def node_withdrawal_create():
    user_addr, node_mac, error = require_node_identity()
    if error:
        return error
    data = get_json_body()
    amount, message = withdrawals.parse_withdrawal_amount(data.get("amount"))
    if amount is None:
        return jsonify({"code":400,"msg":message}), 400
    wallet_address = str(data.get("wallet_address") or "").strip()[:128]
    if not wallet_address:
        return jsonify({"code":400,"msg":"请先设置提现钱包"}), 400
    current_cursor().execute(
        """
        insert into withdrawal_request(user_id,wallet_address,amount,status,node_address,withdrawal_channel,withdrawal_account)
        values(%s,%s,%s,%s,%s,%s,%s)
        """,
        (None,wallet_address,withdrawals.format_withdrawal_amount(amount),"pending",user_addr,str(data.get("withdrawal_channel") or "wallet")[:32],str(data.get("withdrawal_account") or wallet_address)[:128]),
    )
    commit_database()
    return jsonify({"code":200,"msg":"提现申请已提交"})
```

Use existing `withdrawals.parse_withdrawal_amount()` and status transition logic.

- [ ] **Step 6: Verify**

Run tests from Step 2 plus existing withdrawal tests:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_node_identity_requires_registered_mac_pair tests.test_mysql_config.MysqlConfigTest.test_node_withdrawal_create_inserts_node_request tests.test_mysql_config.MysqlConfigTest.test_admin_withdrawal_review_allows_valid_transitions
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add db.py init_mysql.sql init_postgresql.sql server_main.py tests/test_mysql_config.py
git commit -m "Add node withdrawal APIs"
```

## Task 6: Client Console Earnings, Withdrawals, Controls, Docs

**Files:**
- Modify: `client.py`
- Modify: `README.md`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing integration-marker tests**

Add tests:

```python
def test_client_console_calls_node_earnings_and_withdrawal_apis(self):
    old_requests = sys.modules.get("requests")
    old_webview = sys.modules.get("webview")
    try:
        sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None)
        sys.modules["webview"] = None
        sys.modules.pop("client", None)
        client_module = importlib.import_module("client")
        html = client_module.CLIENT_MANAGE_HTML
        self.assertIn("/api/earnings", html)
        self.assertIn("/api/withdrawals", html)
        self.assertIn("/api/control/stop", html)
        self.assertIn("/api/control/restart", html)
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
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_client_console_calls_node_earnings_and_withdrawal_apis
```

Expected: FAIL until the console HTML wires those endpoints.

- [ ] **Step 3: Implement proxy endpoints**

In local console handler:

- `/api/earnings` calls server `/api/node/earnings` with query parameters `user_addr` and `node_mac` from local state.
- `/api/withdrawals` GET calls server `/api/node/withdrawals` with query parameters `user_addr` and `node_mac` from local state.
- `/api/withdrawals` POST sends `user_addr`, `node_mac`, `amount`, `wallet_address`, `withdrawal_channel`, `withdrawal_account`.
- `/api/storage` updates state storage dir and rechecks it.
- `/api/control/stop` sets `state["running"] = False`, returns JSON, then exits process after a short delay.
- `/api/control/restart` returns `"开发模式暂不支持自动重启"` unless `sys.argv[0]` is a real packaged executable; do not attempt risky process replacement in first version.

- [ ] **Step 4: Update README**

Document:

```powershell
python client.py --storage-dir=D:\web3-node-data --manage-port=8787
```

Add client console URL:

```text
http://127.0.0.1:8787
```

Explain directory health, capacity reporting, earnings, withdrawals, stop/restart limits.

- [ ] **Step 5: Verify**

Run:

```powershell
python -B -m py_compile server_main.py client.py node_mac.py
python -B -m unittest discover
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add client.py README.md tests/test_mysql_config.py
git commit -m "Complete local node console workflows"
```

## Final Verification

- [ ] Run complete verification:

```powershell
python -B -m py_compile server_main.py client.py node_mac.py
python -B -m unittest discover
git status --short
```

- [ ] Expected:

```text
Ran 130+ tests in under 60 seconds
OK
```

`git status --short` should be empty after the final commit.
