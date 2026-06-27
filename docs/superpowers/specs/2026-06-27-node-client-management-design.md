# Node Client Management Design

## Goal

Build an A-style local node management console: the client node starts its own local web page for operators, reports storage capacity and directory health to the server, and lets node operators view earnings and submit withdrawal requests. The server remains the operating center for capacity visibility and withdrawal review.

## Scope

This design covers:

- Client startup options for storage directories and local management port.
- Local storage directory validation and capacity measurement.
- Heartbeat reporting of total, used, free capacity, directory path, and directory health.
- A local client management page served by `client.py`.
- Server-side node capacity storage and admin display.
- Node withdrawal settings, withdrawal submission, review status, and paid marking.

This design does not introduce remote server-side stop/restart control of customer nodes. Stop and restart actions stay local to the client console.

## Recommended Approach

Use a lightweight local HTTP management server embedded in `client.py`. It should run alongside the existing heartbeat loop and serve `http://127.0.0.1:<manage_port>`, defaulting to `8787`.

This avoids a new frontend build system, keeps control actions local to the customer machine, and preserves the current packaging path for `client.py` and `node_mac.py`.

## Client Startup

The Windows client should support these options:

```powershell
python client.py --storage-dir=D:\web3-node-data --manage-port=8787
```

It should also support the existing config/env pattern:

```json
{
  "server_url": "http://127.0.0.1:8000",
  "parent_invite": "",
  "heartbeat_interval": 60,
  "reconnect_interval": 10,
  "storage_dir": "D:/web3-node-data",
  "manage_port": 8787
}
```

Environment variables:

- `NODE_STORAGE_DIR`
- `NODE_MANAGE_PORT`

The macOS client should support the same config keys where practical, but the first implementation can focus on `client.py` because the requested management page is most valuable for the packaged customer node.

## Directory Validation

The client should validate the selected storage directory at startup and on demand from the management page.

Validation should report:

- `storage_path`: selected directory.
- `storage_status`: `ok` or `unavailable`.
- `storage_error`: empty when healthy, otherwise a short readable reason.
- `storage_total_gb`: total capacity of the drive or filesystem.
- `storage_used_gb`: used space for the selected directory or drive, depending on what is meaningful for the display.
- `storage_free_gb`: available free space on the drive or filesystem.

Directory health checks:

- Create the directory if it does not exist.
- Confirm it is a directory.
- Write and delete a small probe file.
- Read filesystem capacity with `shutil.disk_usage(path)`.
- Continue running when unavailable, but report the error in heartbeats.

## Heartbeat Contract

The existing `/heartbeat` endpoint should accept the old payload and the new optional fields:

```json
{
  "user_addr": "NODE_abc123",
  "node_mac": "123456",
  "disk_used": 12.5,
  "upload_bw": 1.7,
  "storage_path": "D:/web3-node-data",
  "storage_status": "ok",
  "storage_error": "",
  "storage_total_gb": 512.0,
  "storage_used_gb": 128.0,
  "storage_free_gb": 384.0
}
```

The server should keep backward compatibility: old clients that only send `disk_used` and `upload_bw` must continue to work.

## Database Changes

Extend `node_power` with nullable columns:

- `storage_path`
- `storage_status`
- `storage_error`
- `storage_total_gb`
- `storage_used_gb`
- `storage_free_gb`

The existing PostgreSQL/MySQL initialization scripts should include these columns. Runtime table initialization should also tolerate existing databases by adding missing columns when possible.

No new withdrawal table is needed for the first version because `withdrawal_request` already exists and supports:

- `pending`
- `approved`
- `rejected`
- `paid`

## Client Local Management API

The local client web server should expose:

- `GET /`: local dashboard HTML.
- `GET /api/status`: node id, server URL, heartbeat status, directory status, capacity, local run state.
- `POST /api/storage`: update `storage_dir`, validate it, and use it for future heartbeats.
- `POST /api/refresh`: force directory recheck and server status refresh.
- `GET /api/earnings`: proxy node earnings summary from the server.
- `GET /api/withdrawals`: proxy node withdrawal records from the server.
- `POST /api/withdrawals`: submit withdrawal request to the server with configured withdrawal info.
- `POST /api/control/stop`: stop the heartbeat loop and shut down the local client process after confirmation.
- `POST /api/control/restart`: restart the client process when possible, or return a clear unsupported message in development mode.

Local control endpoints should bind only to `127.0.0.1`.

## Server Node APIs

Add node-oriented APIs that authenticate by node identity:

- `GET /api/node/me?user_addr=...&node_mac=...`
- `GET /api/node/earnings?user_addr=...&node_mac=...`
- `GET /api/node/withdrawals?user_addr=...&node_mac=...`
- `POST /api/node/withdrawals`
- `POST /api/node/withdrawal_settings`

For the first implementation, node identity validation should match the registered `user_address` and `node_mac` pair in `user_node`. This is better than an unauthenticated user address alone and fits the current client registration model.

Withdrawal submission from the node console should use the node address as the earning owner. A future account-unification migration can move this API to token-based user sessions when node accounts and `app_user` accounts share one identity model.

## Server Admin UI

The admin dashboard should add:

- Node capacity columns: total, used, free, directory status.
- A compact warning display for unavailable directories.
- A withdrawal table inside `/admin`, loaded by the existing auto-refresh loop.
- Buttons for valid review transitions:
  - pending: approve, reject
  - approved: mark paid, reject
  - rejected/paid: read-only

The existing `/api/admin/withdrawals` and `/api/admin/withdrawals/<id>/review` endpoints should remain the source of truth.

## Client UI

The client console should be a modern operational dashboard, not a marketing page.

Primary areas:

- Overview: node id, server connectivity, last heartbeat, online state.
- Capacity: total, used, free, selected directory, directory health.
- Earnings: total earnings, withdrawn, pending, available.
- Withdrawals: amount input, withdrawal info, submit, status table.
- Storage directories: current directory, add/switch, recheck.
- Runtime controls: stop, restart, warning confirmation.

The page should use compact cards, tables, status chips, and clear action buttons.

## Error Handling

- If the storage directory is unavailable, the client must continue running and report `storage_status=unavailable`.
- If the server is unreachable, the client management page should show disconnected state and keep retrying.
- If withdrawal submission fails, the local page should show the server message without losing form data.
- Stop/restart actions must ask for confirmation in the UI.

## Testing

Tests should cover:

- Client config parsing for `manage_port`.
- Directory validation success and failure.
- Heartbeat payload includes capacity and directory status.
- Server heartbeat stores optional capacity fields and remains compatible with old payloads.
- Admin node list returns capacity fields.
- Admin HTML loads withdrawals in auto-refresh and renders review actions.
- Withdrawal status transitions remain enforced.

## Rollout Notes

The first implementation should be conservative:

1. Add capacity fields and heartbeat compatibility.
2. Add local client management server with read-only overview.
3. Add storage directory update and recheck.
4. Add node earnings/withdrawals APIs.
5. Add withdrawal submit and admin review UI.
6. Add stop/restart controls last, with local-only binding and confirmation.
