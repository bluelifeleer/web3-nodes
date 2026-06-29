# 2026-06-29 管理台与客户端工程归档

## 背景

本轮工作围绕两个目标推进：

- 将分散页面整理为更统一的管理台体验，并把模板、样式、脚本拆分，降低 `server_main.py` 内联页面负担。
- 强化客户端节点控制台的数据刷新体验，并把客户端、服务端、数据库 schema、旧静态 HTML 按功能归档到框架目录。

## 交付范围

### 页面与静态资源拆分

服务端页面改为模板 + 静态资源组织：

- `app/templates/management_console.html`
- `app/templates/admin_dashboard.html`
- `app/templates/admin_login.html`
- `app/templates/user_login.html`
- `app/templates/user_upload.html`
- `app/templates/user_dashboard.html`
- `app/templates/public_share.html`
- `app/static/css/console.css`
- `app/static/js/console.js`
- `app/static/css/admin-dashboard.css`
- `app/static/js/admin-dashboard.js`
- `app/static/css/admin-login.css`
- `app/static/js/admin-login.js`
- `app/static/css/user-login.css`
- `app/static/js/user-login.js`
- `app/static/css/user-upload.css`
- `app/static/js/user-upload.js`
- `app/static/css/user-dashboard.css`
- `app/static/js/user-dashboard.js`
- `app/static/css/public-share.css`
- `app/static/js/public-share.js`

保留少量模板内联配置脚本：

- `admin_dashboard.html` 注入高德地图 key / security jscode。
- `public_share.html` 注入分享码 `shareCode`。

这些配置仍留在模板层，避免把 Jinja 变量放入静态 JS 文件。

### 客户端控制台动态刷新

`client/console.py` 中的节点控制台新增：

- `CLIENT_CONSOLE_REFRESH_INTERVAL_MS = 5000`
- `autoRefreshState` 页面状态展示
- `setInterval(refreshAll, CLIENT_CONSOLE_REFRESH_INTERVAL_MS)` 自动刷新状态、收益、提现记录
- `visibilitychange` 监听：页面隐藏时暂停轮询，回到前台后立即刷新并恢复轮询

### Python 模块拆分

新增模块：

- `client/main.py`
  - 负责客户端主入口、心跳循环、本地 HTTP 路由、存储分片读写、代理服务端节点 API。

- `client/config.py`
  - 负责客户端配置读取。
  - 负责启动参数解析：邀请码、存储目录、管理端口、容量额度。

- `client/console.py`
  - 负责本地节点控制台 HTML。
  - 提供 `render_client_console_html(csrf_token)`。

- `client/node_mac.py`
  - 负责旧 Mac 节点客户端兼容逻辑。

- `client/node_config.example.json`
  - 负责客户端配置示例。

- `client/build_exe.bat` / `client/build_mac.sh`
  - 负责客户端打包脚本，脚本会自动回到项目根目录执行。

- `app/config.py`
  - 负责服务端环境配置对象 `ServerConfig`。
  - `server_main.py` 仍保留 `ADMIN_API_TOKEN`、`SESSION_SECRET` 等兼容变量。

- `app/database.py`
  - 负责数据库环境加载、连接配置、初始化 SQL 执行和数据库方言辅助 SQL。
  - 数据库初始化 SQL 归档到 `app/schema/`。

- `app/services/auth.py`
  - 负责密码 hash、会话 token、钱包签名消息和钱包地址恢复。

- `app/services/points.py`
  - 负责分享下载积分、节点下载积分和积分到收益单位换算。

- `app/services/shares.py`
  - 负责分享码、提取码 hash、分享过期/次数校验和分享记录格式化。

- `app/services/files.py`
  - 负责用户文件查询字段、存储节点解析、用户文件记录格式化。

- `app/services/withdrawals.py`
  - 负责提现金额、审核状态和状态流转校验。

- `app/schema/init_mysql.sql` / `app/schema/init_postgresql.sql`
  - 负责 MySQL / PostgreSQL 初始化 schema。

- `app/templates/upload.html` / `app/templates/download.html`
  - 旧上传/下载页面模板，样式和脚本拆分到 app/static/css 与 app/static/js。

- `app/services/runtime.py`
  - 负责运行时密钥检查、缺失密钥生成、`.env` 解析与回写。

- `app/web/pages.py`
  - 负责服务端页面模板常量和静态模板读取。
  - 保留 `HOME_HTML`、后台/用户/分享模板名称与 HTML 内容导出。

- `app/routes/pages.py`
  - 负责首页、后台登录页、统一管理台、用户上传页、分享页、健康检查等页面/轻量 API 蓝图。

- `app/services/ipfs.py`
  - 负责 IPFS RPC 地址解析、HTTP API 兜底客户端、状态读取。
  - 兼容测试和旧入口对 `server_main.requests`、`server_main.ipfshttpclient` 的 monkeypatch。

- `app/services/nodes.py`
  - 负责节点质量分、在线状态、排行榜、邀请树等展示型计算。

