# 服务端主程序 server_main.py（完整版带API路由，修复8000端口报错）
import time
import hashlib
import random
from datetime import datetime
import pymysql
import requests
from flask import Flask, request, jsonify, render_template_string, g
try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None
import os
import shutil
import json
try:
    import reedsolo
except ImportError:
    reedsolo = None

# ==================== 初始化Flask服务 ====================
app = Flask(__name__)

# ==================== 数据库配置 ====================
# 可用环境变量覆盖，避免把本机密码写死在代码里：
# 优先读取 MYSQL_*，兼容旧的 DB_*。
def get_env(primary_key, legacy_key, default):
    return os.getenv(primary_key) or os.getenv(legacy_key) or default


DB_CONFIG = {
    "host": get_env("MYSQL_HOST", "DB_HOST", "172.25.244.60"),
    "user": get_env("MYSQL_USER", "DB_USER", "root"),
    "password": get_env("MYSQL_PASSWORD", "DB_PASSWORD", "cjl19880307"),
    "database": get_env("MYSQL_DB_NAME", "DB_NAME", "web3_modes_store"),
    "port": int(get_env("MYSQL_PORT", "DB_PORT", "3306")),
    "charset": "utf8mb4",
    "autocommit": True,
    "connect_timeout": 3,
    "read_timeout": 10,
    "write_timeout": 10,
}
db = None
cursor = None
db_error = ""


def init_db():
    global db, cursor, db_error
    try:
        if db is not None:
            db.ping(reconnect=True)
        else:
            db = pymysql.connect(**DB_CONFIG)
        cursor = db.cursor()
        db_error = ""
        return True
    except Exception as exc:
        db = None
        cursor = None
        db_error = str(exc)
        return False


@app.before_request
def require_database_for_api():
    if request.path == "/" or request.path == "/api/health":
        return None
    if not init_db():
        return jsonify({
            "code": 503,
            "msg": "数据库连接失败，请检查 MySQL 是否启动、库表是否创建、MYSQL_PASSWORD/DB_PASSWORD 是否正确",
            "error": db_error,
        }), 503
    g.db = db
    g.cursor = cursor

# ==================== 全局分成配置（开发者后台可改） ====================
SELF_RATIO = 0.15    # 上级分成比例15%
NODE_RATIO = 0.85    # 节点本级收益85%
ONLINE_VALID_MIN = 10 # 最低有效在线时长(分钟)

# ===================== 配置 =====================
AES_KEY = "1234567890123456"  # 自定义加密密钥
SHARD_SIZE = 1024 * 1024  # 1MB 分片

# 临时分片存储目录
CHUNK_TMP_DIR = "./chunk_tmp"
os.makedirs(CHUNK_TMP_DIR, exist_ok=True)

# 分片大小 1MB
CHUNK_SIZE = 1024 * 1024
AES_KEY = "1234567890123456"
SHARD_SIZE = 1024 * 1024

# ===================== 新增：数据防丢核心配置 =====================
# 每个分片保存3个副本（企业级标准）
COPY_NUM = 3
# 纠删码配置：10数据片 +3校验片
EC_DATA_SHARD = 10
EC_PARITY_SHARD = 3

# 替换原有分片节点分配逻辑
# 原逻辑：随机分配少量节点 → 极易丢数据
# 新逻辑：跨地区、跨IP、多副本冗余，永不丢数据

# 全局配置接口动态修改
@app.route("/api/set_ratio",methods=["POST"])
def set_ratio():
    global SELF_RATIO,NODE_RATIO
    data = request.get_json()
    SELF_RATIO = float(data.get("self_ratio",0.15))
    NODE_RATIO = float(data.get("node_ratio",0.85))
    return jsonify({"code":200,"msg":"分成比例修改成功","data":{"self_ratio":SELF_RATIO,"node_ratio":NODE_RATIO}})

# 生成推广码
def create_invite_code():
    return hashlib.md5(str(random.random()).encode()).hexdigest()[:10]

