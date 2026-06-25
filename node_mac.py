import sys
import os
import time
import hashlib
import uuid
import requests
import subprocess
try:
    import webview
except Exception:
    webview = None

# ========== 服务端地址（替换为你的公网IP/域名，本地测试保留默认） ==========
SERVER_URL = "http://127.0.0.1:8000"
# 推广参数自动注入，无需手动填写
PARENT_INVITE = ""

# 解析启动参数（下载页携带的invite推广码）
def get_invite_arg():
    for arg in sys.argv:
        if arg.startswith("invite="):
            return arg.replace("invite=", "")
    return ""

# 获取Mac设备唯一指纹（防多开、防作弊、一机一号永久绑定）
def get_device_id():
    # 适配Mac系统硬件唯一标识
    return str(uuid.getnode())

# 适配Mac读取本地IPFS存储算力
def get_ipfs_disk():
    try:
        # Mac原生IPFS命令适配
        res = subprocess.check_output("ipfs stats repo --human", shell=True).decode()
        if "GB" in res:
            return round(float(res.split("GB")[0].strip().split(" ")[-1]), 2)
        elif "MB" in res:
            return round(float(res.split("MB")[0].strip().split(" ")[-1]) / 1024, 2)
        return 0.2
    except Exception:
        # 未启动IPFS时默认基础算力，不影响程序运行
        return 0.2

# 核心节点运行逻辑
def main():
    global PARENT_INVITE
    # 读取下载页传入的上级推广码
    PARENT_INVITE = get_invite_arg()

    # 生成唯一设备标识+用户节点地址
    device_id = get_device_id()
    user_addr = "MAC_NODE" + hashlib.md5(device_id.encode()).hexdigest()[:10]

    # 首次启动自动注册、绑定上级
    try:
        requests.post(f"{SERVER_URL}/register", json={
            "user_addr": user_addr,
            "node_mac": device_id,
            "parent_invite": PARENT_INVITE
        }, timeout=8)
    except Exception:
        # 网络异常自动重试，不闪退
        pass

    # 永久循环心跳上报（60秒一次）
    while True:
        disk_usage = get_ipfs_disk()
        try:
            requests.post(f"{SERVER_URL}/heartbeat", json={
                "user_addr": user_addr,
                "node_mac": device_id,
                "disk_used": disk_usage,
                "upload_bw": round(0.25, 2)
            }, timeout=8)
        except Exception:
            pass

        # 在 while True 心跳循环内添加：
        # 自动上报地理位置
        try:
            requests.post(f"{SERVER_URL}/api/report_location",json={
                "user_addr":user_addr,
                "node_mac":device_id
            },timeout=5)
        except:
            pass
        # 休眠60秒，降低设备功耗
        time.sleep(60)

def open_map_window():
    if webview is None:
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
    if webview is None:
        main()
    else:
        threading.Thread(target=main,daemon=True).start()
        open_map_window()
