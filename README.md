# Web3 节点激励与文件分享系统

这版先从首页进入：

```text
http://127.0.0.1:8000
```

首页会串联用户登录、上传文件、用户面板、后台登录、后台面板、节点接入和健康检查。

系统包含三条主线：

- 后台管理：节点列表、文件记录、IPFS 状态、分享记录、下载记录、积分流水、提现审核。
- 用户产品：注册登录、钱包绑定/钱包登录、上传文件、创建分享链接、分享下载、积分收益、提现申请。
- 客户端节点：注册节点、上报心跳、统计本地 IPFS 存储占用、绑定上级邀请码。

默认推荐 PostgreSQL，同时保留 MySQL 兼容。

## 1. 环境准备

需要安装：

- Python 3.8+
- PostgreSQL 13+，推荐
- MySQL 5.7 / 8.0，可选兼容模式
- IPFS Kubo，本地文件上传/下载需要

安装 Python 依赖：

```powershell
cd C:\Users\HUAWEI\www\web3-nodes
pip install -r requirements.txt
```

如果依赖下载慢，可以使用国内镜像：

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 2. 配置 `.env`

项目会自动读取根目录 `.env`。仓库没有强制提供 `.env.example`，可以直接新建 `.env`。

`ADMIN_API_TOKEN`、`SESSION_SECRET`、`AES_KEY` 可以不手动填写。服务端首次启动时如果发现缺失，会自动生成、写入 `.env`，并在命令行打印，方便复制。

PostgreSQL 推荐配置：

```env
DB_ENGINE=postgresql
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=你的数据库密码
POSTGRES_DB_NAME=web3_modes_store

MAX_UPLOAD_MB=100
```

MySQL 兼容配置：

```env
DB_ENGINE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的数据库密码
MYSQL_DB_NAME=web3_modes_store

MAX_UPLOAD_MB=100
```

说明：

- `DB_ENGINE=postgresql` 时使用 `init_postgresql.sql`。
- `DB_ENGINE=mysql` 时使用 `init_mysql.sql`。
- `ADMIN_API_TOKEN` 用于后台登录。
- `SESSION_SECRET` 用于用户登录 Token。
- `AES_KEY` 当前代码使用 AES，需要 16 字节字符串；自动生成时会生成可用长度。
- `AMAP_WEB_KEY` 和 `AMAP_SECURITY_JSCODE` 可选，用于后台节点地图；两者缺一时后台会自动降级为节点分布看板，避免地图 SDK 报 `INVALID_USER_KEY` / `INVALID_USER_SCODE`。
- 不要提交真实 `.env`，仓库已忽略 `.env`。

## 3. 数据库初始化

正常情况下不需要手动执行 SQL。

启动服务端时会自动执行：

- PostgreSQL：检查并创建 `POSTGRES_DB_NAME`，再执行 `init_postgresql.sql`。
- MySQL：连接 MySQL 后执行 `init_mysql.sql`。

只有启动失败或排查数据库权限时，才需要手动执行：

```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -d web3_modes_store -f init_postgresql.sql
```

或：

```powershell
mysql -h 127.0.0.1 -P 3306 -u root -p < init_mysql.sql
```

## 4. 启动 IPFS

文件上传和分享下载需要本地 IPFS API。

```powershell
ipfs daemon
```

保持这个窗口运行。再新开一个终端验证：

```powershell
ipfs stats repo --human
```

如果能输出仓库大小，说明本地 IPFS 可用。

如果 `ipfs daemon` 出现类似下面的 mDNS 警告：

```text
mdns: Failed to set multicast interface: setsockopt: An invalid argument was supplied.
```

通常是 Windows 某个网络适配器不支持组播接口导致的局域网发现警告。只要 `ipfs stats repo --human` 和 API 端口可用，上传备份一般不受影响。如果希望关闭这个提示，可以执行：

```powershell
ipfs config --json Discovery.MDNS.Enabled false
```

然后重启 `ipfs daemon`。

## 5. 启动服务端

新开终端：

```powershell
cd C:\Users\HUAWEI\www\web3-nodes
python server_main.py
```

看到下面输出代表服务启动成功：

```text
完整服务启动成功！后台地址：http://127.0.0.1:8000
```

如果自动生成了运行密钥，还会看到类似：