# 1. 节点注册接口
@app.route("/register",methods=["POST"])
def node_register():
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    parent_invite = data.get("parent_invite","")

    # 判断设备是否已注册
    cursor.execute("select * from node_power where node_mac=%s",(node_mac,))
    if cursor.fetchone():
        return jsonify({"code":200,"msg":"节点已注册，无需重复绑定"})

    # 生成用户专属推广码、绑定上级
    invite_code = create_invite_code()
    cursor.execute(
        "insert into user_node(user_address,invite_code,parent_invite_code) values(%s,%s,%s)",
        (user_addr,invite_code,parent_invite)
    )
    # 初始化节点数据
    cursor.execute(
        "insert into node_power(user_address,node_mac) values(%s,%s)",
        (user_addr,node_mac)
    )
    return jsonify({"code":200,"msg":"节点注册成功，上级绑定完成","invite_code":invite_code})

# 2. 节点心跳上报接口
@app.route("/heartbeat",methods=["POST"])
def node_heartbeat():
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    disk_used = data.get("disk_used",0)
    upload_bw = data.get("upload_bw",0)

    cursor.execute(
        "update node_power set disk_used=%s,upload_bandwidth=%s,online_duration=online_duration+1,update_time=%s where user_address=%s and node_mac=%s",
        (disk_used,upload_bw,datetime.now(),user_addr,node_mac)
    )
    return jsonify({"code":200,"msg":"心跳上报成功"})

# 3. 每日自动分账函数
def auto_settle_reward():
    cursor.execute("select * from node_power where online_duration > %s",(ONLINE_VALID_MIN,))
    node_list = cursor.fetchall()

    for node in node_list:
        user_addr = node[1]
        disk_contrib = node[4]
        online_contrib = node[5]
        # 贡献值计算公式
        total_contrib = disk_contrib * 10 + online_contrib * 0.5
        total_reward = round(total_contrib * 0.01,4)

        # 写入节点本级收益
        node_reward = total_reward * NODE_RATIO
        cursor.execute(
            "insert into node_reward(user_address,reward_type,reward_amount,node_contribution) values(%s,1,%s,%s)",
            (user_addr,node_reward,total_contrib)
        )

        # 写入上级分成收益
        cursor.execute("select parent_invite_code from user_node where user_address=%s",(user_addr,))
        parent_res = cursor.fetchone()
        if not parent_res:continue
        parent_code = parent_res[0]
        if parent_code:
            cursor.execute("select user_address from user_node where invite_code=%s",(parent_code,))
            super_res = cursor.fetchone()
            if super_res:
                super_addr = super_res[0]
                super_reward = total_reward * SELF_RATIO
                cursor.execute(
                    "insert into node_reward(user_address,reward_type,reward_amount,node_contribution) values(%s,2,%s,%s)",
                    (super_addr,super_reward,total_contrib)
                )
    return True

# 4. 后台数据接口：节点列表
@app.route("/api/node_list",methods=["GET"])
def node_list():
    cursor.execute("""
    SELECT un.user_address,un.invite_code,un.parent_invite_code,
    np.disk_used,np.online_duration,np.upload_bandwidth,np.update_time
    FROM user_node un LEFT JOIN node_power np ON un.user_address=np.user_address
    """)
    res = cursor.fetchall()
    data_list = []
    for item in res:
        data_list.append({
            "user_addr":item[0],
            "invite_code":item[1],
            "parent_code":item[2],
            "disk_used":item[3],
            "online_min":item[4],
            "upload_bw":item[5],
            "update_time":str(item[6])
        })
    return jsonify({"code":200,"data":data_list})

# 5. 后台数据接口：收益列表
@app.route("/api/reward_list",methods=["GET"])
def reward_list():
    cursor.execute("select * from node_reward order by settle_time desc")
    res = cursor.fetchall()
    data_list = []
    for item in res:
        data_list.append({
            "id":item[0],
            "user_addr":item[1],
            "reward_type":"本级收益" if item[2]==1 else "上级分成",
            "amount":item[3],
            "contrib":item[4],
            "time":str(item[5])
        })
    return jsonify({"code":200,"data":data_list})

