Web3节点激励系统 首次启动全套调试手册（从零跑通）
前言：99%用户报错原因
你刚才出现 URL拼写错误/打不开后台，不是代码BUG，是：
- 数据库没建库、没建表
- .env 里的数据库配置或 ADMIN_API_TOKEN 没配置好
- 依赖没装全
- 服务没真正启动成功
下面严格按顺序 1~5 步操作，百分百跑通整套系统。
第一步：环境准备（必须全部完成）
1. 必备软件
- Python 3.8+
- PostgreSQL 13+（默认推荐）
- MySQL 5.7 / 8.0（兼容模式，可选）
- 已安装 IPFS 本地节点（可选，不装也能测试）
2. 安装依赖（关键）
打开 CMD / 终端，执行：
pip install -r requirements.txt
所有 Python 运行依赖和打包依赖都已维护在 requirements.txt 中。
第二步：配置服务端数据库连接
复制 .env.example 为 .env，然后按你的数据库环境修改。默认推荐 PostgreSQL：
DB_ENGINE=postgresql
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=你的数据库密码
POSTGRES_DB_NAME=web3_modes_store
ADMIN_API_TOKEN=请改成一串只有管理员知道的随机字符串
MAX_UPLOAD_MB=100
AES_KEY=1234567890123456
如果要继续使用 MySQL：
DB_ENGINE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的数据库密码
MYSQL_DB_NAME=web3_modes_store
服务端会根据 DB_ENGINE 自动选择 PostgreSQL 或 MySQL，并兼容旧的 DB_*。
不要把真实 .env 提交到 Git，仓库已通过 .gitignore 忽略 .env。
第三步：数据库初始化（服务启动会自动执行）
服务启动时会自动读取 init_postgresql.sql 或 init_mysql.sql，创建 web3_modes_store 数据库和业务表。
如需手动排查，也可以执行：
psql -h 你的PostgreSQL地址 -p 5432 -U postgres -d web3_modes_store -f init_postgresql.sql
或：
mysql -h 你的MySQL地址 -P 3306 -u root -p < init_mysql.sql
数据库不可用时后台首页仍可打开，/api/health 会返回具体数据库错误。
第四步：启动服务端 & 验证后台是否正常
1. 运行服务端
终端执行：
python server_main.py
2. 看到以下文字代表启动成功
✅ 完整服务启动成功！后台地址：http://127.0.0.1:8000
3. 浏览器打开后台
直接输入：http://127.0.0.1:8000
成功页面：看到「后台 Token、分成比例配置、节点列表、收益记录」等面板。
在页面顶部输入 .env 里的 ADMIN_API_TOKEN，点击「保存并加载」后后台数据会自动刷新。
第五步：启动客户端节点，测试绑定 & 心跳
客户端支持复制 node_config.example.json 为 node_config.json 配置服务地址、默认推广码和心跳间隔：
{
  "server_url": "http://127.0.0.1:8000",
  "parent_invite": "",
  "heartbeat_interval": 60
}
也可以用环境变量 NODE_SERVER_URL、NODE_PARENT_INVITE、NODE_HEARTBEAT_INTERVAL 覆盖。
1. 新开一个终端
执行客户端：
python3 client.py
2. 正常日志输出
- 🚀 Web3分布式存储激励节点启动成功
- ✅ 节点注册成功
- 🔄 节点持续运行中
- 每60秒打印一次心跳上报成功
3. 后台验证
刷新后台节点列表，能看到你的本机节点、存储容量、在线时长，即为完全跑通。
第六步：推广绑定测试（核心裂变功能）
1. 通过启动参数设置上级推广码
Windows：
client.exe invite=你的推广码
或把下载后的 exe 命名为：
node_invite_你的推广码.exe
2. macOS/Linux：
python3 node_mac.py invite=你的推广码
3. 重启客户端
新节点会自动绑定上级，后台可看到「上级推广码」归属关系，分成自动生效。
第七步：自动结算功能验证
系统默认：每日 00:00 自动批量结算上下级收益，并按 settle_date + 来源节点防重复结算。
如需测试，可以手动修改代码时间为当前分钟，快速验证分账逻辑。
第八步：文件存储能力验证
后台文件面板支持：
- 按文件名、文件哈希、IPFS CID 搜索记录
- 查看公开/私有权限和私有访问令牌
- 通过下载链接从 IPFS 取回并解密文件
- 删除文件记录（软删除，不直接删除 IPFS 内容）
- 查看副本健康状态和 IPFS 节点状态
上传页可选择公开下载或私有下载。私有文件需要下载链接中的 token 才能取回。
第九步：常见报错精准排错（解决你所有问题）
报错1：网页打不开 / URL错误
原因：服务没启动成功 / 数据库连接失败直接闪退
解决：确认数据库密码正确、库表齐全，重新运行服务端。
报错2：客户端连接失败
解决：确认8000端口没被占用，服务端正常运行。
报错3：数据库报错 Unknown database
解决：确认 .env 中 MySQL 连接信息正确；服务启动会自动执行 init_mysql.sql，也可以手动执行脚本排查。
报错4：依赖报错 ModuleNotFound
解决：重新执行 pip install -r requirements.txt
如果安装慢就使用-i https://pypi.tuna.tsinghua.edu.cn/simple 表示使用国内镜像
报错5：IPFS 读取失败
解决：不影响运行，无IPFS时自动模拟存储数据，可正常测试收益。
第十步：整套系统成功标准（全部满足即完工）
- ✅ 服务端正常启动 8000 端口
- ✅ 后台网页正常打开、无报错
- ✅ 客户端节点注册成功、心跳持续上报
- ✅ 后台可看到在线节点、存储、带宽、时长
- ✅ 支持自定义上下级分成比例
- ✅ 节点绑定上级、裂变关系生效
- ✅ 自动分账逻辑正常运行
第十一步：后期商用拓展指引
- 可打包客户端为 exe，发给用户一键部署
- 可搭建前端下载页，自动带推广参数
- 可接入钱包、积分、提现功能
- 可自定义存储算力权重、分红比例、等级制度

