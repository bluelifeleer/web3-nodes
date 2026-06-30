# Web3 节点存储与文件分享系统

这是一个 Flask + 本地节点客户端的分布式存储原型。系统把用户上传文件加密切片后优先写入真实客户端节点目录，同时保留服务端兜底副本并尝试上传 IPFS 备份；下载时会验证切片 hash、合并密文、解密并再次校验原文件 hash。

当前主入口：

```text
http://127.0.0.1:8000
```

核心角色：

- 用户端：注册登录、钱包绑定/钱包登录、上传文件、创建分享、提取码下载、积分收益、提现申请。
- 管理端：节点状态、文件记录、IPFS 状态、存储审计、分享记录、下载日志、积分流水、提现审核。
- 客户端节点：指定存储目录和容量、锁定/隐藏目录、保存加密分片、上报容量与心跳、提供本地管理页。

默认推荐 PostgreSQL，保留 MySQL 兼容。

## 当前代码审查摘要

本次审查覆盖了根目录入口、`app/` 服务端模块、`client/` 客户端模块、schema、模板静态资源和 `tests/test_mysql_config.py`。当前结构已经从单文件原型整理为 Flask 目录结构，但仍保留一部分兼容入口。

主要结论：

- `app/routes/` 已接管页面、认证、节点、财务、后台管理、用户文件与分享 API。
- `app/services/` 已承载认证、分享、积分、提现、IPFS、存储、节点展示等纯逻辑。
- `client/main.py` 仍偏大，包含本地 HTTP 管理服务、分片读写、心跳、代理收益/提现等逻辑；后续适合继续拆出 `client/storage.py` 和 `client/manage_server.py`。
- `server_main.py` 仍保留旧后台上传、传统文件列表/下载、地图位置、自动修复、加密/下载核心 helper 和数据库事务兼容入口。
- 当前 AES 实现使用 ECB 模式以兼容既有测试和流程；生产级加密建议后续升级为 AES-GCM 或带认证的 CBC/CTR 方案，并迁移旧数据。

工程归档记录：

```text
docs/engineering/2026-06-29-console-modularization-archive.md
```

## 目录结构

```text
web3-nodes/
  server_main.py                 服务端兼容启动入口和未拆完的核心 helper
  requirements.txt               Python 依赖
  app/
    config.py                    服务端环境配置
    database.py                  数据库连接、初始化、方言辅助
    routes/                      Flask Blueprint
      pages.py                   首页、登录页、管理台、分享页、健康检查
      auth.py                    用户认证和钱包 API
      nodes.py                   节点注册、心跳、排行榜、节点收益
      files.py                   用户文件、分享、公开下载 API
      finance.py                 用户收益/提现、后台提现审核
      admin.py                   后台审计、用户/分享/下载/积分列表
    services/                    业务 helper
    schema/                      PostgreSQL / MySQL 初始化 SQL
    templates/                   Jinja 页面模板
    static/css, static/js        页面样式和交互脚本
  client/
    main.py                      客户端节点入口和本地管理服务
    config.py                    客户端配置和启动参数解析
    console.py                   本地节点控制台 HTML
    node_config.example.json     节点配置示例
  tests/test_mysql_config.py     主要回归测试
```

## 环境要求

- Python 3.10+，代码使用 `str | None` 等 3.10 类型语法。
- PostgreSQL 13+，推荐。
- MySQL 5.7 / 8.0，可选兼容模式。
- IPFS Kubo，可选但推荐；真实节点写入成功时，IPFS 作为兜底备份。

安装依赖：

```powershell
cd C:\Users\HUAWEI\www\web3-nodes
pip install -r requirements.txt
```

国内镜像：

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 服务端配置

项目会读取根目录 `.env`。如果 `ADMIN_API_TOKEN`、`SESSION_SECRET`、`AES_KEY` 缺失，服务端启动时会自动生成并追加写入 `.env`。

PostgreSQL 示例：

```env
DB_ENGINE=postgresql
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=你的数据库密码
POSTGRES_DB_NAME=web3_modes_store

MAX_UPLOAD_MB=100
```

MySQL 示例：

```env
DB_ENGINE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的数据库密码
MYSQL_DB_NAME=web3_modes_store

MAX_UPLOAD_MB=100
```

可选配置：

```env
ADMIN_API_TOKEN=后台登录Token
SESSION_SECRET=用户登录Token签名密钥
AES_KEY=16字节AES密钥

AMAP_WEB_KEY=高德Web Key
AMAP_SECURITY_JSCODE=高德安全密钥

IPFS_API_ADDR=/ip4/127.0.0.1/tcp/5001
IPFS_API_URL=http://127.0.0.1:5001
NODE_STORAGE_API_URL_TEMPLATE=http://127.0.0.1:{port}
```

