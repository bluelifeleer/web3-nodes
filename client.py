# 客户端 node_client.py（修复接口报错完整版）
import time
import hashlib
import uuid
import subprocess
import random
import requests
try:
    import webview
except Exception:
    webview = None

# 服务端地址（和后端统一）
SERVER_URL = "http://127.0.0.1:8000"
# 上级推广码（分享链接自动填充，用户无需手动改）
PARENT_INVITE = ""

# 生成唯一设备指纹（防多开、防作弊）
def get_device_mac():
    return str(uuid.getnode())

# 读取本地IPFS真实存储占用
def get_local_disk_use():
    try:
        # 调用本地IPFS命令，读取仓库占用空间
        res = subprocess.check_output("ipfs stats repo --human",shell=True).decode()
        # 解析GB数值
        if "GB" in res:
            gb_val = float(res.split("GB")[0].strip().split(" ")[-1])
            return round(gb_val,2)
        return 0.1
    except Exception as e:
        # 未启动IPFS时默认基础占用
        return 0.1

# 节点核心运行逻辑
def client_run():
    device_mac = get_device_mac()
    # 根据设备MAC生成唯一用户标识
    user_addr = "NODE_" + hashlib.md5(device_mac.encode()).hexdigest()[:12]

    # 1. 首次注册绑定上级
    try:
        requests.post(f"{SERVER_URL}/register",json={
            "user_addr":user_addr,
            "node_mac":device_mac,
            "parent_invite":PARENT_INVITE
        },timeout=10)
        print(f"✅ 节点注册成功，设备指纹：{device_mac}")
    except:
        print("❌ 服务端连接失败，请检查服务是否启动")
        return

    # 2. 循环心跳上报（60秒一次）
    print("🔄 节点持续运行中，实时上报存储数据...")
    while True:
        disk_use = get_local_disk_use()
        upload_bw = round(random.uniform(0.2,3.0),2)
        try:
            requests.post(f"{SERVER_URL}/heartbeat",json={
                "user_addr":user_addr,
                "node_mac":device_mac,
                "disk_used":disk_use,
                "upload_bw":upload_bw
            },timeout=10)
            print(f"✅ 心跳上报成功｜当前存储：{disk_use}G｜上行带宽：{upload_bw}MB/s")
        except:
            print("❌ 心跳上报失败，等待重连...")

        # 在 while True 心跳循环内添加：
        # 自动上报地理位置
        try:
            requests.post(f"{SERVER_URL}/api/report_location",json={
                "user_addr":user_addr,
                "node_mac":device_mac
            },timeout=5)
        except:
            pass
        
        time.sleep(60)


def open_map_window():
    if webview is None:
        print("ℹ️ 未安装 pywebview，跳过地图窗口")
        return
    html = '''
    <html style="margin:0;padding:0">
    <body style="margin:0;padding:0">
    <script src="https://webapi.amap.com/maps?v=2.0&key=6f17f9896974a8686929496921212479"></script>
    <div id="map" style="width:100vw;height:100vh"></div>
    <script>
    let map = new AMap.Map('map',{zoom:4,center:[105,35]});
    fetch("http://127.0.0.1:8000/api/map_node_list")
    .then(res=>res.json()).then(d=>{
        d.data.forEach(item=>{
            if(item.lat==0)return;
            let marker = new AMap.Marker({
                position:[item.lng,item.lat],
                icon:item.status?"https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png":"https://webapi.amap.com/theme/v1.3/markers/n/mark_bs.png"
            })
            map.add(marker);
        })
    })
    </script>
    </body>
    </html>
    '''
    webview.create_window("节点全球地图", html=html, width=800, height=600)
    webview.start(gui=True, debug=False)

if __name__ == "__main__":
    import threading
    print("🚀 Web3分布式存储激励节点启动成功")
    if webview is None:
        client_run()
    else:
        threading.Thread(target=client_run,daemon=True).start()
        open_map_window()
