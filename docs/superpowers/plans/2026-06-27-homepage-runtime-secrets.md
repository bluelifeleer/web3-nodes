# Homepage and Runtime Secrets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a polished commercial homepage that connects user/admin/node flows and auto-generate required runtime secrets on first startup.

**Architecture:** `/` becomes the public product homepage, `/admin` hosts the existing admin dashboard, and `/admin/login` redirects to `/admin` after token login. Startup secret bootstrapping checks `.env` for `ADMIN_API_TOKEN`, `SESSION_SECRET`, and `AES_KEY`, appends missing values, injects them into `os.environ`, and prints copyable startup output.

**Tech Stack:** Python, Flask, embedded HTML/CSS/JS, unittest.

---

### Task 1: Homepage Routing

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] Write failing tests for `/` as a commercial homepage with links to `/user/login`, `/user/upload`, `/user/dashboard`, `/admin/login`, `/admin`, and `/api/health`.
- [ ] Write failing tests for `/admin` rendering the admin dashboard without database initialization.
- [ ] Implement `HOME_HTML`, move admin dashboard route to `/admin`, and update login redirect to `/admin`.
- [ ] Run targeted tests and confirm pass.

### Task 2: Runtime Secret Bootstrap

**Files:**
- Modify: `server_main.py`
- Test: `tests/test_mysql_config.py`

- [ ] Write failing tests for generating missing `ADMIN_API_TOKEN`, `SESSION_SECRET`, and 16-character `AES_KEY` into a temp `.env`.
- [ ] Write failing tests that existing values are not overwritten.
- [ ] Implement `ensure_runtime_secrets` and call it before module-level constants unless `WEB3_NODES_SKIP_DOTENV=1`.
- [ ] Print copyable generated values at startup/import when generation occurs.
- [ ] Run targeted tests and confirm pass.

### Task 3: Docs and Verification

**Files:**
- Modify: `README.md`

- [ ] Shorten README quick-start around homepage-first usage.
- [ ] Run `python -B -m unittest discover`.
- [ ] Run `python -B -m py_compile server_main.py db.py auth.py files.py shares.py points.py withdrawals.py client.py tests/test_mysql_config.py`.
- [ ] Run `git diff --check`.