说明：

- `DB_ENGINE=postgresql` 使用 `app/schema/init_postgresql.sql`。
- `DB_ENGINE=mysql` 使用 `app/schema/init_mysql.sql`。
- `AES_KEY` 必须是 16 字节字符串；自动生成值满足当前代码要求。
- 高德地图配置两项都存在时才加载地图 SDK，否则后台降级为普通节点看板。
- IPFS API 地址优先读取 `IPFS_API_ADDR` / `IPFS_API_MULTIADDR` / `IPFS_API_URL`，未配置时会尝试 `ipfs config Addresses.API`，最后才退回 `127.0.0.1:5001`。

## 数据库初始化

服务端启动时会自动初始化数据库和表结构。一般不需要手动执行 SQL。

手动初始化 PostgreSQL：

```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -d web3_modes_store -f app/schema/init_postgresql.sql
```

手动初始化 MySQL：

```powershell
mysql -h 127.0.0.1 -P 3306 -u root -p < app/schema/init_mysql.sql
```

## 启动 IPFS

推荐先启动 Kubo：

```powershell
ipfs daemon
```

验证 API 地址：

```powershell
ipfs config Addresses.API
ipfs stats repo --human
```

如果你的 Kubo 输出类似：

```text
RPC API server listening on /ip4/127.0.0.1/tcp/5002
```

可以写入 `.env`：

```env
IPFS_API_ADDR=/ip4/127.0.0.1/tcp/5002
```

Kubo 0.42 等新版本如果被 `ipfshttpclient` 判定版本不兼容，代码会自动切换到内置 HTTP API 客户端。

## 启动服务端

```powershell
cd C:\Users\HUAWEI\www\web3-nodes
python server_main.py
```

服务端监听：

```text
http://127.0.0.1:8000
```

常用入口：

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/admin/login
http://127.0.0.1:8000/admin
http://127.0.0.1:8000/user/login
http://127.0.0.1:8000/user/upload
http://127.0.0.1:8000/user/dashboard
http://127.0.0.1:8000/console
```

健康检查：

```text
GET /api/health
```

## 管理端

打开：

```text
http://127.0.0.1:8000/admin/login
```

输入 `.env` 中的 `ADMIN_API_TOKEN`。登录成功后页面会把 token 保存为：

```text
localStorage.admin_token
```

管理端功能：

- 节点列表、在线状态、容量、带宽、质量分。
- 节点收益、排行榜、邀请树。
- 文件记录、文件副本健康、IPFS 状态。
- 用户、分享、下载日志、积分流水。
- 用户/节点提现审核。
- 存储审计日志筛选和导出。

后台 API 通过 `X-Admin-Token` 或 `admin_token` 查询参数鉴权。

审计导出：

```text
GET /api/admin/audit/storage
GET /api/admin/audit/storage/export?format=json
GET /api/admin/audit/storage/export?format=csv
```

## 用户端

登录注册：

```text
http://127.0.0.1:8000/user/login
```

支持：

- 用户名密码注册/登录。
- 钱包 nonce 签名登录。
- 登录后 token 保存为 `localStorage.user_token`。

上传：

```text
http://127.0.0.1:8000/user/upload
POST /api/user/files
```

用户上传需要真实可用客户端节点。没有可用节点时接口会返回：

```text
暂无可用用户节点，请先启动节点客户端后再上传
```

分享：

```text
POST /api/user/files/<file_hash>/shares
GET /api/user/shares
PATCH /api/user/shares/<share_code>
DELETE /api/user/shares/<share_code>
```

公开访问：

```text
GET /s/<share_code>
GET /api/share/<share_code>
POST /api/share/<share_code>/verify
GET /api/share/<share_code>/download
```

分享支持提取码、过期时间、最大下载次数和启停状态。下载成功后会记录下载日志、更新下载次数，并写入用户分享积分和节点下载积分。

## 客户端节点

复制示例配置：

```powershell
copy client\node_config.example.json node_config.json
```

示例：

```json
{
  "server_url": "http://127.0.0.1:8000",
  "parent_invite": "",
  "heartbeat_interval": 60,
  "reconnect_interval": 10,
  "manage_port": 8787,
  "storage_dir": "",
  "storage_quota_gb": 0
}
```

首次作为真实存储节点使用时，必须指定存储目录和容量：

```powershell
python -m client.main --storage-dir=D:\web3-node-data --storage-quota-gb=100 --manage-port=8787
```

也可以用环境变量：

```powershell
$env:NODE_SERVER_URL="http://127.0.0.1:8000"
$env:NODE_STORAGE_DIR="D:\web3-node-data"
$env:NODE_STORAGE_QUOTA_GB="100"
$env:NODE_MANAGE_PORT="8787"
python -m client.main
```

客户端启动后默认自动打开本地管理页：

```text
http://127.0.0.1:8787
```

如需关闭自动打开浏览器：

```powershell
$env:NODE_OPEN_CLIENT_CONSOLE="0"
python -m client.main --storage-dir=D:\web3-node-data --storage-quota-gb=100
```

本地存储结构：

```text
D:\web3-node-data
  .web3_nodes.lock
  .web3_nodes_store\
    files\
    manifest\
