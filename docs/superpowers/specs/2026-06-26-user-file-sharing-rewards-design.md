# User File Sharing and Rewards Design

Date: 2026-06-26

## Goal

Build the first product layer on top of the existing Web3 node service so normal users can register, upload files, generate share links, download shared files, earn points, and submit withdrawal requests.

This phase combines:

- A: user-facing file upload, share, and download flows.
- B: storage and download contribution accounting for users and nodes.

The implementation keeps Flask and the current database stack, but splits the growing single-file service into focused modules.

## Current Context

The project already has:

- Flask service in `server_main.py`.
- PostgreSQL-first database support with MySQL compatibility.
- Admin token protection.
- Node registration, heartbeat, location, ranking, and reward records.
- IPFS upload/download helpers.
- Public/private file upload with access tokens.
- Admin file list, soft delete, health, and IPFS status views.

The missing layer is a complete user-facing product: login, user-owned files, share links, download pages, points, and withdrawal requests.

## Chosen Approach

Use a modular Flask monolith.

Keep Flask and simple HTML pages for this phase, but move responsibilities out of `server_main.py` into modules:

- `db.py`: database connection, dialect helpers, initialization.
- `auth.py`: account registration/login, password hashing, session tokens, wallet nonce, wallet binding, wallet login.
- `files.py`: user uploads, file ownership, file list/detail, IPFS storage, download orchestration.
- `shares.py`: share links, extract codes, expiry, download limits.
- `points.py`: point ledger, file download rewards, node contribution rewards.
- `withdrawals.py`: withdrawal requests and status updates.
- `admin.py`: admin APIs and admin page data.
- `server_main.py`: app creation, route registration, startup only.

This gives a product-level feature set while keeping the codebase understandable as more capabilities are added.

## Identity Model

Users can authenticate in three ways:

- Register and log in with username/password.
- Bind a wallet address after signing a nonce.
- Log in directly with a bound wallet by signing a nonce.

The account is the primary owner of files and points. The wallet address is linked to the account for Web3 identity, rewards display, and withdrawal targeting.

Password storage must use a one-way hash. Wallet binding and wallet login must use nonce-based signature verification. Nonces expire and cannot be reused.

Wallet signatures should use Ethereum-compatible `personal_sign` style messages in phase 1. The message should include the nonce, purpose, and short expiry text so the user can understand what they are signing. Session tokens can be server-signed tokens without adding a session table in this phase.

## Data Model

Existing `file_chain_record` should be enhanced rather than replaced.

### New Tables

`app_user`

- `id`
- `username` unique
- `password_hash`
- `wallet_address` unique nullable
- `status`
- `created_at`
- `last_login_at`

`wallet_nonce`

- `wallet_address`
- `nonce`
- `expires_at`
- `used_at`

`file_share`

- `id`
- `share_code`
- `file_hash`
- `owner_user_id`
- `visibility`
- `extract_code_hash`
- `expires_at`
- `max_downloads`
- `download_count`
- `status`
- `created_at`

`file_download_log`

- `id`
- `share_code`
- `file_hash`
- `downloader_ip`
- `downloader_user_id`
- `node_address`
- `file_size`
- `created_at`

`point_ledger`

- `id`
- `user_id`
- `wallet_address`
- `point_type`
- `amount`
- `source_type`
- `source_id`
- `remark`
- `created_at`

`withdrawal_request`

- `id`
- `user_id`
- `wallet_address`
- `amount`
- `status`
- `admin_note`
- `created_at`
- `reviewed_at`

### Enhanced Existing Table

`file_chain_record`

- Add `owner_user_id`.
- Add `owner_wallet_address`.
- Add `download_count`.
- Add `last_download_at`.

All schema changes must be added to both PostgreSQL and MySQL initialization paths.

## API Design