```text
已自动生成运行密钥，并写入 .env：
ADMIN_API_TOKEN=...
SESSION_SECRET=...
AES_KEY=...
后台登录地址：http://127.0.0.1:8000/admin/login
```

服务监听：

```text
http://127.0.0.1:8000
```

## 6. 首页和后台管理使用

打开首页：

```text
http://127.0.0.1:8000
```

首页包含用户、节点和后台所有核心入口。

首次进入后台建议打开登录页：

```text
http://127.0.0.1:8000/admin/login
```

输入 `.env` 中的 `ADMIN_API_TOKEN` 登录。登录成功后页面会把后台 Token 保存到浏览器：

```text
localStorage.admin_token
```

之后访问后台：

```text
http://127.0.0.1:8000/admin
```

后台会自动加载数据；如果没有 Token，会自动跳回 `/admin/login`。

后台可用功能：

- 查看节点列表和在线状态
- 查看节点存储、带宽、在线时长
- 配置分成比例
- 查看文件记录、搜索文件、查看 IPFS CID
- 查看文件副本健康状态
- 查看 IPFS 状态
- 查看用户分享记录
- 查看下载记录
- 查看积分流水
- 审核用户提现申请

后台页面会每 10 秒自动刷新节点、收益、文件、排行榜、邀请树、IPFS 状态和地图数据，同时保留手动刷新按钮。

后台管理上传仍走原后台 Token 流程：

- 静态上传页：`/upload.html`
- 上传接口：`/api/upload_file`
- 需要后台 Token 鉴权

## 7. 用户端使用

### 注册 / 登录

打开：

```text
http://127.0.0.1:8000/user/login
```

支持：

- 用户名密码注册
- 用户名密码登录
- 钱包登录

登录成功后，页面会把返回的用户 Token 保存到浏览器：

```text
localStorage.user_token
```

后续 `/user/dashboard` 和 `/user/upload` 会自动使用这个 Token。

### 用户面板

打开：

```text
http://127.0.0.1:8000/user/dashboard
```

用户面板会展示：

- 当前账号和钱包
- 已上传文件
- 已创建分享
- 积分流水
- 累计收益
- 已提现金额
- 冻结中提现
- 可提现余额
- 提现记录

### 钱包绑定

在 `/user/dashboard` 的钱包绑定区域：

1. 填写钱包地址。
2. 点击获取绑定 nonce。
3. 用钱包签名页面展示的 message。
4. 填入 nonce 和签名并提交绑定。

绑定成功后，可在 `/user/login` 使用钱包登录。

### 上传文件

打开：

```text
http://127.0.0.1:8000/user/upload
```

上传流程：

1. 先登录，确保浏览器里有 `localStorage.user_token`。
2. 选择文件。
3. 选择公开或私有。
4. 点击上传。
5. 上传成功后页面会显示 `file_hash`。

当前新版用户上传文件不再暴露原始裸下载链接，必须创建分享链接后下载。

### 创建分享链接

在 `/user/upload` 上传成功后，可以继续填写：

- 提取码，可选
- 过期时间，可选
- 最大下载次数，`0` 表示不限次数

点击创建分享后，会得到：

```text
http://127.0.0.1:8000/s/<share_code>
```

分享接口：

```text
POST /api/user/files/<file_hash>/shares
```

### 访问分享和下载

别人打开：

```text
http://127.0.0.1:8000/s/<share_code>
```

页面会自动读取：

```text
GET /api/share/<share_code>
```

如果分享需要提取码，页面内会显示输入框，不会弹窗。

点击下载时调用：

```text
GET /api/share/<share_code>/download
```

下载成功后系统会：

- 记录下载日志
- 增加分享下载次数
- 给分享文件的用户增加分享下载积分
- 给存储节点增加节点下载积分

过期、停用、删除、次数用完或提取码错误时，下载接口会拒绝访问。

### 提现

用户在 `/user/dashboard` 可提交提现申请。

要求：

- 用户已绑定钱包
- 可提现余额足够
- 提现金额大于等于最小精度

后台管理员在管理端审核提现。

## 8. 启动客户端节点

复制节点配置：

```powershell
copy node_config.example.json node_config.json
```

示例配置：

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

客户端不再默认使用内置目录作为有效存储。首次启动必须显式指定存储目录和愿意贡献的可用容量，否则节点只会启动本地管理页并提示配置目录，不会作为健康存储节点参与分片写入。

