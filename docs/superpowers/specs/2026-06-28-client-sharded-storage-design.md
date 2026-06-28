# Client Sharded Storage Design

## Goal

Make real customer node storage the primary storage path. Uploaded files must be encrypted, split into verified shards, delivered to client machines under the user-selected storage directory, and reconstructed safely during download. IPFS and the current server-side simulated node storage remain fallback copies, not the primary success path.

The feature also adds mandatory client storage directory selection, directory locking and hiding, detailed operational logs, and exportable audit records.

## Scope

This design covers:

- Mandatory client storage directory selection and operator-declared available capacity before heartbeats are considered healthy.
- Client-side hidden and locked storage root preparation.
- Encrypted shard generation, shard hashes, and original file hash metadata.
- Server-to-client shard write and read APIs.
- Upload-time distribution to real online client nodes.
- Download-time shard retrieval, hash verification, decryption, merge, and original file hash verification.
- Server simulated storage and IPFS fallback copies.
- Detailed logs and audit export APIs.

This design does not require full peer-to-peer node networking. The server remains the coordinator for node selection, shard transfer, and audit records.

## Recommended Approach

Use server-orchestrated storage with client local storage APIs.

The server receives uploads, encrypts the complete plaintext, splits the encrypted bytes into fixed-size shards, assigns shards to online real nodes, and sends each shard to the selected client node. Each client writes only encrypted shards to its configured storage directory. Downloads reverse the process by asking the client nodes for shards, validating every shard hash, merging encrypted shards by index, decrypting the merged ciphertext, and validating the final plaintext hash.

This approach keeps upload/download behavior centralized and testable while moving the actual primary storage location to the customer machine.

## Client Startup And Directory Requirement

The client must no longer silently accept the bundled default storage directory as a production-ready directory.

Storage directory sources stay in the current precedence order:

1. CLI: `--storage-dir=D:\web3-node-data`
2. Environment: `NODE_STORAGE_DIR`
3. Config: `node_config.json`
4. Local management page update after startup

If no storage directory is explicitly configured, the client should:

- Start the local management page when possible.
- Mark storage as `required`.
- Refuse to register as usable storage.
- Refuse healthy heartbeat storage reporting.
- Show a clear message in the console and management page.

After the operator sets a directory, the client validates it and resumes normal registration and heartbeat reporting.

The operator must also declare the capacity they are willing to contribute, for example:

```powershell
python client.py --storage-dir=D:\web3-node-data --storage-quota-gb=100
```

Supported sources:

- CLI: `--storage-quota-gb=100`
- Environment: `NODE_STORAGE_QUOTA_GB`
- Config: `storage_quota_gb`
- Local management page update

The heartbeat should report both physical free capacity and declared quota:

- `storage_total_gb`: physical filesystem total.
- `storage_used_gb`: actual bytes used inside the node store.
- `storage_free_gb`: physical filesystem free space.
- `storage_quota_gb`: operator-declared usable capacity.
- `storage_available_gb`: remaining usable capacity, calculated as `min(storage_quota_gb - storage_used_gb, storage_free_gb)`.

Nodes with missing quota, zero remaining usable capacity, unhealthy storage, or lock mismatch must not be selected for new shard writes.

## Directory Locking And Hiding

The selected directory is prepared as a node-owned storage root:

```text
<selected-directory>/
  .web3_nodes.lock
  .web3_nodes_store/
    manifest/
    files/
```

The lock file records:

- `user_addr`
- `node_mac`
- `storage_dir`
- `created_at`
- `schema_version`

The client refuses to use a directory when an existing lock belongs to a different `user_addr` or `node_mac`. This is an application-level lock to prevent accidental reuse or cross-node corruption.

The client should hide the store directory:

- Windows: run an internal helper equivalent to `attrib +h +s <store-dir>` when available.
- Other platforms: use the dot-directory name `.web3_nodes_store`.

Failure to hide the directory should not destroy storage, but it must be logged and surfaced as a warning in the directory health payload.

## Storage Format

The server calculates:

- `file_hash = sha256(plain_file_bytes)`
- `encrypted_data = aes_encrypt(plain_file_bytes)`
- `encrypted_hash = sha256(encrypted_data)`
- `shards = file_shard(encrypted_data)`
- `chunk_hash = sha256(shard_bytes)` for each shard

Each shard record includes:

- `file_hash`
- `encrypted_hash`
- `chunk_index`
- `chunk_total`
- `chunk_hash`
- `chunk_size`
- `node_address`
- `storage_status`
- `stored_at`
- `last_verified_at`

The client writes shards as:

```text
.web3_nodes_store/files/<file_hash>/<chunk_index>.part
.web3_nodes_store/manifest/<file_hash>.json
```

The manifest stores the same shard metadata, never plaintext.

## Upload Flow

The user upload flow should:

1. Receive the file.
2. Validate max upload size and duplicate file hash.
3. Encrypt the complete file.
4. Split encrypted data into shards.
5. Select real online client nodes with healthy storage and enough `storage_available_gb`.
6. Send each shard to a client storage API.
7. Require at least one real client shard write for the upload to succeed.
8. Store a complete encrypted fallback in the server simulated node path.
9. Store a complete encrypted backup in IPFS when IPFS is available.
10. Save file and shard metadata.
11. Write audit events for each stage.

When real client storage fails entirely, the upload returns `503` and does not pretend IPFS is the primary storage. IPFS is a fallback only after at least one real client storage write succeeds.

## Client Storage API

The client local HTTP server remains bound to `127.0.0.1` for the management UI. For server-coordinated storage, the implementation needs a storage endpoint reachable from the server deployment. In local development, tests can call the same handler directly. For production, the deployment must provide a reachable node endpoint or a later pull-task mode.