必须运行本地IPFS节点：ipfs daemon
否则：
- 服务端会报错，提示 IPFS 读取失败
- 客户端会报错，提示 IPFS 未启动

第十二步：不同系统安装 IPFS（Kubo）
项目会调用本地 IPFS 命令和 API：
ipfs stats repo --human
ipfs daemon
因此推荐安装官方 Kubo 命令行版本。

1. Windows 安装
打开官方 Kubo 安装文档：
https://docs.ipfs.tech/install/command-line/
下载 Windows 版本压缩包，解压后把 ipfs.exe 所在目录加入系统 PATH。
验证安装：
ipfs --version
ipfs init
ipfs daemon

2. macOS 安装
推荐使用 Homebrew：
brew install ipfs
ipfs --version
ipfs init
ipfs daemon
如果没有 Homebrew，也可以从官方 Kubo 安装文档下载 macOS 压缩包手动安装。

3. Linux 安装
常见 amd64 服务器可执行：
wget https://dist.ipfs.tech/kubo/latest/kubo_latest_linux-amd64.tar.gz
tar -xvzf kubo_latest_linux-amd64.tar.gz
cd kubo
sudo bash install.sh
ipfs --version
ipfs init
ipfs daemon

4. Docker 安装
适合服务器或隔离部署：
docker run -d --name ipfs_host \
  -v ipfs_staging:/export \
  -v ipfs_data:/data/ipfs \
  -p 4001:4001 \
  -p 127.0.0.1:5001:5001 \
  -p 127.0.0.1:8080:8080 \
  ipfs/kubo:latest
注意：5001 是 IPFS API 端口，建议只绑定本机 127.0.0.1，不要直接暴露公网。

5. 安装后验证
保持 ipfs daemon 运行，再新开一个终端执行：
ipfs stats repo --human
如果能输出仓库大小，说明客户端可以正常读取 IPFS 状态。
