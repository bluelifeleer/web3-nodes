Web3节点激励系统 首次启动全套调试手册（从零跑通）
前言：99%用户报错原因
你刚才出现 URL拼写错误/打不开后台，不是代码BUG，是：
- 数据库没建库、没建表
- 代码内数据库密码没改成自己的
- 依赖没装全
- 服务没真正启动成功
下面严格按顺序 1~5 步操作，百分百跑通整套系统。
第一步：环境准备（必须全部完成）
1. 必备软件
- Python 3.8+
- MySQL 5.7 / 8.0
- 已安装 IPFS 本地节点（可选，不装也能测试）
2. 安装依赖（关键）
打开 CMD / 终端，执行：
pip install -r requirements.txt
所有 Python 运行依赖和打包依赖都已维护在 requirements.txt 中。
第二步：数据库初始化（最容易出错的一步）
1. 打开数据库工具
Navicat / SQLyog / MySQL命令行均可
2. 执行初始化脚本
项目已把建库和 5 张表的建表语句整理到 init_mysql.sql，可重复执行：
mysql -h 172.25.244.60 -P 3306 -u root -p < init_mysql.sql
脚本会自动创建并切换到数据库：
web3_modes_store
第三步：配置服务端数据库连接
服务端支持用环境变量配置数据库，优先读取 MYSQL_*，并兼容旧的 DB_*：
MYSQL_HOST=172.25.244.60
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=cjl19880307
MYSQL_DB_NAME=web3_modes_store
如果不配置，默认连接 172.25.244.60:3306 / root / cjl19880307 / web3_modes_store。
数据库不可用时后台首页仍可打开，/api/health 会返回具体数据库错误。
第四步：启动服务端 & 验证后台是否正常
1. 运行服务端
终端执行：
python server_main.py
2. 看到以下文字代表启动成功
✅ 完整服务启动成功！后台地址：http://127.0.0.1:8000
3. 浏览器打开后台
直接输入：http://127.0.0.1:8000
成功页面：看到「分成比例配置、节点列表、收益记录」三个面板。
第五步：启动客户端节点，测试绑定 & 心跳
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
1. 设置上级推广码
打开 client.py
修改：PARENT_INVITE = "你的推广码"
2. 重启客户端
新节点会自动绑定上级，后台可看到「上级推广码」归属关系，分成自动生效。
第七步：自动结算功能验证
系统默认：每日 00:00 自动批量结算上下级收益。
如需测试，可以手动修改代码时间为当前分钟，快速验证分账逻辑。
第八步：常见报错精准排错（解决你所有问题）
报错1：网页打不开 / URL错误
原因：服务没启动成功 / 数据库连接失败直接闪退
解决：确认数据库密码正确、库表齐全，重新运行服务端。
报错2：客户端连接失败
解决：确认8000端口没被占用，服务端正常运行。
报错3：数据库报错 Unknown database
解决：没执行 init_mysql.sql，或没有创建 web3_modes_store 数据库。
报错4：依赖报错 ModuleNotFound
解决：重新执行 pip install -r requirements.txt
报错5：IPFS 读取失败
解决：不影响运行，无IPFS时自动模拟存储数据，可正常测试收益。
第九步：整套系统成功标准（全部满足即完工）
- ✅ 服务端正常启动 8000 端口
- ✅ 后台网页正常打开、无报错
- ✅ 客户端节点注册成功、心跳持续上报
- ✅ 后台可看到在线节点、存储、带宽、时长
- ✅ 支持自定义上下级分成比例
- ✅ 节点绑定上级、裂变关系生效
- ✅ 自动分账逻辑正常运行
第十步：后期商用拓展指引
- 可打包客户端为 exe，发给用户一键部署
- 可搭建前端下载页，自动带推广参数
- 可接入钱包、积分、提现功能
- 可自定义存储算力权重、分红比例、等级制度

必须运行本地IPFS节点：ipfs daemon
否则：
- 服务端会报错，提示 IPFS 读取失败
- 客户端会报错，提示 IPFS 未启动

第十一步：不同系统安装 IPFS（Kubo）
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