### Authentication

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/wallet/nonce`
- `POST /api/wallet/bind`
- `POST /api/wallet/login`

### User Files

- `POST /api/user/files`
- `GET /api/user/files`
- `GET /api/user/files/<file_hash>`
- `DELETE /api/user/files/<file_hash>`

### Sharing and Download

- `POST /api/user/files/<file_hash>/shares`
- `GET /api/user/shares`
- `PATCH /api/user/shares/<share_code>`
- `DELETE /api/user/shares/<share_code>`
- `GET /api/share/<share_code>`
- `POST /api/share/<share_code>/verify`
- `GET /api/share/<share_code>/download`

Share validation rules:

- Missing share returns 404.
- Expired share returns 410.
- Exhausted download limit returns 429.
- Wrong extract code returns 403.
- Successful download increments counters and writes logs.

### Points and Withdrawals

- `GET /api/user/points`
- `GET /api/user/earnings`
- `POST /api/user/withdrawals`
- `GET /api/user/withdrawals`

### Admin

Existing admin APIs remain protected by `ADMIN_API_TOKEN`.

Add:

- `GET /api/admin/users`
- `GET /api/admin/shares`
- `GET /api/admin/downloads`
- `GET /api/admin/points`
- `GET /api/admin/withdrawals`
- `POST /api/admin/withdrawals/<id>/review`

## Pages

### User Pages

`/user/login`

- Register.
- Username/password login.
- Wallet signature login.

`/user/dashboard`

- My files.
- Share link management.
- Points balance.
- Earnings summary.
- Withdrawal request history.

`/user/upload`

- Select file.
- Choose public/private.
- Set extract code.
- Set expiry time.
- Set max download count.
- Upload and generate share link.

`/s/<share_code>`

- Show file name, size, and uploader identity.
- Ask for extract code when required.
- Show expired or exhausted state.
- Download file after validation.

### Admin Page

Keep the current admin page and add panels for:

- Users.
- Shares.
- Download logs.
- Point ledger.
- Withdrawal review.

## Reward Rules

The first phase uses simple configurable point rules:

- Valid share download gives the file owner/share creator 1 point.
- Node download contribution gives storage nodes 0.1 point per MB.
- Storage contribution gives nodes 1 point per GB per day.
- Display withdrawal conversion as 100 points = 1 earning unit.

Withdrawals are recorded as requests and reviewed by admin. This phase does not perform real chain transfers.

## Permissions

- User APIs require a user session token.
- Admin APIs require `ADMIN_API_TOKEN`.
- Share pages can be opened publicly.
- Download requires share validation before streaming file content.
- A user can only list, edit, delete, and create shares for their own files.
- Admin can view all records.

## Error Handling

- Unauthenticated user API: 401.
- Invalid wallet nonce or expired nonce: 400.
- Share not found: 404.
- Share expired: 410.
- Download limit exhausted: 429.
- Extract code mismatch: 403.
- IPFS unavailable during upload/download: readable JSON error, no success log, no point ledger write.

## Testing Plan

Add tests for:

- User registration and login.
- Password hash verification.
- Wallet nonce creation, expiry, one-time use, binding, and login.
- User file ownership isolation.
- Share creation with extract code, expiry, and max downloads.
- Share validation failure states.
- Download success increments share/file counters.
- Download success writes download log.
- Download success writes point ledger entries.
- Withdrawal request creation and admin review.
- Admin token still protects admin APIs.
- PostgreSQL default SQL and MySQL compatibility SQL.

## Acceptance Criteria

- A normal user can register and log in.
- A normal user can bind a wallet with signature verification.
- A bound wallet can be used for wallet signature login.
- A normal user can upload a file.
- Uploaded files are owned by the logged-in user.
- A user can generate a share link with extract code, expiry time, and download limit.
- A visitor can open a share page and download after validation.
- Extract code, expiry, and download limits work.
- Successful downloads create logs and points.
- User dashboard shows files, shares, points, earnings, and withdrawal requests.
- Admin page shows users, shares, downloads, points, and withdrawal requests.
- Existing node registration, heartbeat, admin reward pages, and file admin pages do not regress.

## Out of Scope for Phase 1

- Real chain transfer for withdrawals.
- Team workspaces and member permission groups.
- Paid storage billing.
- Advanced file preview/transcoding.
- Full front-end framework migration.
- Distributed erasure-code repair redesign.
