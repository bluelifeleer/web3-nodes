const ADMIN_DASHBOARD_CONFIG = window.ADMIN_DASHBOARD_CONFIG || {};
const AMAP_WEB_KEY = ADMIN_DASHBOARD_CONFIG.amapWebKey || "";
const ADMIN_REFRESH_INTERVAL_MS = 10000;
let adminRefreshTimer = null;
const withdrawalNoteDrafts = {};

function getAdminToken(){
    return localStorage.getItem("admin_token") || "";
}

function requireAdminLogin(){
    if(!getAdminToken()){
        window.location.href = "/admin/login";
        return false;
    }
    return true;
}

function setAdminTokenStatus(text, isError){
    const status = document.getElementById("adminTokenStatus");
    if(status){
        status.innerText = text || "";
        status.style.color = isError ? "#c2410c" : "#166534";
    }
}

function setAdminAutoRefreshStatus(text){
    const status = document.getElementById("adminAutoRefreshStatus");
    if(status){ status.innerText = text || ""; }
}

function adminFetch(url, options){
    const token = getAdminToken();
    if(!token){
        setAdminTokenStatus("登录态失效，请重新登录", true);
        return Promise.resolve({
            status: 401,
            json: () => Promise.resolve({code:401,msg:"请先登录后台",data:[]})
        });
    }
    options = options || {};
    options.headers = Object.assign({}, options.headers || {}, {"X-Admin-Token": token});
    return fetch(url, options).then(res=>{
        if(res.status === 401){
            localStorage.removeItem("admin_token");
            setAdminTokenStatus("Token 无效，请重新输入", true);
            window.location.href = "/admin/login";
        }else{
            setAdminTokenStatus("Token 验证通过", false);
        }
        return res;
    });
}

// 修改分成比例
function setRatio(){
    let s = document.getElementById("selfRatio").value;
    let n = document.getElementById("nodeRatio").value;
    adminFetch("/api/set_ratio",{
        method:"POST",
        body:JSON.stringify({self_ratio:s,node_ratio:n}),
        headers:{"Content-Type":"application/json"}
    }).then(res=>res.json()).then(data=>{alert(data.msg);})
}

// 获取节点列表
function formatNodeStorage(value){
    const num = Number(value || 0);
    if(!Number.isFinite(num) || num <= 0){ return "0 B"; }
    if(num >= 1){ return `${num.toFixed(2)} GB`; }
    const mb = num * 1024;
    if(mb >= 1){ return `${mb.toFixed(2)} MB`; }
    return `${(mb * 1024).toFixed(2)} KB`;
}

function getNodes(){
    adminFetch("/api/node_list")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            const storageStatus = escHtml(item.storage_status || "unknown");
            const storageError = escHtml(item.storage_error || "");
            const isBadStatus = storageStatus !== "ok";
            html += `<tr>
                <td>${item.user_addr}</td>
                <td>${item.invite_code}</td>
                <td>${item.parent_code||"无"}</td>
                <td>${formatNodeStorage(item.disk_used)}</td>
                <td>${formatNodeStorage(item.storage_total_gb || 0)}</td>
                <td><span class="node-storage-usage">${formatNodeStorage(item.storage_used_gb || item.disk_used || 0)}</span></td>
                <td>${formatNodeStorage(item.storage_free_gb || 0)}</td>
                <td><span class="node-status-badge ${isBadStatus ? "bad" : ""}">${storageStatus}</span>${storageError ? "<br>" + storageError : ""}</td>
                <td>${item.online_min}</td>
                <td>${item.upload_bw}</td>
                <td>${item.online_status}</td>
                <td>${item.quality_score}</td>
            </tr>`
        })
        document.getElementById("nodeTable").innerHTML = html;
    })
}