```

规则：

- `.web3_nodes.lock` 绑定 `user_addr` 和 `node_mac`，防止多个节点误用同一目录。
- `.web3_nodes_store` 保存加密分片和 manifest，不保存明文文件。
- Windows 下会尝试给 `.web3_nodes_store` 设置隐藏/系统属性。
- 心跳会上报目录容量、声明容量、已用容量、可写剩余额度和本地分片 API 地址。
- 节点控制台可动态刷新状态、收益、提现和存储目录检查结果。

本地节点控制台提供“卸载节点服务”操作：

- 卸载前可以点击“保存节点标识”下载 `web3-node-identity-<节点地址>.json`，文件包含 `user_addr`、`node_mac`、服务端地址、存储目录和容量等支持查询所需信息。
- 卸载前会向服务端读取节点收益。
- 如果仍有可提现收益、待审核提现或已审核待打款提现，卸载会被阻止，并提示先处理收益。
- 收益处理完成后，卸载会删除用户存储目录下的 `.web3_nodes_store` 和 `.web3_nodes.lock`，清理本地加密分片、manifest 和目录锁；如果根目录已为空，会一并删除该空目录。
- 如果用户指定目录里还有其它非节点文件，根目录会被保留并写入跳过列表，避免误删用户自己的数据。
- 打包后的客户端会生成延迟卸载脚本，在当前进程退出后删除客户端程序目录；开发源码模式只清理节点数据，不会删除仓库源码。
- 卸载完成后节点停止心跳并释放该目录，后续重新启动需要重新指定目录和容量。

节点标识支持服务端查询：

```text
GET  /node/lookup
POST /api/node/identity/lookup
```

`/node/lookup` 支持上传节点端保存的 JSON 文件，或粘贴 JSON 内容。服务端会校验 `user_addr + node_mac` 是否匹配已注册节点，并返回节点容量、在线状态、收益汇总和最近提现记录，用于后续客服或运营协助。

客户端本地 API 只绑定 `127.0.0.1`，并校验 Host、Origin/Referer 和 CSRF token。服务端写入分片使用：

```text
GET  /api/node/identity
POST /api/node/storage/shards
GET /api/node/storage/shards/<file_hash>/<chunk_index>
GET /api/node/storage/files/<file_hash>/manifest
POST /api/control/uninstall
```

## 文件存储和下载链路

用户上传文件：

1. 服务端计算 `file_hash = sha256(plain)`。
2. 使用 `AES_KEY` 加密完整文件。
3. 对密文按 `SHARD_SIZE` 切片。
4. 为每片生成 `chunk_hash` 和 manifest。
5. 选择有容量和本地 API 的真实客户端节点。
6. 下发加密分片到客户端目录。
7. 写入 `file_chain_record`、`file_shard_record` 和 `storage_audit_log`。
8. 写入服务端兜底副本，并尝试上传 IPFS 备份。

用户下载分享文件：

1. 校验分享状态、提取码、过期时间、下载次数。
2. 优先从真实客户端节点读取分片。
3. 校验每个 `chunk_hash`。
4. 按 `chunk_index` 合并密文。
5. 解密并校验 `sha256(plain) == file_hash`。
6. 如果真实节点不可用，尝试服务端兜底副本和 IPFS 备份。
7. 校验通过后返回附件，并写入下载日志和积分流水。

## 旧后台上传接口

仍保留旧后台上传/下载能力，主要用于兼容和管理端测试：

```text
POST /api/upload_check
POST /api/upload_chunk
POST /api/upload_merge
POST /api/upload_file
GET  /api/file_list
GET  /api/file_health
GET  /api/file_download/<file_hash>
```

普通用户上传和分享应优先使用 `/user/upload` 与 `/api/user/files`。

## 邀请码和节点收益

客户端支持指定上级邀请码：

```powershell
python -m client.main --invite=你的邀请码 --storage-dir=D:\web3-node-data --storage-quota-gb=100
```

或：

```env
NODE_PARENT_INVITE=你的邀请码
```

节点收益和提现：

```text
GET  /api/node/me
GET  /api/node/earnings
GET  /api/node/withdrawals
POST /api/node/withdrawals
```

用户收益和提现：

```text
GET  /api/user/earnings
GET  /api/user/points
GET  /api/user/withdrawals
POST /api/user/withdrawals
```

## 常见问题

### 上传提示没有可用节点

检查：

- 客户端是否用 `python -m client.main` 启动。
- 是否指定了 `--storage-dir` 和 `--storage-quota-gb`。
- 客户端本地管理页是否显示目录健康。
- 服务端后台节点列表是否显示 `storage_api_url`、可用容量和最近心跳。

### 卸载节点提示需要先处理收益

这是预期保护。节点卸载会清理本地分片和目录锁，因此系统会先检查节点收益：

- `available_earnings` 大于 0：先在本地节点控制台提交提现。
- `pending_withdrawals` 或 `locked_withdrawals` 大于 0：等待管理员审核和打款完成。
- 服务端不可达或收益状态无法确认：暂时不能卸载，避免收益未处理就释放节点。
- 卸载前建议先保存节点标识；如果以后需要服务端协助，可打开 `/node/lookup` 上传或粘贴该标识查询节点快照。

### IPFS 显示离线但 daemon 已启动

先看 Kubo 实际 API 端口：

```powershell
ipfs config Addresses.API
```

如果不是 5001，在 `.env` 配置：

```env
IPFS_API_ADDR=/ip4/127.0.0.1/tcp/5002
```

重启服务端后再查看后台 IPFS 状态。

### `Unsupported daemon version`

新 Kubo 版本可能不被 `ipfshttpclient` 支持。当前代码会在遇到该错误时自动使用 HTTP API 兜底客户端；确认 `.env` 的 IPFS API 地址正确即可。

### 用户登录提示密钥未配置

确认 `.env` 中有：

```env
SESSION_SECRET=...
```

没有时重启服务端，代码会自动生成。

### 后台登录失败

确认 `.env` 中有：

```env
ADMIN_API_TOKEN=...
```

并通过 `/admin/login` 登录，不要直接手动构造后台请求。

## 测试和验证

主要回归：

```powershell
python -B -m unittest tests.test_mysql_config
```

语法检查：

```powershell
python -B -m py_compile server_main.py client\__init__.py client\main.py client\config.py client\console.py client\node_mac.py app\__init__.py app\config.py app\database.py app\routes\__init__.py app\routes\admin.py app\routes\auth.py app\routes\finance.py app\routes\files.py app\routes\nodes.py app\routes\pages.py app\services\__init__.py app\services\auth.py app\services\files.py app\services\points.py app\services\shares.py app\services\withdrawals.py app\services\runtime.py app\services\ipfs.py app\services\nodes.py app\services\storage.py app\web\__init__.py app\web\pages.py
```

当前测试覆盖重点：

- 数据库配置和 schema 初始化。
- 运行密钥自动生成。
- 首页、后台、用户页、分享页模板与静态资源。
- 客户端本地管理 API、CSRF、Host/Origin 防护。
- 客户端目录锁定、隐藏、容量上报、心跳、节点标识导出和卸载保护。
- 用户文件上传、真实节点分片写入、IPFS 兜底。
- 分享创建、提取码、过期/次数限制、下载积分。
- 服务端节点标识上传/粘贴查询。
- IPFS API 地址识别和 HTTP API 兜底。

## 后续工程建议

优先级较高：

- 将 `client/main.py` 拆为 `client/storage.py`、`client/manage_server.py`、`client/heartbeat.py`。
- 将 `server_main.py` 中旧后台上传、地图位置、自动修复和加密下载 helper 继续迁到 `app/routes/` 与 `app/services/`。
- 将当前 AES-ECB 升级为带认证加密方案，并设计旧文件迁移策略。
- 为审计日志增加更细的前端筛选和下载失败原因聚合。

优先级中等：

- 增加 `.env.example`。
- 为客户端多目录配置补充正式 JSON schema。
- 将首页 HTML 常量迁移为独立 Jinja 模板。

## 跑通标准

全部满足时，当前开发环境基本可用：

- `python server_main.py` 正常启动。
- `/api/health` 返回数据库正常。
- `/admin/login` 可用 `ADMIN_API_TOKEN` 登录。
- `python -m client.main --storage-dir=... --storage-quota-gb=...` 启动节点。
- 后台节点列表显示节点在线、容量不为 0。
- 用户可以注册登录、上传文件并创建 `/s/<share_code>`。
- 分享页可以验证提取码并下载文件。
- 后台能看到下载日志、积分流水和存储审计日志。
