# Client Sharded Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store user uploads as encrypted verified shards on real client node directories, reconstruct downloads from verified shards, and expose audit logs in the admin page with JSON/CSV export.

**Architecture:** Keep the server as coordinator. Add focused helpers in `client.py` for locked hidden storage roots and shard read/write APIs, and focused helpers in `server_main.py` for shard packaging, dispatch, reconstruction, fallback, and audit logging. Extend existing SQL initialization/migration files without replacing current upload/download routes.

**Tech Stack:** Python standard library, Flask, existing unittest suite in `tests/test_mysql_config.py`, existing AES helper, existing local client HTTP server.

---

## File Structure

- Modify `client.py`: explicit storage/quota config, storage lock preparation, hidden store paths, shard write/read helpers, local shard API endpoints, heartbeat quota fields.
- Modify `server_main.py`: shard metadata helpers, audit logging/export, client dispatch, upload migration, download reconstruction and fallback.
- Modify `db.py`: runtime migrations for node quota fields, `file_shard_record`, and `storage_audit_log`.
- Modify `init_mysql.sql`: schema fields/tables.
- Modify `init_postgresql.sql`: schema fields/tables.
- Modify `node_config.example.json`: require explicit operator quota example.
- Modify `README.md`: document mandatory directory/quota, shard storage, audit page/export.
- Modify `tests/test_mysql_config.py`: focused tests for client storage, schema, upload/download shard path, and audit endpoints.

## Task 1: Client Storage Requirement, Quota, Lock, And Hidden Store

**Files:**
- Modify: `client.py`
- Modify: `node_config.example.json`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests**

Add tests named:

```python
def test_client_config_tracks_explicit_storage_and_quota(self):
    # load config from an empty JSON file and assert storage_explicit is False and quota is 0.
    # load config with storage_dir and storage_quota_gb and assert storage_explicit True.

def test_client_prepare_storage_root_writes_lock_and_store_dir(self):
    # prepare a temp dir with user_addr NODE_A and node_mac MAC_A.
    # assert .web3_nodes.lock and .web3_nodes_store exist.

def test_client_prepare_storage_root_rejects_lock_mismatch(self):
    # prepare lock with NODE_A/MAC_A, then call with NODE_B/MAC_B.
    # assert RuntimeError includes locked.
```

- [ ] **Step 2: Verify red**

Run:

```powershell
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_client_config_tracks_explicit_storage_and_quota tests.test_mysql_config.MysqlConfigTest.test_client_prepare_storage_root_writes_lock_and_store_dir tests.test_mysql_config.MysqlConfigTest.test_client_prepare_storage_root_rejects_lock_mismatch
```

Expected: FAIL because helpers and quota fields are missing.

- [ ] **Step 3: Implement minimal client helpers**

Implement `storage_explicit`, `storage_quota_gb`, `prepare_storage_root()`, `storage_store_dir()`, and quota-aware `inspect_storage_dir()`.

- [ ] **Step 4: Verify green**

Run the same three tests. Expected: PASS.

## Task 2: Client Shard Write/Read API

**Files:**
- Modify: `client.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests**

Add tests named:

```python
def test_client_shard_write_read_round_trip(self):
    # write encrypted bytes through helper, read them back, assert manifest has chunk_hash.

def test_client_shard_path_rejects_invalid_hash_and_index(self):
    # invalid file_hash or negative index raises ValueError.

def test_client_management_storage_shard_routes_round_trip(self):
    # start local management server, POST base64 shard, GET it, assert bytes match.
```

- [ ] **Step 2: Verify red**

Run the three tests. Expected: FAIL because shard helpers/routes are missing.

- [ ] **Step 3: Implement minimal shard storage**

Add helpers `write_local_shard()`, `read_local_shard()`, `read_local_manifest()`, and routes:

- `POST /api/node/storage/shards`
- `GET /api/node/storage/shards/<file_hash>/<chunk_index>`
- `GET /api/node/storage/files/<file_hash>/manifest`

- [ ] **Step 4: Verify green**

Run the three tests. Expected: PASS.

## Task 3: Schema And Audit Storage

**Files:**
- Modify: `db.py`
- Modify: `init_mysql.sql`
- Modify: `init_postgresql.sql`
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests**

Add tests named:

```python
def test_shard_and_audit_schema_exist(self):
    # assert file_shard_record, storage_audit_log, storage_quota_gb, storage_available_gb exist in SQL and migrations.

def test_insert_storage_audit_log_writes_expected_fields(self):
    # patch cursor, call insert_storage_audit_log, assert event_type/file_hash/node_address/request_id are in params.
