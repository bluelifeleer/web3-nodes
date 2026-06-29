    const token = localStorage.getItem("user_token") || "";
    const statusBox = document.getElementById("statusBox");
    function showStatus(message){ statusBox.textContent = message; }
    function authHeaders(extra){
        return Object.assign({"Authorization": `Bearer ${token}`}, extra || {});
    }
    function esc(value){
        return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
            "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
        }[ch]));
    }
    async function apiGet(url){
        const response = await fetch(url, {headers: authHeaders()});
        const payload = await response.json();
        if(!response.ok){ throw new Error(`${url}: ${payload.msg || response.statusText}`); }
        return payload;
    }
    async function apiPost(url, body){
        const response = await fetch(url, {
            method: "POST",
            headers: authHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify(body)
        });
        const payload = await response.json();
        if(!response.ok){ throw new Error(payload.msg || response.statusText); }
        return payload;
    }
    function renderTable(targetId, columns, rows){
        const target = document.getElementById(targetId);
        if(!rows || rows.length === 0){
            target.innerHTML = "暂无数据";
            return;
        }
        target.innerHTML = `<table><thead><tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr></thead><tbody>${
            rows.map((row) => `<tr>${columns.map((c) => `<td class="wrap">${c.html ? c.html(row) : esc(c.render ? c.render(row) : row[c.key])}</td>`).join("")}</tr>`).join("")
        }</tbody></table>`;
    }
    function defaultExtractCodeForFile(fileHash){
        const seed = String(fileHash || "").replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
        return (seed.slice(0, 6) || "FILE88").padEnd(6, "8");
    }
    let activeShareFileHash = "";
    function closeShareDialog(){
        document.getElementById("shareCreateModal").hidden = true;
    }
    function openShareDialog(fileHash, fileName){
        activeShareFileHash = fileHash || "";
        document.getElementById("shareFileHashInput").value = activeShareFileHash;
        document.getElementById("shareExtractCodeInput").value = defaultExtractCodeForFile(activeShareFileHash);
        document.getElementById("shareMaxDownloadsInput").value = "0";
        document.getElementById("shareExpiresAtInput").value = "";
        document.getElementById("shareModalFileName").textContent = fileName ? `文件：${fileName}` : "";
        document.getElementById("shareResultBox").textContent = "分享链接会在创建后显示在这里。";
        document.getElementById("shareCreateModal").hidden = false;
        document.getElementById("shareExtractCodeInput").focus();
    }
    async function submitShareDialog(){
        const fileHash = activeShareFileHash || document.getElementById("shareFileHashInput").value.trim();
        const extractCode = document.getElementById("shareExtractCodeInput").value.trim();
        const maxDownloads = Number(document.getElementById("shareMaxDownloadsInput").value || 0);
        const expiresAt = document.getElementById("shareExpiresAtInput").value.trim();
        if(!fileHash){
            document.getElementById("shareResultBox").textContent = "缺少文件 Hash，无法创建分享。";
            return;
        }
        showStatus("正在创建分享...");
        try{
            const payload = await apiPost(`/api/user/files/${encodeURIComponent(fileHash)}/shares`, {
                visibility: "public",
                extract_code: extractCode,
                max_downloads: Number.isFinite(maxDownloads) && maxDownloads > 0 ? maxDownloads : 0,
                expires_at: expiresAt,
                status: "active"
            });
            const data = payload.data || {};
            const sharePath = data.share_url_with_extract_code || data.share_url || `/s/${encodeURIComponent(data.share_code || "")}`;
            const shareUrl = new URL(sharePath, window.location.origin).toString();
            showStatus(`分享已创建\n${shareUrl}`);
            document.getElementById("shareResultBox").innerHTML = `分享已创建：<a href="${esc(sharePath)}" target="_blank" rel="noopener">${esc(shareUrl)}</a>`;
            refreshDashboard();
        }catch(error){
            showStatus(`分享创建失败\n${error.message}`);
            document.getElementById("shareResultBox").textContent = `分享创建失败：${error.message}`;
        }
    }
    function createShareForFile(fileHash, fileName){
        openShareDialog(fileHash, fileName || "");
    }
    async function refreshDashboard(){
        if(!token){
            showStatus("缺少 user_token，请先到登录页登录。");
            return;
        }
        showStatus("加载中...");
        try{
            const [me, files, sharesData, pointsData, earnings, withdrawals] = await Promise.all([
                apiGet("/api/auth/me"),
                apiGet("/api/user/files"),
                apiGet("/api/user/shares"),
                apiGet("/api/user/points"),
                apiGet("/api/user/earnings"),
                apiGet("/api/user/withdrawals")
            ]);
            const user = me.user || {};
            document.getElementById("accountBox").innerHTML = `用户：${esc(user.username)}<br>钱包：${esc(user.wallet_address || "未绑定")}<br>状态：${esc(user.status)}`;
            const earningData = earnings.data || {};
            document.getElementById("availableEarnings").textContent = earningData.available_earnings ?? 0;
            document.getElementById("earningsBox").innerHTML = `累计收益：${esc(earningData.total_earnings ?? 0)}<br>已提现：${esc(earningData.withdrawn_earnings ?? 0)}<br>冻结中：${esc(earningData.pending_withdrawals ?? 0)}`;
            document.getElementById("totalPoints").textContent = (pointsData.data || {}).total_points ?? 0;
            renderTable("pointsBox", [
                {label:"类型", key:"point_type"},
                {label:"数量", key:"amount"},
                {label:"来源", key:"source_type"},
                {label:"时间", key:"created_at"}
            ], (pointsData.data || {}).items || []);
            renderTable("filesBox", [
                {label:"文件名", key:"file_name"},
                {label:"哈希", key:"file_hash"},
                {label:"大小(MB)", key:"size"},
                {label:"权限", key:"visibility"},
                {label:"操作", html:(row) => `<div class="table-actions">${row.download_url ? `<a href="${esc(row.download_url)}" target="_blank" rel="noopener">下载</a>` : ""}<button type="button" class="share-file-button" data-file-hash="${esc(row.file_hash || "")}" data-file-name="${esc(row.file_name || "")}">创建分享</button></div>`}
            ], files.data || []);
            renderTable("sharesBox", [
                {label:"分享码", key:"share_code"},
                {label:"文件", key:"file_name"},
                {label:"链接", html:(row) => `<a href="/s/${esc(row.share_code || "")}" target="_blank" rel="noopener">/s/${esc(row.share_code || "")}</a>`},
                {label:"提取码", render:(row) => row.extract_code_required ? "需要" : "无"},
                {label:"下载", render:(row) => `${row.download_count || 0}/${row.max_downloads || 0}`}
            ], sharesData.data || []);
            renderTable("withdrawalsBox", [
                {label:"金额", key:"amount"},
                {label:"状态", key:"status"},
                {label:"钱包", key:"wallet_address"},
                {label:"时间", key:"created_at"}
            ], withdrawals.data || []);
            showStatus("加载完成。");
        }catch(error){
            showStatus(`加载失败\n${error.message}`);
        }
    }
    document.getElementById("refreshButton").addEventListener("click", refreshDashboard);
    document.getElementById("shareCloseButton").addEventListener("click", closeShareDialog);
    document.getElementById("shareCreateButton").addEventListener("click", submitShareDialog);
    document.getElementById("shareCreateModal").addEventListener("click", (event) => {
        if(event.target.id === "shareCreateModal"){ closeShareDialog(); }
    });
    document.addEventListener("click", (event) => {
        const button = event.target.closest(".share-file-button");
        if(button){ createShareForFile(button.dataset.fileHash || "", button.dataset.fileName || ""); }
    });
    document.getElementById("bindNonceButton").addEventListener("click", async () => {
        try{
            const payload = await apiPost("/api/wallet/nonce", {
                wallet_address: document.getElementById("bindWalletAddress").value.trim(),
                purpose: "bind"
            });
            document.getElementById("bindNonce").value = payload.nonce || "";
            document.getElementById("bindMessage").textContent = payload.message || "";
        }catch(error){ showStatus(`绑定 nonce 获取失败\n${error.message}`); }
    });
    document.getElementById("bindWalletButton").addEventListener("click", async () => {
        try{
            await apiPost("/api/wallet/bind", {
                wallet_address: document.getElementById("bindWalletAddress").value.trim(),
                nonce: document.getElementById("bindNonce").value.trim(),
                signature: document.getElementById("bindSignature").value.trim()
            });
            showStatus("钱包绑定成功。");
            refreshDashboard();
        }catch(error){ showStatus(`钱包绑定失败\n${error.message}`); }
    });
    document.getElementById("withdrawButton").addEventListener("click", async () => {
        try{
            await apiPost("/api/user/withdrawals", {
                amount: document.getElementById("withdrawAmount").value.trim()
            });
            showStatus("提现申请已提交。");
            refreshDashboard();
        }catch(error){ showStatus(`提现提交失败\n${error.message}`); }
    });
    refreshDashboard();
