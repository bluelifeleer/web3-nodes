# PCDN Business Mode Design

## Goal

Change the product direction from a Web3-style file sharing and distributed storage business into a PCDN-oriented business that can operate in domestic environments, while preserving the current implementation as a switchable legacy business.

The first PCDN release targets third-party PCDN integration. It must also run locally without a real vendor by using a mock PCDN adapter. Self-hosted PCDN remains a future adapter, not part of the first implementation.

The design must avoid a broad rewrite. Existing node registration, heartbeat, local console, capacity reporting, earnings, withdrawals, admin authentication, and the management shell should be reused.

## Business Modes

Add a lightweight business mode layer.

Supported modes:

- `storage_share`: the current upload, encrypted shard storage, IPFS fallback, share link, download, and file-based reward business.
- `pcdn_partner`: the new third-party PCDN business.

Configuration:

```env
BUSINESS_MODE=storage_share
PCDN_PROVIDER=mock
```

`BUSINESS_MODE` defaults to `storage_share` so current behavior remains stable. `PCDN_PROVIDER` defaults to `mock` and is only active when `BUSINESS_MODE=pcdn_partner`.

The business mode must be exposed to templates and APIs through a small service such as `app.services.business`, not by reading environment variables throughout templates and routes.

## Recommended Approach

Use a lightweight adapter pattern.

The server owns common platform behavior:

- User and admin authentication.
- Node identity and heartbeat.
- Node storage and bandwidth capability reporting.
- Earnings and withdrawals.
- Admin shell and audit views.

The selected business adapter owns mode-specific behavior:

- Menu visibility.
- PCDN dashboard metrics.
- PCDN task creation and sync.
- Vendor usage metrics normalization.
- PCDN settlement input records.

This keeps the existing code useful while preventing the new PCDN business from being mixed into file sharing routes and tables.

## Third-Party PCDN Adapter Contract

Create `app/services/pcdn/adapters/`.

The first adapter is `mock`, which returns deterministic local data and does not require network access. Future vendor adapters must implement the same interface.

Suggested interface:

```python
class PcdnAdapter:
    provider_name: str

    def list_resources(self) -> list[dict]:
        ...

    def create_task(self, task: dict) -> dict:
        ...

    def get_task(self, task_id: str) -> dict:
        ...

    def sync_usage(self, since=None, until=None) -> list[dict]:
        ...

    def health(self) -> dict:
        ...
```

Normalized usage records should include:

- `vendor_task_id`
- `node_address`
- `resource_url` or `domain`
- `bandwidth_mbps`
- `traffic_gb`
- `online_minutes`
- `cache_hit_rate`
- `started_at`
- `ended_at`
- `raw_payload_json`

Vendor-specific secrets stay in environment/config and are not sent to browsers.

## PCDN Data Model

Add new tables with `pcdn_` prefixes. Do not reuse file sharing tables for PCDN-specific data.

Minimum tables:

- `pcdn_task`
  - local task id, vendor task id, name, resource URL/domain, status, provider, created by, timestamps.
- `pcdn_node_metric`
  - node address, task id, bandwidth, traffic, online minutes, cache hit rate, metric window, provider, raw payload.
- `pcdn_settlement`
  - node address, task id, metric window, contribution score, amount, status, provider, timestamps.
- `pcdn_provider_sync_log`
  - provider, sync type, status, message, request id, raw summary, timestamps.

Existing `user_node`, `node_power`, `node_reward`, and `withdrawal_request` remain common platform tables. PCDN settlement can write summarized rewards into the existing `node_reward` table with a distinct reward type such as `pcdn_traffic` or `pcdn_bandwidth`.

## Node Behavior

The current client remains useful. In `pcdn_partner` mode:

- Storage directory becomes cache directory.
- Storage quota becomes declared cache capacity.
- Upload bandwidth remains an important capability signal.
- Heartbeats continue reporting online state, cache capacity, cache usage, available capacity, and local management API URL.
- The local console copy changes labels from storage-centric language to PCDN/cache language when business mode is PCDN.

The client does not need to implement real edge proxying in the first release. The mock adapter simulates third-party usage metrics so the management and settlement workflows can be tested.

Future self-hosted PCDN can add a local cache/proxy process behind the same node identity and heartbeat contract.

## API Shape

Add PCDN-specific routes under `/api/pcdn/`.

Admin routes:

- `GET /api/pcdn/status`
- `GET /api/pcdn/tasks`
- `POST /api/pcdn/tasks`
- `POST /api/pcdn/sync`
- `GET /api/pcdn/node_metrics`
- `GET /api/pcdn/settlements`
- `POST /api/pcdn/settlements/run`