// 获取收益记录
function getReward(){
    adminFetch("/api/reward_list")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.user_addr}</td>
                <td>${item.reward_type}</td>
                <td>${item.amount}</td>
                <td>${item.contrib}</td>
                <td>${item.source_user||""}</td>
                <td>${item.settle_date||""}</td>
                <td>${item.time}</td>
            </tr>`
        })
        document.getElementById("rewardTable").innerHTML = html;
    })
}

function getLeaderboard(){
    adminFetch("/api/leaderboard")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.rank}</td>
                <td>${item.user_addr}</td>
                <td>${item.quality_score}</td>
                <td>${item.online_status}</td>
                <td>${item.disk_used}</td>
                <td>${item.online_min}</td>
                <td>${item.upload_bw}</td>
            </tr>`
        })
        document.getElementById("leaderboardTable").innerHTML = html;
    })
}

function getDailyReward(){
    adminFetch("/api/reward_daily")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        data.data.forEach(item=>{
            html += `<tr>
                <td>${item.settle_date}</td>
                <td>${item.user_addr}</td>
                <td>${item.reward_type}</td>
                <td>${item.amount}</td>
                <td>${item.contrib}</td>
                <td>${item.count}</td>
            </tr>`
        })
        document.getElementById("dailyRewardTable").innerHTML = html;
    })
}

function renderInviteLines(nodes, depth){
    let lines = [];
    nodes.forEach(item=>{
        lines.push(`${"  ".repeat(depth)}- ${item.user_addr}｜码:${item.invite_code}｜${item.online_status}｜质量:${item.quality_score}`);
        lines = lines.concat(renderInviteLines(item.children || [], depth + 1));
    })
    return lines;
}

function getInviteTree(){
    adminFetch("/api/invite_tree")
    .then(res=>res.json())
    .then(data=>{
        document.getElementById("inviteTreeBox").innerText = renderInviteLines(data.data, 0).join("\n") || "暂无邀请关系";
    })
}

function getAdminWithdrawals(){
    const active = document.activeElement;
    if(active && active.dataset && active.dataset.withdrawalNote === "1"){
        withdrawalNoteDrafts[active.dataset.withdrawalId] = active.value;
        return;
    }
    adminFetch("/api/admin/withdrawals")
    .then(res=>res.json())
    .then(data=>{
        let html = "";
        (data.data || []).forEach(item=>{
            const owner = escHtml(item.user_id || item.node_address || "");
            const wallet = escHtml(item.wallet_address || "");
            const amount = escHtml(item.amount || 0);
            const status = escHtml(item.status || "");
            const noteId = String(item.id);
            const rawNote = Object.prototype.hasOwnProperty.call(withdrawalNoteDrafts, noteId)
                ? withdrawalNoteDrafts[noteId]
                : (item.admin_note || "");
            const note = escHtml(rawNote);
            const actions = item.status === "pending"
                ? `<button onclick="reviewWithdrawal(${item.id},'approved')">通过</button><button onclick="reviewWithdrawal(${item.id},'rejected')">驳回</button>`
                : item.status === "approved"
                    ? `<button onclick="reviewWithdrawal(${item.id},'paid')">标记已提现</button><button onclick="reviewWithdrawal(${item.id},'rejected')">驳回</button>`
                    : "已完成";
            html += `<tr><td>${item.id}</td><td>${owner}</td><td>${wallet}</td><td>${amount}</td><td>${status}</td><td><input id="withdrawalNote-${item.id}" data-withdrawal-note="1" data-withdrawal-id="${item.id}" value="${note}" placeholder="审核备注" style="width:120px" oninput="withdrawalNoteDrafts['${item.id}']=this.value"></td><td>${actions}</td></tr>`;
        });
        document.getElementById("withdrawalTable").innerHTML = html || '<tr><td colspan="7">暂无提现申请</td></tr>';
    });
}

function reviewWithdrawal(id,status){
    const noteInput = document.getElementById(`withdrawalNote-${id}`);
    const admin_note = noteInput ? noteInput.value : "";
    withdrawalNoteDrafts[String(id)] = admin_note;
    adminFetch(`/api/admin/withdrawals/${id}/review`, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({status,admin_note})
    }).then(res=>res.json()).then(data=>{
        delete withdrawalNoteDrafts[String(id)];
        alert(data.msg || "操作完成");
        getAdminWithdrawals();
    });
}

