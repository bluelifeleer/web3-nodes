CREATE TABLE IF NOT EXISTS user_node (
  id SERIAL PRIMARY KEY,
  user_address varchar(64) NOT NULL,
  invite_code varchar(32) NOT NULL,
  parent_invite_code varchar(32) DEFAULT '',
  create_time timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_addr ON user_node (user_address);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invite_code ON user_node (invite_code);

CREATE TABLE IF NOT EXISTS node_power (
  id SERIAL PRIMARY KEY,
  user_address varchar(64) NOT NULL,
  node_mac varchar(64) NOT NULL,
  disk_total double precision DEFAULT 0,
  disk_used double precision DEFAULT 0,
  online_duration integer DEFAULT 0,
  upload_bandwidth double precision DEFAULT 0,
  update_time timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_node_mac ON node_power (node_mac);

CREATE TABLE IF NOT EXISTS node_reward (
  id SERIAL PRIMARY KEY,
  user_address varchar(64) NOT NULL,
  reward_type smallint DEFAULT 1,
  reward_amount double precision DEFAULT 0,
  node_contribution double precision DEFAULT 0,
  source_user_address varchar(64) DEFAULT '',
  settle_date date DEFAULT NULL,
  settle_time timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reward_once
  ON node_reward (user_address,reward_type,source_user_address,settle_date);

CREATE TABLE IF NOT EXISTS file_chain_record (
  id SERIAL PRIMARY KEY,
  file_name varchar(255) DEFAULT '',
  file_hash varchar(128) NOT NULL,
  ipfs_cid varchar(128) NOT NULL,
  file_size double precision DEFAULT 0,
  shard_count integer DEFAULT 0,
  upload_user varchar(64) DEFAULT '',
  stored_nodes text,
  visibility varchar(16) DEFAULT 'public',
  access_token varchar(64) DEFAULT '',
  create_time timestamp DEFAULT CURRENT_TIMESTAMP,
  deleted_at timestamp DEFAULT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_file_hash ON file_chain_record (file_hash);

CREATE TABLE IF NOT EXISTS node_location (
  id SERIAL PRIMARY KEY,
  user_address varchar(64) NOT NULL,
  node_mac varchar(64) NOT NULL,
  ip_addr varchar(64) DEFAULT '',
  country varchar(32) DEFAULT '',
  province varchar(32) DEFAULT '',
  city varchar(32) DEFAULT '',
  lat varchar(32) DEFAULT '0',
  lng varchar(32) DEFAULT '0',
  online_status smallint DEFAULT 1,
  update_time timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_node_location_mac ON node_location (node_mac);