User or node-facing routes can stay minimal for the first release:

- `GET /api/pcdn/node/summary`

Existing file APIs stay available in `storage_share` mode. In `pcdn_partner` mode, file sharing pages should be hidden from normal navigation and may return a mode-disabled JSON response for API calls that are not relevant.

## Admin UI

The unified management shell should switch menu groups by business mode.

In `storage_share` mode, keep current menu items:

- Upload file
- My shares
- File evidence
- Storage audit

In `pcdn_partner` mode, show:

- PCDN dashboard
- PCDN resource pool
- PCDN tasks
- Vendor sync logs
- PCDN settlements
- Node management
- Withdrawals
- Audit logs

The first implementation can add a single PCDN admin page or a section inside the existing admin dashboard. It should show:

- Current business mode and provider.
- Provider health.
- Active tasks.
- Node capacity/resource pool.
- Latest usage metrics.
- Settlement summary.
- Sync button for the mock adapter.

## Client UI

The node console should receive the business mode in its status payload.

In `storage_share` mode, keep current labels.

In `pcdn_partner` mode, relabel:

- Storage directory -> Cache directory.
- Storage quota -> Cache capacity.
- Stored files -> Cached resources or local cache records.
- Node storage contribution -> PCDN resource contribution.

No real vendor credentials should be shown in the client console.

## Business Switching Rules

Switching should be controlled by configuration, not database edits.

Rules:

- `BUSINESS_MODE=storage_share` enables current file sharing UI and APIs.
- `BUSINESS_MODE=pcdn_partner` enables PCDN UI and APIs.
- The inactive business is hidden from navigation.
- Existing data remains in place when switching modes.
- Inactive APIs should either stay read-only for admin migration needs or return a clear `business mode disabled` response. The first release should prefer a clear disabled response for user-facing file operations in PCDN mode.

## Settlement Flow

First release settlement flow:

1. Admin clicks vendor sync or scheduled sync runs.
2. Active adapter returns normalized usage metrics.
3. Server stores metrics in `pcdn_node_metric`.
4. Settlement job calculates contribution based on traffic, bandwidth, online minutes, and cache hit rate.
5. Settlement writes `pcdn_settlement` rows.
6. Aggregated reward rows are written into `node_reward`.
7. Existing withdrawal workflow handles payout.

The mock adapter should produce stable sample metrics so tests and demos are repeatable.

## Error Handling And Audit

PCDN adapter calls must be wrapped and logged.

Required behavior:

- Vendor failures do not crash the Flask app.
- Sync failures write `pcdn_provider_sync_log`.
- Admin UI shows provider health and last sync error.
- Raw vendor payloads are stored only in server-side JSON fields.
- Secrets are never written to audit logs or browser payloads.

## Testing Plan

Target `tests/test_mysql_config.py` first, matching the current repo practice.

Coverage should include:

- `ServerConfig` reads `BUSINESS_MODE` and `PCDN_PROVIDER`.
- Invalid business mode falls back safely or reports a clear config error.
- Mock PCDN adapter implements the required contract.
- PCDN schema contains `pcdn_` tables.
- Admin page changes visible menus by mode.
- PCDN mode hides file sharing navigation.
- PCDN APIs return mock task, resource, metric, sync, and settlement data.
- Storage share mode keeps current upload/share tests passing.
- Client status includes business mode and console labels switch in PCDN mode.
- Settlement writes PCDN rewards without breaking existing withdrawals.

Run:

```powershell
python -B -m unittest tests.test_mysql_config
```

## Implementation Order

1. Add business mode config and tests.
2. Add PCDN schema tables.
3. Add PCDN adapter interface and mock adapter.
4. Add PCDN services and routes.
5. Add mode-aware admin/menu rendering.
6. Add PCDN dashboard section or page.
7. Add client status mode and label switching.
8. Add PCDN settlement into the existing reward and withdrawal flow.
9. Update README with switching examples.

## Out Of Scope For First Release

- Real self-hosted edge proxying.
- Real third-party vendor API integration without documentation.
- Replacing the current file sharing business.
- Migrating existing storage/share data into PCDN tables.
- Automatic legal/compliance validation of vendor behavior.

## Open Extension Point

When a real PCDN vendor is selected, add a new adapter under `app/services/pcdn/adapters/` and configure:

```env
BUSINESS_MODE=pcdn_partner
PCDN_PROVIDER=vendor_name
PCDN_VENDOR_BASE_URL=https://example.vendor
PCDN_VENDOR_ACCESS_KEY=...
PCDN_VENDOR_SECRET_KEY=...
```

Only the adapter should understand vendor-specific authentication, request signing, field names, and error formats.