function storageAuditQuery(){
    const params = new URLSearchParams();
    const fields = [
        ["file_hash", "auditFileHashFilter"],
        ["node_address", "auditNodeFilter"],
        ["event_type", "auditEventFilter"],
        ["status", "auditStatusFilter"]
    ];
    fields.forEach(([key, id]) => {
        const value = (document.getElementById(id)?.value || "").trim();
        if(value){ params.set(key, value); }
    });
    return params;
}

function showStorageAuditDetail(index){
    const item = window.storageAuditRows && window.storageAuditRows[index];
    document.getElementById("storageAuditDetail").innerText = item ? JSON.stringify(item, null, 2) : "";
}

function getStorageAuditLogs(){
    const params = storageAuditQuery();
    adminFetch(`/api/admin/audit/storage?${params.toString()}`)
    .then(res=>res.json())
    .then(data=>{
        window.storageAuditRows = data.data || [];
        const html = window.storageAuditRows.map((item, index) => `<tr>
            <td>${escHtml(item.created_at || "")}</td>
            <td>${escHtml(item.event_type || "")}</td>
            <td style="font-size:12px">${escHtml((item.file_hash || "").substring(0, 18))}</td>
            <td>${item.chunk_index ?? ""}</td>
            <td>${escHtml(item.node_address || "")}</td>
            <td>${escHtml(item.status || "")}</td>
            <td><button onclick="showStorageAuditDetail(${index})">详情</button></td>
        </tr>`).join("");
        document.getElementById("storageAuditTable").innerHTML = html || '<tr><td colspan="7">暂无审计日志</td></tr>';
    });
}

function exportStorageAudit(format){
    const params = storageAuditQuery();
    params.set("format", format);
    window.open(`/api/admin/audit/storage/export?${params.toString()}&admin_token=${encodeURIComponent(getAdminToken())}`, "_blank");
}