```

- [ ] **Step 2: Verify red**

Run the two tests. Expected: FAIL because schema/audit helper is missing.

- [ ] **Step 3: Implement schema and helper**

Add migration SQL and `insert_storage_audit_log(event_type, file_hash="", chunk_index=None, node_address="", request_id="", status="", message="", metadata=None)`.

- [ ] **Step 4: Verify green**

Run the two tests. Expected: PASS.

## Task 4: Server Shard Packaging And Client Dispatch

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests**

Add tests named:

```python
def test_build_encrypted_shard_manifest_records_hashes(self):
    # patch aes_encrypt to deterministic bytes, assert chunk hashes and encrypted_hash.

def test_persist_file_to_storage_nodes_dispatches_shards_to_clients(self):
    # patch post_client_shard, assert each shard is sent and stored nodes returned.

def test_persist_file_to_storage_nodes_requires_real_client_success(self):
    # all dispatches fail, assert RuntimeError.
```

- [ ] **Step 2: Verify red**

Run the three tests. Expected: FAIL because shard packaging/dispatch is missing.

- [ ] **Step 3: Implement packaging and dispatch**

Add `build_encrypted_shard_manifest()`, `post_client_shard()`, and update `persist_file_to_storage_nodes()` to dispatch shards while still writing server fallback copy.

- [ ] **Step 4: Verify green**

Run the three tests. Expected: PASS.

## Task 5: User Upload Migration

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests**

Add tests named:

```python
def test_user_file_upload_records_shard_metadata_and_audit(self):
    # upload file, patch dispatch/IPFS, assert file_shard_record insert and audit events.

def test_user_file_upload_still_attempts_ipfs_after_real_node_success(self):
    # patch backup_to_ipfs, assert called after shard dispatch.
```

- [ ] **Step 2: Verify red**

Run the two tests. Expected: FAIL because user upload does not persist shard metadata/audit yet.

- [ ] **Step 3: Implement metadata insert**

After real client shard write succeeds, insert `file_shard_record` rows and audit events before returning the current JSON shape.

- [ ] **Step 4: Verify green**

Run the two tests. Expected: PASS.

## Task 6: Download Reconstruction And Fallback

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests**

Add tests named:

```python
def test_download_reconstructs_verified_client_shards_before_decrypt(self):
    # patch shard rows and client reads, assert aes_decrypt receives merged encrypted bytes.

def test_download_rejects_corrupt_client_shard_and_uses_fallback(self):
    # corrupt shard hash, fallback server copy succeeds, assert fallback audit event.

def test_download_final_file_hash_mismatch_returns_json_error(self):
    # aes_decrypt returns wrong plain bytes, assert non-200 JSON and no reward log.
```

- [ ] **Step 2: Verify red**

Run the three tests. Expected: FAIL because download reconstruction helper is missing.

- [ ] **Step 3: Implement reconstruction**

Add `read_verified_encrypted_file()`, `read_encrypted_from_client_shards()`, and `decrypt_and_verify_file()`. Update share and file download routes to use them before reward side effects.

- [ ] **Step 4: Verify green**

Run the three tests. Expected: PASS.

## Task 7: Admin Audit APIs And Page

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] **Step 1: Write failing tests**

Add tests named:

```python
def test_admin_storage_audit_api_filters_and_formats_rows(self):
    # patch cursor rows, call /api/admin/audit/storage, assert filters in params and response fields.

def test_admin_storage_audit_export_supports_json_and_csv(self):
    # call export format json and csv, assert content types and body.

def test_admin_page_renders_storage_audit_section(self):
    # assert ADMIN_HTML contains storage audit table, filters, refresh, details, export controls.
```

- [ ] **Step 2: Verify red**

Run the three tests. Expected: FAIL because admin audit APIs/page are missing.

- [ ] **Step 3: Implement API and page section**

Add admin routes for audit list/export and add an admin HTML section with filters, table, detail display, refresh, and export buttons.

- [ ] **Step 4: Verify green**

Run the three tests. Expected: PASS.

## Task 8: Docs And Final Verification

**Files:**
- Modify: `README.md`
- Test: compile and focused unittest suite.

- [ ] **Step 1: Update docs**

Document mandatory `--storage-dir`, `--storage-quota-gb`, hidden locked store, shard verification, IPFS fallback, and admin audit page/export.

- [ ] **Step 2: Run verification**

Run:

```powershell
python -B -m py_compile server_main.py client.py node_mac.py
python -B -m unittest tests.test_mysql_config
git status --short
```

Expected: compile succeeds, test module passes, and only intentional files are modified.