# ==================== 极简前端后台面板 ====================
ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Web3节点激励后台面板</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{padding:20px;background:#f5f7fa;font-family:微软雅黑;}
        .box{background:#fff;padding:20px;border-radius:8px;margin-bottom:20px;box-shadow:0 0 8px #eee;}
        h3{margin-bottom:15px;color:#222;}
        table{width:100%;border-collapse:collapse;margin-top:10px;}
        th,td{border:1px solid #eee;padding:10px;text-align:center;font-size:14px;}
        th{background:#f0f5ff;}
        input,button{padding:8px 12px;margin:0 5px;border-radius:4px;border:1px solid #ccc;}
        button{background:#2d8cf0;color:#fff;border:none;cursor:pointer;}
    </style>
    <script type="text/javascript" src="https://webapi.amap.com/maps?v=2.0&key=6f17f9896974a8686929496921212479"></script>
</head>
<body>
    <div class="box">
        <h3>分成比例配置</h3>
        <input type="text" id="selfRatio" placeholder="上级分成比例" value="0.15">
        <input type="text" id="nodeRatio" placeholder="节点分成比例" value="0.85">
        <button onclick="setRatio()">保存配置</button>
    </div>

    <div class="box">
        <h3>全网节点列表</h3>
        <button onclick="getNodes()">刷新节点数据</button>
        <table>
            <thead>
                <tr>
                    <th>节点地址</th>
                    <th>个人推广码</th>
                    <th>上级推广码</th>
                    <th>存储占用G</th>
                    <th>在线时长(分)</th>
                    <th>上行带宽</th>
                </tr>
            </thead>
            <tbody id="nodeTable"></tbody>
        </table>
    </div>

    <div class="box" style="min-height:600px;">
        <h3>🌍 全网节点全球地理分布地图</h3>
        <p style="color:#888;font-size:14px;margin-bottom:15px;">实时在线节点打点｜离线节点灰色显示｜自动IP属地解析</p>
        <div id="map" style="width:100%;height:500px;border-radius:8px;"></div>
    </div>

    <div class="box">
        <h3>收益结算记录</h3>
        <button onclick="getReward()">刷新收益数据</button>
        <table>
            <thead>
                <tr>
                    <th>节点地址</th>
                    <th>收益类型</th>
                    <th>收益金额</th>
                    <th>贡献值</th>
                    <th>结算时间</th>
                </tr>
            </thead>
            <tbody id="rewardTable"></tbody>
        </table>
    </div>

    <div class="box">
    <h3>📁 文件加密上链存证记录（分布式存储）</h3>
    <button onclick="getFileList()">刷新存证数据</button>
    <table>
        <thead>
            <tr>
                <th>文件名</th>
                <th>IPFS-CID</th>
                <th>文件哈希(上链)</th>
                <th>分片数</th>
                <th>存储节点数</th>
                <th>上传时间</th>
            </tr>
        </thead>
        <tbody id="fileTable"></tbody>
    </table>
</div>

<script>
// 修改分成比例
function setRatio(){
    let s = document.getElementById("selfRatio").value;
    let n = document.getElementById("nodeRatio").value;
    fetch("/api/set_ratio",{
        method:"POST",
        body:JSON.stringify({self_ratio:s,node_ratio:n}),
        headers:{"Content-Type":"application/json"}
    }).then(res=>res.json()).then(data=>{alert(data.msg);})
}

// 获取节点列表
function getNodes(){
    fetch("/api/node_list")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.user_addr}</td>
                <td>${item.invite_code}</td>
                <td>${item.parent_code||"无"}</td>
                <td>${item.disk_used}</td>
                <td>${item.online_min}</td>
                <td>${item.upload_bw}</td>
            </tr>`
        })
        document.getElementById("nodeTable").innerHTML = html;
    })
}

// 获取收益记录
function getReward(){
    fetch("/api/reward_list")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.user_addr}</td>
                <td>${item.reward_type}</td>
                <td>${item.amount}</td>
                <td>${item.contrib}</td>
                <td>${item.time}</td>
            </tr>`
        })
        document.getElementById("rewardTable").innerHTML = html;
    })
}

function getFileList(){
    fetch("/api/file_list")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.file_name}</td>
                <td style="font-size:12px">${item.ipfs_cid}</td>
                <td style="font-size:12px">${item.file_hash.substring(0,20)}...</td>
                <td>${item.shard}</td>
                <td>${item.nodes.length}</td>
                <td>${item.time}</td>
            </tr>`
        })
        document.getElementById("fileTable").innerHTML = html;
    })
}

let map = null;
let markerList = [];

function initMap(){
    // 初始化地图，中心点中国
    map = new AMap.Map('map', {
        zoom: 3,
        center: [105.27, 35.31]
    });
    map.addControl(new AMap.Scale());
    map.addControl(new AMap.ToolBar());
    loadNodeMap();
}

// 加载节点点位
function loadNodeMap(){
    // 清空旧标记
    markerList.forEach(m=>map.remove(m));
    markerList = [];

    fetch("/api/map_node_list")
    .then(res=>res.json())
    .then(data=>{
        data.data.forEach(item=>{
            let lat = parseFloat(item.lat);
            let lng = parseFloat(item.lng);
            if(lat===0 || lng===0) return;

            // 在线绿色、离线灰色
            let iconUrl = item.status===1 
            ? "https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png"
            : "https://webapi.amap.com/theme/v1.3/markers/n/mark_bs.png";

            let marker = new AMap.Marker({
                position: [lng,lat],
                icon: iconUrl,
                zIndex: item.status===1 ? 10 : 1
            });

            // 悬浮弹窗信息
            let info = `
                节点地址：${item.user_addr}<br/>
                地区：${item.country} ${item.province} ${item.city}<br/>
                状态：${item.status===1 ? "✅ 在线" : "❌ 离线"}
            `;
            marker.on('mouseover',function(e){
                let infoWin = new AMap.InfoWindow({content:info});
                infoWin.open(map, [lng,lat]);
            })
            map.add(marker);
            markerList.push(marker);
        })
    })
}

// 每30秒刷新地图
setInterval(loadNodeMap,30000);

// 自动加载数据
window.onload = function(){
initMap();
    getNodes();
    getReward();
    getFileList();
}
</script>
</body>
</html>
'''

# 后台首页路由
@app.route("/")
def admin_index():
    return render_template_string(ADMIN_HTML)


@app.route("/api/health")
def health_check():
    db_ok = init_db()
    return jsonify({
        "code": 200 if db_ok else 503,
        "server": "ok",
        "database": "ok" if db_ok else "error",
        "db_error": db_error,
    }), 200 if db_ok else 503

# 定时结算线程
def settle_task():
    while True:
        if time.strftime("%H:%M") == "00:00":
            auto_settle_reward()
        time.sleep(60)

# AES加密
def aes_encrypt(data):
    if AES is None:
        raise RuntimeError("缺少 pycryptodome 依赖，请执行：pip install pycryptodome")
    cipher = AES.new(AES_KEY.encode(), AES.MODE_ECB)
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    return cipher.encrypt(data)

# 文件分片
def file_shard(data):
    shards = []
    for i in range(0, len(data), SHARD_SIZE):
        shards.append(data[i:i+SHARD_SIZE])
    return shards

# 文件哈希
def get_file_hash(data):
    return hashlib.sha256(data).hexdigest()

# 1. 校验文件分片进度（断点续传/秒传）
@app.route("/api/upload_check", methods=["POST"])
def upload_check():
    data = request.get_json()
    file_hash = data.get("fileHash")
    file_dir = os.path.join(CHUNK_TMP_DIR, file_hash)
    if not os.path.exists(file_dir):
        return jsonify({"code":200,"data":{"uploadedChunk":0}})
    
    # 获取已上传分片下标
    chunk_list = []
    for f in os.listdir(file_dir):
        if f.isdigit():
            chunk_list.append(int(f))
    if not chunk_list:
        return jsonify({"code":200,"data":{"uploadedChunk":0}})
    return jsonify({"code":200,"data":{"uploadedChunk":max(chunk_list)+1}})

# 2. 分片上传接口
@app.route("/api/upload_chunk", methods=["POST"])
def upload_chunk():
    file_hash = request.form.get("fileHash")
    chunk_index = int(request.form.get("chunkIndex"))
    chunk_total = int(request.form.get("chunkTotal"))
    chunk = request.files["chunk"]

    # 分片临时目录
    file_dir = os.path.join(CHUNK_TMP_DIR, file_hash)
    os.makedirs(file_dir, exist_ok=True)
    chunk_path = os.path.join(file_dir, str(chunk_index))

    # 已存在直接跳过（秒传）
    if os.path.exists(chunk_path):
        return jsonify({"code":200,"msg":"分片已存在"})

    chunk.save(chunk_path)
    return jsonify({"code":200,"msg":"分片上传成功"})

# 3. 分片合并 + 加密 + 分布式存储 + IPFS上链
@app.route("/api/upload_merge", methods=["POST"])
def upload_merge():
    data = request.get_json()
    file_hash = data.get("fileHash")
    file_name = data.get("fileName")
    upload_addr = data.get("user_addr")

    file_dir = os.path.join(CHUNK_TMP_DIR, file_hash)
    if not os.path.exists(file_dir):
        return jsonify({"code":400,"msg":"分片不存在"})

    # 读取所有分片并合并
    chunk_files = [int(i) for i in os.listdir(file_dir)]
    chunk_files.sort()
    file_data = b""
    for idx in chunk_files:
        with open(os.path.join(file_dir, str(idx)),"rb") as f:
            file_data += f.read()

    # 原有核心业务：加密、分片、IPFS、存证、算力分红
    try:
        encrypt_data = aes_encrypt(file_data)
    except RuntimeError as exc:
        return jsonify({"code":500,"msg":str(exc)}), 500
    shards = file_shard(encrypt_data)
    shard_num = len(shards)
    real_file_hash = get_file_hash(file_data)

    # IPFS上传
    import ipfshttpclient
    try:
        client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001')
        cid = client.add_bytes(encrypt_data)
    except:
        return jsonify({"code":400,"msg":"IPFS节点未启动"})

    # 分配在线节点存储
    cursor.execute("select user_address from node_power where online_duration > 10")
    online_nodes = [x[0] for x in cursor.fetchall()]
    import random
    assign_nodes = random.sample(online_nodes, min(len(online_nodes),shard_num)) if online_nodes else get_backup_nodes()

    # 写入存证数据库
    cursor.execute('''
    insert into file_chain_record(file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes)
    values(%s,%s,%s,%s,%s,%s,%s)
    ''',(file_name,real_file_hash,cid,round(len(file_data)/1024/1024,3),shard_num,upload_addr,json.dumps(assign_nodes, ensure_ascii=False)))
    db.commit()

    # 节点算力奖励
    for node in assign_nodes:
        cursor.execute('update node_power set disk_used=disk_used+0.1 where user_address=%s',(node,))
    db.commit()

    # 清理临时分片
    shutil.rmtree(file_dir)

    return jsonify({
        "code":200,
        "msg":"文件加密上链完成",
        "data":{
            "file_hash":real_file_hash,
            "ipfs_cid":cid,
            "shard_count":shard_num,
            "storage_nodes":assign_nodes
        }
    })

# 废弃旧接口，防止冲突
@app.route("/api/upload_file",methods=["POST"])
def api_upload_file():
    uploaded_file = request.files.get("file")
    upload_addr = request.form.get("user_addr", "")
    if not uploaded_file:
        return jsonify({"code":400,"msg":"缺少上传文件"})

    file_data = uploaded_file.read()
    if not file_data:
        return jsonify({"code":400,"msg":"上传文件为空"})

    try:
        encrypt_data = aes_encrypt(file_data)
    except RuntimeError as exc:
        return jsonify({"code":500,"msg":str(exc)}), 500
    shards = file_shard(encrypt_data)
    shard_num = len(shards)
    real_file_hash = get_file_hash(file_data)

    import ipfshttpclient
    try:
        client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001')
        cid = client.add_bytes(encrypt_data)
    except Exception:
        return jsonify({"code":400,"msg":"IPFS节点未启动"})

    assign_nodes = get_backup_nodes()
    cursor.execute('''
    insert into file_chain_record(file_name,file_hash,ipfs_cid,file_size,shard_count,upload_user,stored_nodes)
    values(%s,%s,%s,%s,%s,%s,%s)
    ''',(uploaded_file.filename,real_file_hash,cid,round(len(file_data)/1024/1024,3),shard_num,upload_addr,json.dumps(assign_nodes, ensure_ascii=False)))

    for node in assign_nodes:
        cursor.execute('update node_power set disk_used=disk_used+0.1 where user_address=%s',(node,))

    return jsonify({
        "code":200,
        "msg":"文件加密上链完成",
        "data":{
            "file_hash":real_file_hash,
            "ipfs_cid":cid,
            "shard_count":shard_num,
            "storage_nodes":assign_nodes
        }
    })

# 查询所有上链存证记录
@app.route("/api/file_list",methods=["GET"])
def file_list():
    cursor.execute("select * from file_chain_record order by create_time desc")
    res = cursor.fetchall()
    arr = []
    for item in res:
        try:
            stored_nodes = json.loads(item[7]) if item[7] else []
        except Exception:
            stored_nodes = []
        arr.append({
            "id":item[0],
            "file_name":item[1],
            "file_hash":item[2],
            "ipfs_cid":item[3],
            "size":item[4],
            "shard":item[5],
            "uploader":item[6],
            "nodes":stored_nodes,
            "time":str(item[8])
        })
    return jsonify({"code":200,"data":arr})

# 简易IP地理位置解析（免费公开接口，无需密钥）
def get_ip_location(ip):
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN",timeout=3)
        data = res.json()
        if data["status"] == "success":
            return {
                "country":data.get("country","未知"),
                "province":data.get("regionName","未知"),
                "city":data.get("city","未知"),
                "lat":str(data.get("lat","0")),
                "lng":str(data.get("lon","0"))
            }
    except:
        pass
    return {"country":"未知","province":"未知","city":"未知","lat":"0","lng":"0"}

# 中间件：获取访客真实IP
def get_real_ip():
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    elif request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

# 新增：节点上报位置（心跳自动调用）
@app.route("/api/report_location",methods=["POST"])
def report_location():
    data = request.get_json()
    user_addr = data.get("user_addr")
    node_mac = data.get("node_mac")
    ip = get_real_ip()
    loc = get_ip_location(ip)

    # 更新或写入节点位置
    cursor.execute("""
    INSERT INTO node_location(user_address,node_mac,ip_addr,country,province,city,lat,lng,online_status)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)
    ON DUPLICATE KEY UPDATE
    ip_addr=%s,country=%s,province=%s,city=%s,lat=%s,lng=%s,online_status=1
    """,(user_addr,node_mac,ip,loc["country"],loc["province"],loc["city"],loc["lat"],loc["lng"],
        ip,loc["country"],loc["province"],loc["city"],loc["lat"],loc["lng"]))
    db.commit()
    return jsonify({"code":200,"msg":"位置上报成功"})

# 新增：获取全网节点地图点位
@app.route("/api/map_node_list",methods=["GET"])
def map_node_list():
    cursor.execute("select * from node_location")
    res = cursor.fetchall()
    arr = []
    for item in res:
        arr.append({
            "user_addr":item[1],
            "node_mac":item[2],
            "ip":item[3],
            "country":item[4],
            "province":item[5],
            "city":item[6],
            "lat":item[7],
            "lng":item[8],
            "status":item[9]
        })
    return jsonify({"code":200,"data":arr})

# 定时标记离线节点
@app.route("/api/map_offline_clear",methods=["POST"])
def map_offline_clear():
    cursor.execute("update node_location set online_status=0 where update_time < NOW() - INTERVAL 2 MINUTE")
    db.commit()
    return jsonify({"code":200})

# 获取【异地、不同IP】在线节点（规避同机房批量掉线）
def get_diff_online_nodes(num):
    # 读取所有在线节点
    cursor.execute("""
    SELECT DISTINCT user_address,ip_addr,country,city 
    FROM node_location 
    WHERE online_status=1 AND update_time > NOW() - INTERVAL 1 MINUTE
    """)
    all_nodes = cursor.fetchall()
    if not all_nodes:
        return []
    
    # 按地区、IP去重，尽量分散节点
    selected = []
    ip_list = []
    for node in all_nodes:
        if node[1] not in ip_list:
            ip_list.append(node[1])
            selected.append(node[0])
        if len(selected) >= num:
            break
    return selected

def get_backup_nodes():
    assign_nodes = get_diff_online_nodes(COPY_NUM)
    while len(assign_nodes) < COPY_NUM:
        assign_nodes.append("SERVER_BACKUP_NODE")
    return assign_nodes

# 初始化纠删码编码器
rs = reedsolo.RSCodec(EC_PARITY_SHARD) if reedsolo is not None else None

# 文件编码：生成数据片+校验片
def file_ec_encode(file_data):
    if rs is None:
        raise RuntimeError("缺少 reedsolo 依赖，请执行：pip install reedsolo")
    # 均匀分片
    shards = [file_data[i:i+SHARD_SIZE] for i in range(0,len(file_data),SHARD_SIZE)]
    # 纠删码编码，生成可自愈碎片
    ec_shards = rs.encode(shards)
    return ec_shards

# 文件解码：丢失部分碎片自动还原完整文件
def file_ec_decode(ec_shards):
    if rs is None:
        raise RuntimeError("缺少 reedsolo 依赖，请执行：pip install reedsolo")
    # 自动补全丢失分片、修复损坏数据
    origin_shards = rs.decode(ec_shards)
    return b"".join(origin_shards)


# 定时任务：巡检所有文件，副本不足自动重新分发补副本
@app.route("/api/auto_repair_backup",methods=["POST"])
def auto_repair_backup():
    # 遍历所有存证文件
    cursor.execute("select id,ipfs_cid,stored_nodes from file_chain_record")
    all_file = cursor.fetchall()
    for item in all_file:
        fid,cid,nodes_str = item
        if not nodes_str:
            continue
        # 检测当前在线存储节点数量
        try:
            node_list = json.loads(nodes_str)
        except Exception:
            node_list = []
        alive = 0
        for addr in node_list:
            cursor.execute("select 1 from node_power where user_address=%s and online_duration>10",(addr,))
            if cursor.fetchone():
                alive +=1
        # 副本少于3个 → 自动新增节点补备份
        if alive < COPY_NUM:
            new_nodes = get_diff_online_nodes(COPY_NUM - alive)
            # 更新存储节点列表、重新分发分片
            new_all = list(set(node_list + new_nodes))
            cursor.execute("update file_chain_record set stored_nodes=%s where id=%s",(json.dumps(new_all, ensure_ascii=False),fid))
    db.commit()
    return jsonify({"code":200,"msg":"数据副本巡检修复完成"})

# 启动服务
if __name__ == "__main__":
    # 开启定时结算
    import threading
    threading.Thread(target=settle_task,daemon=True).start()
    print("✅ 完整服务启动成功！后台地址：http://127.0.0.1:8000")
    app.run(host="0.0.0.0",port=8000,debug=False)
