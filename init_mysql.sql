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
  `source_user_address` varchar(64) DEFAULT '' COMMENT '收益来源节点',
  `settle_date` date DEFAULT NULL COMMENT '结算日期，防重复结算',
  `settle_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '结算时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_reward_once` (`user_address`,`reward_type`,`source_user_address`,`settle_date`)
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
  `visibility` varchar(16) DEFAULT 'public' COMMENT 'public公开 private凭token访问',
  `access_token` varchar(64) DEFAULT '' COMMENT '私有文件访问令牌',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `deleted_at` datetime DEFAULT NULL COMMENT '软删除时间',
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

ALTER TABLE `file_chain_record` ADD COLUMN `owner_user_id` int DEFAULT NULL;
ALTER TABLE `file_chain_record` ADD COLUMN `owner_wallet_address` varchar(128) DEFAULT '';
ALTER TABLE `file_chain_record` ADD COLUMN `download_count` int DEFAULT 0;
ALTER TABLE `file_chain_record` ADD COLUMN `last_download_at` datetime DEFAULT NULL;
CREATE INDEX idx_file_chain_owner ON `file_chain_record` (`owner_user_id`);

CREATE TABLE IF NOT EXISTS `app_user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(64) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `wallet_address` varchar(128) DEFAULT NULL,
  `status` varchar(16) DEFAULT 'active',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `last_login_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_app_user_username` (`username`),
  UNIQUE KEY `idx_app_user_wallet` (`wallet_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `wallet_nonce` (
  `id` int NOT NULL AUTO_INCREMENT,
  `wallet_address` varchar(128) NOT NULL,
  `nonce` varchar(128) NOT NULL,
  `expires_at` datetime NOT NULL,
  `used_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_wallet_nonce_address` (`wallet_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `file_share` (
  `id` int NOT NULL AUTO_INCREMENT,
  `share_code` varchar(32) NOT NULL,
  `file_hash` varchar(128) NOT NULL,
  `owner_user_id` int NOT NULL,
  `visibility` varchar(16) DEFAULT 'public',
  `extract_code_hash` varchar(255) DEFAULT '',
  `expires_at` datetime DEFAULT NULL,
  `max_downloads` int DEFAULT 0,
  `download_count` int DEFAULT 0,
  `status` varchar(16) DEFAULT 'active',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_file_share_code` (`share_code`),
  KEY `idx_file_share_file` (`file_hash`),
  KEY `idx_file_share_owner` (`owner_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `file_download_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `share_code` varchar(32) DEFAULT '',
  `file_hash` varchar(128) NOT NULL,
  `downloader_ip` varchar(64) DEFAULT '',
  `downloader_user_id` int DEFAULT NULL,
  `node_address` varchar(128) DEFAULT '',
  `file_size` decimal(18,6) DEFAULT 0,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_download_file` (`file_hash`),
  KEY `idx_download_share` (`share_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `point_ledger` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL,
  `wallet_address` varchar(128) DEFAULT '',
  `point_type` varchar(32) NOT NULL,
  `amount` decimal(18,6) NOT NULL,
  `source_type` varchar(32) DEFAULT '',
  `source_id` varchar(128) DEFAULT '',
  `remark` varchar(255) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_point_user` (`user_id`),
  KEY `idx_point_wallet` (`wallet_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `withdrawal_request` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `wallet_address` varchar(128) NOT NULL,
  `amount` decimal(18,6) NOT NULL,
  `status` varchar(16) DEFAULT 'pending',
  `admin_note` varchar(255) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `reviewed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_withdrawal_user` (`user_id`),
  KEY `idx_withdrawal_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
