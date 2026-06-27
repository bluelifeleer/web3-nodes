# Admin Login and Client Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep client nodes running through service outages and make the admin page usable through login and automatic refresh.

**Architecture:** Client registration becomes a retry loop before heartbeat starts. Admin authentication remains token-based for API compatibility, with a lightweight `/admin/login` page storing the token in browser localStorage. The admin dashboard gains a single refresh scheduler that reuses existing fetch functions.

**Tech Stack:** Python, Flask, browser JavaScript embedded in `server_main.py`, unittest.

---

### Task 1: Client Reconnect Loop

**Files:**
- Modify: `client.py`
- Test: `tests/test_mysql_config.py`

- [ ] Write a failing test that `client_run_once` retries registration instead of returning when the first request fails.
- [ ] Run the targeted unittest and confirm failure.
- [ ] Extract one client loop helper with injectable `post`, `sleep`, and `disk` callbacks.
- [ ] Make startup registration retry every `reconnect_interval` seconds until it succeeds.
- [ ] Run the targeted unittest and confirm pass.

### Task 2: Admin Login Page

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] Write a failing test that `/admin/login` renders a login form using `ADMIN_API_TOKEN`.
- [ ] Write a failing test that `/` includes a redirect/prompt to `/admin/login` when no token is saved.
- [ ] Run the targeted unittests and confirm failure.
- [ ] Add `ADMIN_LOGIN_HTML` and `/admin/login`.
- [ ] Update admin dashboard JavaScript so login is the entry flow while keeping `X-Admin-Token` API auth.
- [ ] Run targeted unittests and confirm pass.

### Task 3: Admin Auto Refresh

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] Write a failing test that admin HTML contains a data refresh interval, status marker, and interval scheduler for `refreshAdminData`.
- [ ] Run the targeted unittest and confirm failure.
- [ ] Add admin status text, last-refresh time, and a single `setInterval` scheduler for dashboard data.
- [ ] Run targeted unittest and confirm pass.

### Task 4: Verification

**Files:**
- Validate all touched code.

- [ ] Run `python -B -m unittest discover`.
- [ ] Run `python -B -m py_compile server_main.py db.py auth.py files.py shares.py points.py withdrawals.py client.py tests/test_mysql_config.py`.
- [ ] Run `git diff --check`.