function getFileList(){
    const q = encodeURIComponent(document.getElementById("fileSearch").value || "");
    adminFetch(`/api/file_list?q=${q}&page=1&page_size=50`)
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
                <td>${item.visibility === "private" ? "私有" : "公开"}</td>
                <td id="health-${item.file_hash}">待检查</td>
                <td>${item.time}</td>
                <td>
                    <a href="${item.download_url}" target="_blank">下载</a>
                    <button onclick="deleteFile('${item.file_hash}')">删除</button>
                </td>
            </tr>`
        })
        document.getElementById("fileTable").innerHTML = html;
    })
}

function deleteFile(fileHash){
    if(!confirm("确认删除这条文件记录？")) return;
    adminFetch("/api/file_delete",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({file_hash:fileHash})
    }).then(res=>res.json()).then(data=>{
        alert(data.msg);
        getFileList();
    })
}

function getFileHealth(){
    adminFetch("/api/file_health")
    .then(res=>res.json())
    .then(data=>{
        data.data.forEach(item=>{
            const cell = document.getElementById(`health-${item.file_hash}`);
            if(cell){
                cell.innerText = `${item.health.status} (${item.health.alive_count}/${item.health.stored_count})`;
            }
        })
    })
}

function getIpfsStatus(){
    adminFetch("/api/ipfs_status")
    .then(res=>res.json())
    .then(data=>{
        const s = data.data;
        document.getElementById("ipfsStatusText").innerText = s.online
            ? `IPFS在线｜Peer ${s.peer_id}｜Repo ${s.repo_size} bytes`
            : `IPFS离线｜${s.error}`;
    })
}

let map = null;
let markerList = [];

function escHtml(value){
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
        "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
    }[ch]));
}

function renderNodeDistribution(nodes, message){
    const fallback = document.getElementById("nodeDistributionFallback");
    if(!fallback){ return; }
    const safeNodes = nodes || [];
    const onlineCount = safeNodes.filter((item) => Number(item.status) === 1).length;
    const rows = safeNodes.slice(0, 30).map((item) => `
        <tr>
            <td>${escHtml(item.user_addr)}</td>
            <td>${escHtml([item.country, item.province, item.city].filter(Boolean).join(" / ") || "未知")}</td>
            <td>${Number(item.status) === 1 ? "在线" : "离线"}</td>
            <td>${escHtml(item.lat)}, ${escHtml(item.lng)}</td>
        </tr>
    `).join("");
    fallback.style.display = "block";
    fallback.innerHTML = `
        <strong>节点分布看板</strong>
        <p style="color:#64748b;margin:8px 0 12px;">${escHtml(message || "地图服务未启用，已切换为列表视图。")} 节点 ${safeNodes.length} 个，在线 ${onlineCount} 个。</p>
        <table>
            <thead><tr><th>节点地址</th><th>地区</th><th>状态</th><th>经纬度</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="4">暂无节点地理数据</td></tr>'}</tbody>
        </table>
    `;
}

function renderMapFallback(message){
    const mapBox = document.getElementById("map");
    if(mapBox){
        mapBox.innerHTML = `<div style="height:100%;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;background:#eef6f6;border:1px dashed #9ccfca;border-radius:8px;color:#155e63;">${escHtml(message)}</div>`;
    }
    renderNodeDistribution([], message);
}

function initMap(){
    if(!AMAP_WEB_KEY){
        renderMapFallback("未完整配置 AMAP_WEB_KEY / AMAP_SECURITY_JSCODE，已关闭高德地图加载以避免 INVALID_USER_KEY 或 INVALID_USER_SCODE。");
        if(getAdminToken()){ loadNodeMap(); }
        return;
    }
    if(typeof AMap === "undefined"){
        renderMapFallback("地图 SDK 加载失败，已切换为节点分布看板。");
        if(getAdminToken()){ loadNodeMap(); }
        return;
    }
    map = new AMap.Map('map', {
        zoom: 3,
        center: [105.27, 35.31]
    });
    map.addControl(new AMap.Scale());
    map.addControl(new AMap.ToolBar());
    if(getAdminToken()){ loadNodeMap(); }
}

// 加载节点点位
function loadNodeMap(){
    if(map){
        markerList.forEach(m=>map.remove(m));
    }
    markerList = [];

    adminFetch("/api/map_node_list")
    .then(res=>res.json())
    .then(data=>{
        const nodes = data.data || [];
        if(!map || typeof AMap === "undefined"){
            renderNodeDistribution(nodes, "地图未启用，当前展示节点地理分布列表。");
            return;
        }
        renderNodeDistribution(nodes, "地图已启用，下方同步保留节点地理分布列表。");
        nodes.forEach(item=>{
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

function refreshAdminData(){
    getNodes();
    getReward();
    getFileList();
    getIpfsStatus();
    getLeaderboard();
    getDailyReward();
    getInviteTree();
    getAdminWithdrawals();
    getStorageAuditLogs();
    if(map){ loadNodeMap(); }
    setAdminAutoRefreshStatus(`自动刷新中｜上次刷新 ${new Date().toLocaleTimeString()}`);
}

function startAdminAutoRefresh(){
    if(adminRefreshTimer){ clearInterval(adminRefreshTimer); }
    setAdminAutoRefreshStatus("自动刷新中");
    adminRefreshTimer = setInterval(refreshAdminData, ADMIN_REFRESH_INTERVAL_MS);
}

// 自动加载数据
document.addEventListener("DOMContentLoaded", () => {
    if(!requireAdminLogin()){ return; }
    setAdminTokenStatus("登录态已读取，正在加载后台数据", false);
    initMap();
    if(getAdminToken()){
        refreshAdminData();
        startAdminAutoRefresh();
    }
});