推荐启动方式：

```powershell
python client.py --storage-dir=D:\web3-node-data --storage-quota-gb=100 --manage-port=8787
```

也可以写入 `node_config.json`：

```json
{
  "storage_dir": "D:/web3-node-data",
  "storage_quota_gb": 100,
  "manage_port": 8787
}
```

或使用环境变量：

```powershell
$env:NODE_STORAGE_DIR="D:\web3-node-data"
$env:NODE_STORAGE_QUOTA_GB="100"
python client.py
```

配置后客户端会自动创建目录锁和隐藏存储根：

```text
D:\web3-node-data
  .web3_nodes.lock
  .web3_nodes_store\
    files\
    manifest\
```

说明：

- `.web3_nodes.lock` 会绑定 `user_addr` 和 `node_mac`，避免多个节点误用同一目录。
- `.web3_nodes_store` 保存加密分片和 manifest，不保存明文文件。
- Windows 下会尝试对 `.web3_nodes_store` 执行隐藏/系统属性；失败不会删除数据，但会在目录健康状态里提示。
- 心跳会上报物理总容量、目录已用容量、物理可用容量、用户声明的 `storage_quota_gb` 和计算后的 `storage_available_gb`。

客户端启动后会同时拉起本地管理页：

```text
http://127.0.0.1:8787
```

如果你改了 `--manage-port`、`manage_port` 配置或 `NODE_MANAGE_PORT`，管理页地址会随之变化。

本地管理页当前提供：

- 目录健康检查：显示目录是否可写、是否锁定、最近一次检测错误和当前路径。
- 容量上报概览：总容量、已使用、物理可用容量、声明可用容量、剩余可写额度。
- 收益与提现：通过本地 `/api/earnings`、`/api/withdrawals` 代理读取服务端节点收益和提现记录，并可从本地页提交提现申请。
- 分片存储 API：服务端可写入/读取加密分片，客户端按 `file_hash/chunk_index` 保存并维护 manifest。
- 控制操作：支持安全停止节点；`重启节点` 第一版只返回提示，开发模式暂不执行自动进程替换。

## 9. 分片存储、下载校验与兜底

用户文件上传后，服务端会：

1. 计算原文件 `file_hash = sha256(plain)`。
2. AES 加密完整文件。
3. 对密文切片并为每个分片生成 `chunk_hash`。
4. 将加密分片下发到真实客户端节点目录。
5. 写入 `file_shard_record` 分片元数据。
6. 同时保存一份服务端模拟节点兜底副本，并尝试上传 IPFS 备份。

下载时会优先从真实客户端节点读取分片，逐片验证 `chunk_hash`，按 `chunk_index` 合并密文，解密后再次验证 `sha256(plain) == file_hash`。只有完整校验通过后才返回文件并记录下载收益；客户端分片不可用时会依次尝试服务端兜底副本和 IPFS 备份。

## 10. 存储审计日志与导出

后台 `/admin` 页面包含“存储审计日志”区域，可按 `file_hash`、节点地址、事件类型、状态筛选并刷新，点击“详情”查看 `metadata_json`。

后台 API：

```text
GET /api/admin/audit/storage
GET /api/admin/audit/storage/export?format=json
GET /api/admin/audit/storage/export?format=csv
```

所有后台审计接口都需要 `X-Admin-Token` 或 `admin_token`。审计日志覆盖上传接收、加密切片、客户端分片写入/读取、hash 校验失败、解密失败、server/IPFS 兜底使用和最终下载成功等事件。

说明：

- 本地管理页的浏览器操作始终调用本地 `127.0.0.1` 接口，再由客户端代理访问服务端节点 API。
- `/api/storage` 更新目录后会立即重新检测，并把新的目录状态用于后续容量上报。
- `停止节点` 会把客户端切换为停止状态，后续心跳循环会结束；默认不会直接强杀当前 Python 进程。
- `重启节点` 当前只返回“开发模式暂不支持自动重启，请手动重新运行 client.py”，避免误触发危险的进程替换。
- 客户端默认不再自动打开 pywebview 地图窗口，避免 Windows WebView 临时数据目录被占用时出现清理警告；确实需要地图窗口时，先配置 `AMAP_WEB_KEY`、`AMAP_SECURITY_JSCODE`，再设置 `$env:NODE_OPEN_MAP_WINDOW="1"` 后启动客户端。

