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

ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS owner_user_id integer DEFAULT NULL;
ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS owner_wallet_address varchar(128) DEFAULT '';
ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS download_count integer DEFAULT 0;
ALTER TABLE file_chain_record ADD COLUMN IF NOT EXISTS last_download_at timestamp DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_file_chain_owner ON file_chain_record (owner_user_id);

CREATE TABLE IF NOT EXISTS app_user (
    id SERIAL PRIMARY KEY,
    username varchar(64) NOT NULL UNIQUE,
    password_hash varchar(255) NOT NULL,
    wallet_address varchar(128) UNIQUE,
    status varchar(16) DEFAULT 'active',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    last_login_at timestamp DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS wallet_nonce (
    id SERIAL PRIMARY KEY,
    wallet_address varchar(128) NOT NULL,
    nonce varchar(128) NOT NULL,
    expires_at timestamp NOT NULL,
    used_at timestamp DEFAULT NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_share (
    id SERIAL PRIMARY KEY,
    share_code varchar(32) NOT NULL UNIQUE,
    file_hash varchar(128) NOT NULL,
    owner_user_id integer NOT NULL,
    visibility varchar(16) DEFAULT 'public',
    extract_code_hash varchar(255) DEFAULT '',
    expires_at timestamp DEFAULT NULL,
    max_downloads integer DEFAULT 0,
    download_count integer DEFAULT 0,
    status varchar(16) DEFAULT 'active',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_download_log (
    id SERIAL PRIMARY KEY,
    share_code varchar(32) DEFAULT '',
    file_hash varchar(128) NOT NULL,
    downloader_ip varchar(64) DEFAULT '',
    downloader_user_id integer DEFAULT NULL,
    node_address varchar(128) DEFAULT '',
    file_size numeric(18,6) DEFAULT 0,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS point_ledger (
    id SERIAL PRIMARY KEY,
    user_id integer DEFAULT NULL,
    wallet_address varchar(128) DEFAULT '',
    point_type varchar(32) NOT NULL,
    amount numeric(18,6) NOT NULL,
    source_type varchar(32) DEFAULT '',
    source_id varchar(128) DEFAULT '',
    remark varchar(255) DEFAULT '',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS withdrawal_request (
    id SERIAL PRIMARY KEY,
    user_id integer NOT NULL,
    wallet_address varchar(128) NOT NULL,
    amount numeric(18,6) NOT NULL,
    status varchar(16) DEFAULT 'pending',
    admin_note varchar(255) DEFAULT '',
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    reviewed_at timestamp DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_wallet_nonce_address ON wallet_nonce (wallet_address);
CREATE INDEX IF NOT EXISTS idx_file_share_file ON file_share (file_hash);
CREATE INDEX IF NOT EXISTS idx_file_share_owner ON file_share (owner_user_id);
CREATE INDEX IF NOT EXISTS idx_download_file ON file_download_log (file_hash);
CREATE INDEX IF NOT EXISTS idx_download_share ON file_download_log (share_code);
CREATE INDEX IF NOT EXISTS idx_point_user ON point_ledger (user_id);
CREATE INDEX IF NOT EXISTS idx_point_wallet ON point_ledger (wallet_address);
CREATE INDEX IF NOT EXISTS idx_withdrawal_user ON withdrawal_request (user_id);
CREATE INDEX IF NOT EXISTS idx_withdrawal_status ON withdrawal_request (status);