Client endpoints:

- `POST /api/node/storage/shards`: write one encrypted shard.
- `GET /api/node/storage/shards/<file_hash>/<chunk_index>`: read one encrypted shard.
- `GET /api/node/storage/files/<file_hash>/manifest`: return local manifest and shard status.
- `POST /api/node/storage/files/<file_hash>/verify`: verify local shard hashes for one file.

Every mutation must validate node identity and reject writes when the directory is missing, locked by another node, unwritable, or unhealthy.

## Download Flow

Download by file hash or share link should:

1. Load file metadata and shard manifest.
2. Try client node shards first.
3. Verify every returned shard against its `chunk_hash`.
4. Require all shard indexes from `0` to `chunk_total - 1`.
5. Merge encrypted shards in index order.
6. Verify `sha256(encrypted_data) == encrypted_hash` when available.
7. Decrypt the encrypted data.
8. Verify `sha256(plain_data) == file_hash`.
9. Only after verification, return the file and record rewards/download logs.

Fallback order:

1. Real client node shards.
2. Server simulated node encrypted copy.
3. IPFS encrypted backup.

Fallback data must still be decrypted and hash-verified before being returned.

## Audit Logs

Add durable audit records for storage-sensitive operations.

Audit event types:

- `client.storage.required`
- `client.storage.configured`
- `client.storage.locked`
- `client.storage.hide_failed`
- `upload.received`
- `upload.encrypted`
- `upload.sharded`
- `shard.assign`
- `shard.write.success`
- `shard.write.failed`
- `fallback.server.write.success`
- `fallback.server.write.failed`
- `fallback.ipfs.write.success`
- `fallback.ipfs.write.failed`
- `download.shard.read.success`
- `download.shard.read.failed`
- `download.shard.hash_failed`
- `download.merge.success`
- `download.decrypt.failed`
- `download.file_hash_failed`
- `download.fallback.used`
- `download.success`

Each event should include:

- `event_type`
- `file_hash`
- `chunk_index` when relevant
- `node_address` when relevant
- `request_id`
- `status`
- `message`
- `metadata_json`
- `created_at`

Audit logs must not store file contents, encrypted shard bytes, AES keys, auth tokens, or direct secrets.

## Audit Export

Add export endpoints for admins:

- `GET /api/admin/audit/storage?file_hash=...&node_address=...&from=...&to=...`
- `GET /api/admin/audit/storage/export?format=json|csv&file_hash=...&node_address=...&from=...&to=...`

The export should support:

- Filtering by file hash.
- Filtering by node.
- Filtering by time range.
- JSON output for machine review.
- CSV output for audit handoff.

Admin UI should include a storage audit page section:

- Compact table of recent storage audit events.
- Filters for file hash, node address, event type, status, and time range.
- Manual refresh button.
- Event detail view for `message` and `metadata_json`.
- Export buttons for the currently filtered result set.

A full analytics dashboard is not required for the first implementation, but the logs must be visible in the page so operators can inspect upload, shard, fallback, and download verification behavior without exporting first.

## Database Changes

Add a shard metadata table, for example `file_shard_record`:

- `id`
- `file_hash`
- `encrypted_hash`
- `chunk_index`
- `chunk_total`
- `chunk_hash`
- `chunk_size`
- `node_address`
- `storage_status`
- `stored_at`
- `last_verified_at`
- `error_message`

Add a storage audit table, for example `storage_audit_log`:

- `id`
- `event_type`
- `file_hash`
- `chunk_index`
- `node_address`
- `request_id`
- `status`
- `message`
- `metadata_json`
- `created_at`

Existing `file_chain_record.stored_nodes` remains for backward-compatible summaries and should contain only real user storage nodes for user uploads. Server backup and IPFS are represented by their own metadata and audit events.

## Error Handling

- Missing storage directory: client stays manageable but not healthy storage.
- Lock mismatch: client refuses storage writes and reports `storage_status=locked`.
- Shard write failure: server logs the failure and tries another eligible node when available.
- Partial client storage success: upload succeeds only if at least one real client shard write succeeds and fallback copies are attempted.
- Shard hash mismatch during download: reject the shard, log it, try fallback, and do not record rewards for failed node data.
- Decrypt or final hash failure: return JSON error unless fallback succeeds.

## Testing

Tests should cover:

- Client config without explicit storage marks storage as required.
- Client directory preparation writes a lock and uses hidden store paths.
- Lock mismatch prevents storage writes.
- Shard path normalization rejects traversal.
- Client shard write/read returns exact encrypted bytes and manifest metadata.
- Upload creates encrypted shards with per-shard hashes.
- Upload requires at least one real client shard write.
- Upload attempts server simulated storage and IPFS fallback after real node write.
- Download verifies shard hashes before merge.
- Download decrypts and validates final file hash.
- Download falls back to server simulated storage and IPFS when client shards are missing.
- Corrupt shard data does not produce rewards or successful download logs.
- Audit log insertion is called for upload, shard write, fallback, download, and verification failures.
- Admin audit export returns JSON and CSV.
- Admin audit page renders recent logs, filters, detail viewing, refresh, and export controls.

## Rollout Notes

Implement in conservative slices:

1. Client storage requirement, lock, hide, and health payload.
2. Shard metadata and audit schema.
3. Client local shard write/read helpers and tests.
4. Server shard packaging and real-client dispatch abstraction.
5. User upload path migration to real client shards plus fallbacks.
6. Download reconstruction with verification and fallback.
7. Admin audit query and export.
8. Admin audit page display.

Backward compatibility:

- Existing records with only full encrypted server/IPFS copies should still download through current fallback behavior.
- New records should prefer shard metadata when present.
- Existing node capacity and management console behavior should remain available.
