CREATE DATABASE IF NOT EXISTS `web3_modes_store` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `web3_modes_store`;

CREATE TABLE IF NOT EXISTS `user_node` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_address` varchar(64) NOT NULL COMMENT '用户钱包/用户唯一地址',
  `invite_code` varchar(32) NOT NULL COMMENT '个人推广码',
  `parent_invite_code` varchar(32) DEFAULT '' COMMENT '上级推广码（绑定溯源）',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_user_addr` (`user_address`),
  UNIQUE KEY `idx_invite_code` (`invite_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户节点推广绑定关系';

CREATE TABLE IF NOT EXISTS `node_power` (
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

CREATE TABLE IF NOT EXISTS `node_reward` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_address` varchar(64) NOT NULL,
  `reward_type` tinyint DEFAULT 1 COMMENT '1本级收益 2上级分成收益',
  `reward_amount` float DEFAULT 0,
  `node_contribution` float DEFAULT 0 COMMENT '对应贡献值',
  `settle_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '结算时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='节点收益分成记录';

CREATE TABLE IF NOT EXISTS `file_chain_record` (
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

CREATE TABLE IF NOT EXISTS `node_location` (
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