正常输出类似：

```text
Web3分布式存储激励节点启动成功
节点注册成功
节点持续运行中，实时上报存储数据...
心跳上报成功
```

后台节点列表能看到该节点，就说明客户端心跳正常。

如果服务端暂时未启动或网络中断，客户端不会退出；它会按 `reconnect_interval` 自动重试注册。注册成功后才进入心跳循环，心跳失败也会继续等待下一轮上报。

## 11. 邀请码 / 上级绑定

客户端支持通过启动参数指定上级邀请码：

```powershell
python client.py invite=你的邀请码
```

或：

```powershell
python client.py --invite=你的邀请码
```

也可以在 `node_config.json` 中配置：

```json
{
  "parent_invite": "你的邀请码"
}
```

客户端还支持环境变量覆盖：

```powershell
$env:NODE_SERVER_URL="http://127.0.0.1:8000"
$env:NODE_PARENT_INVITE="你的邀请码"
$env:NODE_HEARTBEAT_INTERVAL="60"
$env:NODE_RECONNECT_INTERVAL="10"
$env:NODE_STORAGE_DIR="D:\web3-node-data"
python client.py
```

## 12. IPFS 安装

项目调用本地 IPFS 命令和 API：

```powershell
ipfs stats repo --human
ipfs daemon
```

推荐安装官方 Kubo 命令行版本。

### Windows

打开官方文档：

```text
https://docs.ipfs.tech/install/command-line/
```

下载 Windows 压缩包，解压后把 `ipfs.exe` 所在目录加入系统 `PATH`。

验证：

```powershell
ipfs --version
ipfs init
ipfs daemon
```

### macOS

推荐 Homebrew：

```bash
brew install ipfs
ipfs --version
ipfs init
ipfs daemon
```

### Linux

常见 amd64 服务器：

```bash
wget https://dist.ipfs.tech/kubo/latest/kubo_latest_linux-amd64.tar.gz
tar -xvzf kubo_latest_linux-amd64.tar.gz
cd kubo
sudo bash install.sh
ipfs --version
ipfs init
ipfs daemon
```

### Docker

```bash
docker run -d --name ipfs_host \
  -v ipfs_staging:/export \
  -v ipfs_data:/data/ipfs \
  -p 4001:4001 \
  -p 127.0.0.1:5001:5001 \
  -p 127.0.0.1:8080:8080 \
  ipfs/kubo:latest
```

建议只把 `5001` API 端口绑定到 `127.0.0.1`，不要直接暴露公网。

## 13. 常见问题

### 网页打不开

检查服务端是否真正启动：

```powershell
python server_main.py
```

如果启动失败，优先检查：

- 数据库服务是否启动
- `.env` 数据库账号密码是否正确
- 端口 `8000` 是否被占用
- Python 依赖是否安装完整

### 后台登录 / Token

后台现在有独立登录页：

```text
http://127.0.0.1:8000/admin/login
```

输入 `.env` 里的：

```env
ADMIN_API_TOKEN=...
```

登录后再进入后台首页。Token 失效时后台会自动清除本地 Token 并回到登录页。

### 用户登录接口提示登录密钥未配置

检查 `.env` 是否配置：

```env
SESSION_SECRET=请改成一串随机字符串
```

修改 `.env` 后需要重启服务端。

### 数据库连接失败

检查：

- `DB_ENGINE` 是否为 `postgresql` 或 `mysql`
- PostgreSQL / MySQL 服务是否启动
- 数据库账号是否有创建数据库和建表权限
- 远程数据库端口是否可连接

### IPFS 文件读取失败

确认 IPFS daemon 正在运行：

```powershell
ipfs daemon
```

并确认 API 端口 `5001` 可用。

### 依赖报错 `ModuleNotFoundError`

重新安装依赖：

```powershell
pip install -r requirements.txt
```

## 14. 成功标准

全部满足即表示系统跑通：

- 服务端正常启动 `http://127.0.0.1:8000`
- 后台页面可以打开
- 后台登录后能自动加载并定时刷新节点/文件/收益数据
- 用户可以注册登录
- 用户可以上传文件并创建 `/s/<share_code>` 分享
- 分享页可以按提取码/过期时间/下载次数限制下载
- 下载后有下载日志和积分流水
- 客户端节点可以注册并持续心跳
- 后台节点列表能看到在线节点
