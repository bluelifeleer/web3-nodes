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
pip install pymysql requests flask pycryptodome ipfshttpclient pywebview reedsolo
必须三个都装，少一个直接报错。
也可以直接执行：
pip install -r requirements.txt
第二步：数据库初始化（最容易出错的一步）
1. 打开数据库工具
Navicat / SQLyog / MySQL命令行均可
2. 新建数据库
数据库名必须严格一致：node_reward
CREATE DATABASE node_reward DEFAULT CHARACTER SET utf8mb4;
3. 执行三张表 SQL
依次执行以下三张表，缺一不可：
表1：user_node
CREATE TABLE `user_node` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_address` varchar(64) NOT NULL COMMENT '用户钱包/用户唯一地址',
  `invite_code` varchar(32) NOT NULL COMMENT '个人推广码',
  `parent_invite_code` varchar(32) DEFAULT '' COMMENT '上级推广码（绑定溯源）',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_user_addr` (`user_address`),
  UNIQUE KEY `idx_invite_code` (`invite_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户节点推广绑定关系';
表2：node_power
CREATE TABLE `node_power` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_address` varchar(64) NOT NULL,
  `node_mac` varchar(64) NOT NULL COMMENT '设备唯一指纹，防多开作弊',
  `disk_total` float DEFAULT 0 COMMENT '总硬盘容量G',
  `disk_used` float DEFAULT 0 COMMENT '有效存储占用G',
  `online_duration` int DEFAULT 0 COMMENT '当日在线时长分钟',
  `upload_bandwidth` float DEFAULT 0 COMMENT '当日上行流量',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_node_mac` (`node_mac`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='节点有效贡献数据';
表3：node_reward
CREATE TABLE `node_reward` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_address` varchar(64) NOT NULL,
  `reward_type` tinyint DEFAULT 1 COMMENT '1本级收益 2上级分成收益',
  `reward_amount` float DEFAULT 0,
  `node_contribution` float DEFAULT 0 COMMENT '对应贡献值',
  `settle_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '结算时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='节点收益分成记录';
表4：file_chain_record
CREATE TABLE `file_chain_record` (
  `id` int NOT NULL AUTO_INCREMENT,
  `file_name` varchar(255) DEFAULT '',
  `file_hash` varchar(128) NOT NULL COMMENT '文件最终哈希，上链存证',
  `ipfs_cid` varchar(128) NOT NULL COMMENT 'IPFS唯一CID',
  `file_size` float DEFAULT 0,
  `shard_count` int DEFAULT 0 COMMENT '分片数量',
  `upload_user` varchar(64) DEFAULT '' COMMENT '上传用户节点',
  `stored_nodes` text COMMENT '保存分片的节点列表',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_file_hash` (`file_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
表5：node_location
CREATE TABLE `node_location` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_address` varchar(64) NOT NULL COMMENT '节点唯一地址',
  `node_mac` varchar(64) NOT NULL,
  `ip_addr` varchar(64) DEFAULT '',
  `country` varchar(32) DEFAULT '',
  `province` varchar(32) DEFAULT '',
  `city` varchar(32) DEFAULT '',
  `lat` varchar(32) DEFAULT '0',
  `lng` varchar(32) DEFAULT '0',
  `online_status` tinyint DEFAULT 1 COMMENT '1在线 0离线',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_node_mac` (`node_mac`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='节点地理位置地图数据表';
第三步：配置服务端数据库连接
服务端支持用环境变量配置数据库，推荐不要把密码写死在代码里：
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=你的数据库密码
DB_NAME=node_reward
如果不配置，默认连接 127.0.0.1:3306 / root / 空密码 / node_reward。
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
解决：没创建 node_reward 数据库。
报错4：依赖报错 ModuleNotFound
解决：重新执行 pip install pymysql requests flask
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
否则：- 服务端会报错，提示 IPFS 读取失败
- 客户端会报错，提示 IPFS 未启动    