- `app/services/storage.py`
  - 负责文件 hash 校验、目录路径归一化、分享可见性、存储节点文件路径、加密分片 manifest。
  - 保持对 `server_main.SHARD_SIZE`、`server_main.file_shard` 等旧 monkeypatch 入口的兼容。

根目录兼容壳已删除：

- 客户端启动入口改为 `python -m client.main`。
- `auth.py`、`db.py`、`points.py`、`shares.py`、`files.py`、`withdrawals.py`、`client.py`、`client_config.py`、`client_console.py`、`node_mac.py` 不再保留根目录兼容壳。
- `server_main.py` 仍是服务端启动入口，但页面类路由已由 `app.routes.pages` 蓝图注册。

## 关键入口

服务端：

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/admin/login
http://127.0.0.1:8000/admin
http://127.0.0.1:8000/user/login
http://127.0.0.1:8000/user/upload
http://127.0.0.1:8000/user/dashboard
```

客户端：

```powershell
python -m client.main --storage-dir=D:\web3-node-data --storage-quota-gb=100 --manage-port=8787
```

客户端本地控制台：

```text
http://127.0.0.1:8787
```

## 验证记录

已执行：

```powershell
python -B -m unittest tests.test_mysql_config
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_server_main_delegates_runtime_pages_ipfs_and_node_helpers_to_flask_app_modules tests.test_mysql_config.MysqlConfigTest.test_public_homepage_links_business_user_admin_and_node_flows tests.test_mysql_config.MysqlConfigTest.test_admin_dashboard_is_available_at_admin_without_database tests.test_mysql_config.MysqlConfigTest.test_admin_login_page_renders_token_login_form_without_database tests.test_mysql_config.MysqlConfigTest.test_admin_login_api_validates_token_without_admin_header tests.test_mysql_config.MysqlConfigTest.test_user_upload_page_posts_to_user_file_api_with_bearer_token tests.test_mysql_config.MysqlConfigTest.test_public_share_page_downloads_with_inline_extract_code tests.test_mysql_config.MysqlConfigTest.test_build_encrypted_shard_manifest_records_hashes tests.test_mysql_config.MysqlConfigTest.test_user_file_upload_records_shard_metadata_and_audit
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_password_hash_verification_accepts_correct_password tests.test_mysql_config.MysqlConfigTest.test_password_verification_rejects_corrupted_hashes tests.test_mysql_config.MysqlConfigTest.test_point_helpers_calculate_share_and_node_download_points tests.test_mysql_config.MysqlConfigTest.test_validate_share_access_rejects_expired_active_share tests.test_mysql_config.MysqlConfigTest.test_validate_share_access_rejects_exhausted_active_share tests.test_mysql_config.MysqlConfigTest.test_validate_share_access_treats_naive_expiry_as_server_local_time tests.test_mysql_config.MysqlConfigTest.test_wallet_login_message_contains_nonce_and_purpose tests.test_mysql_config.MysqlConfigTest.test_default_database_engine_is_postgresql tests.test_mysql_config.MysqlConfigTest.test_postgres_environment_variables_are_preferred tests.test_mysql_config.MysqlConfigTest.test_mysql_environment_variables_are_preferred tests.test_mysql_config.MysqlConfigTest.test_dotenv_file_can_populate_environment_without_overwriting_existing tests.test_mysql_config.MysqlConfigTest.test_database_initializer_executes_init_sql_without_selected_database tests.test_mysql_config.MysqlConfigTest.test_mysql_initializer_ignores_duplicate_file_column_alters tests.test_mysql_config.MysqlConfigTest.test_mysql_initializer_ignores_duplicate_owner_index_creation tests.test_mysql_config.MysqlConfigTest.test_database_initializer_failure_updates_server_error tests.test_mysql_config.MysqlConfigTest.test_create_share_requires_owned_file_and_hashes_extract_code tests.test_mysql_config.MysqlConfigTest.test_create_share_retries_duplicate_share_code_collision tests.test_mysql_config.MysqlConfigTest.test_public_share_verify_checks_extract_code tests.test_mysql_config.MysqlConfigTest.test_share_download_logs_download_and_point_ledger_entries
python -B -m unittest tests.test_mysql_config.MysqlConfigTest.test_client_storage_route_rejects_hostile_origin_or_referer
python -B -m py_compile server_main.py client/__init__.py client/main.py client/config.py client/console.py client/node_mac.py app/config.py app/database.py app/routes/__init__.py app/routes/pages.py app/services/auth.py app/services/files.py app/services/points.py app/services/shares.py app/services/withdrawals.py app/services/runtime.py app/services/ipfs.py app/services/nodes.py app/services/storage.py app/web/pages.py
```

结果：

- `tests.test_mysql_config`：198 tests OK
- Flask 结构、页面蓝图、分片上传相关 9 条用例：OK
- 认证、积分、分享、数据库配置/初始化相关 19 条用例：OK
- `test_client_storage_route_rejects_hostile_origin_or_referer` 单测重跑：OK
- `py_compile`：通过

说明：

- 本轮客户端包归档后，全量 `tests.test_mysql_config` 已重新通过。
- `py_compile` 生成的 tracked pycache 已恢复，不作为交付改动。

## 回归覆盖

新增或调整的测试覆盖：

- 节点控制台 HTML 包含自动刷新状态节点和轮询逻辑。
- 节点控制台页面模板归属 `client/console.py`。
- 客户端配置与启动参数解析归属 `client/config.py`。
- 客户端入口、旧 Mac 客户端、配置示例和打包脚本归档到 `client/` 目录。
- 服务端模板拆分后，测试改为组合检查 HTML 结构和静态 CSS / JS 行为。
- 服务端模块归属 Flask 目录结构：`app.config`、`app.routes`、`app.services`、`app.web`。
- `auth.py`、`points.py`、`shares.py`、`db.py`、`files.py`、`withdrawals.py` 的真实实现归档到 `app.services` / `app.database`，根目录兼容壳已删除。
- `init_mysql.sql`、`init_postgresql.sql` 归档到 `app/schema/`。
- `upload.html`、`download.html` 归档到 `app/templates/`，并拆分 `app/static/css/upload.css`、`app/static/js/upload.js`、`app/static/css/download.css`、`app/static/js/download.js`。

主要回归文件：

```text
tests/test_mysql_config.py
```

## 文件职责

```text
client/main.py
```

客户端主入口、心跳循环、本地 HTTP 路由、存储分片读写、代理服务端节点 API。

```text
client/config.py
```

客户端配置文件、环境变量、启动参数解析。

```text
client/console.py
```

客户端本地控制台 HTML 和 CSRF 注入渲染。

```text
client/node_mac.py
```

旧 Mac 节点客户端兼容逻辑。

```text
server_main.py
```

服务端兼容启动入口、Flask app 实例、数据库事务、文件上传下载、节点调度和审计等尚未迁移的 API 工作流。

```text
app/config.py
```

服务端环境配置对象。

```text
app/database.py
```

数据库环境加载、连接配置、初始化 SQL 执行和数据库方言辅助 SQL。

```text
app/schema/
```

数据库初始化 SQL。

```text
app/routes/
```

Flask 蓝图目录；当前 `pages.py` 接管首页、管理台页面、登录页、分享页和健康检查。

```text
app/services/runtime.py
```

服务端运行时密钥和 `.env` 自举。

```text
app/services/auth.py
```

密码 hash、会话 token、钱包签名消息和钱包地址恢复。

```text
app/services/points.py
```

积分规则和收益单位换算。

```text
app/services/shares.py
```

分享码、提取码 hash、分享访问校验和分享记录格式化。

```text
app/services/files.py
```

用户文件查询字段、存储节点解析和用户文件记录格式化。

```text
app/services/withdrawals.py
```

提现金额、审核状态和状态流转校验。

```text
app/templates/
```

旧静态上传/下载 HTML 归档。

```text
app/web/pages.py
```

首页、管理台、用户页、分享页模板常量与模板文件读取。

```text
app/services/ipfs.py
```

IPFS API 地址解析、Kubo HTTP API 兜底客户端和 IPFS 状态读取。

```text
app/services/nodes.py
```

节点记录格式化、质量分、排行榜和邀请树。

```text
app/services/storage.py
```

文件 hash 校验、存储路径归一化、分享可见性和加密分片 manifest。

```text
app/templates/
```

服务端页面结构。

```text
app/static/
```

服务端页面样式和交互脚本，按 css / js 子目录分类。

## 风险与注意事项

- `server_main.py` 已拆出运行时、页面、IPFS、节点展示、存储分片、认证、积分、分享、文件格式化、提现校验和数据库基础能力，并迁移页面类路由到 Flask Blueprint；节点、分享、用户文件、审计等数据库密集路由仍较集中，后续可继续按 API 域拆分。
- 客户端真实实现已归档到 `client/` 目录，但本地 HTTP handler 仍在 `client/main.py` 内；下一轮适合继续抽到 `client/manage_server.py`。
- 服务端页面已拆分到模板和静态资源，首页模板常量已迁入 `app/web/pages.py`；后续可继续把首页改为独立 Jinja 模板文件。
- 高德地图和分享码需要模板动态注入，不能直接纯静态化。

## 后续建议

推荐下一步按小步拆分：

1. 新建 `client/manage_server.py`，迁移 `make_manage_handler()` 和 `start_manage_server()`。
2. 新建 `client/storage.py`，迁移本地分片、manifest、目录锁定、容量检测函数。
3. 继续在 `app/routes/` 和 `app/services/` 内迁移审计日志、分享下载、用户文件 API 这类边界清晰的服务端逻辑。
4. 继续减少 `server_main.py` 中的数据库密集路由，保持接口路径不变。

