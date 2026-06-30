const form = document.getElementById("identityLookupForm");
const messageNode = document.getElementById("lookupMessage");
const resultNode = document.getElementById("lookupResult");
const textNode = document.getElementById("identityText");
const fileNode = document.getElementById("identityFile");
const clearButton = document.getElementById("clearLookupButton");

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#39;"
    }[char]));
}

function setMessage(text, isError = false) {
    messageNode.textContent = text || "";
    messageNode.className = "lookup-message" + (isError ? " error" : "");
}

function formatAmount(value) {
    if (value === null || value === undefined || value === "") return "0";
    return String(value);
}

function renderResult(data) {
    const node = data.node || {};
    const earnings = data.earnings || {};
    const withdrawals = Array.isArray(data.withdrawals) ? data.withdrawals : [];
    const rows = withdrawals.map((item) => `
        <tr>
            <td>${esc(item.id)}</td>
            <td>${esc(item.amount)}</td>
            <td>${esc(item.status)}</td>
            <td class="mono">${esc(item.wallet_address || item.withdrawal_account || "")}</td>
            <td>${esc(item.created_at || "")}</td>
        </tr>
    `).join("");
    resultNode.innerHTML = `
        <div class="summary-grid">
            <div class="summary-item"><span>节点地址</span><strong class="mono">${esc(node.user_addr || data.identity?.user_addr || "-")}</strong></div>
            <div class="summary-item"><span>设备标识</span><strong class="mono">${esc(node.node_mac || data.identity?.node_mac || "-")}</strong></div>
            <div class="summary-item"><span>在线状态</span><strong>${esc(node.online_status || "-")}</strong></div>
            <div class="summary-item"><span>存储目录</span><strong class="mono">${esc(node.storage_path || "-")}</strong></div>
            <div class="summary-item"><span>总容量</span><strong>${esc(formatAmount(node.storage_total_gb))} GB</strong></div>
            <div class="summary-item"><span>已用容量</span><strong>${esc(formatAmount(node.storage_used_gb))} GB</strong></div>
            <div class="summary-item"><span>累计收益</span><strong>${esc(formatAmount(earnings.total_earnings))}</strong></div>
            <div class="summary-item"><span>可提现</span><strong>${esc(formatAmount(earnings.available_earnings))}</strong></div>
        </div>
        <h2>最近提现</h2>
        <table class="lookup-table">
            <thead><tr><th>ID</th><th>金额</th><th>状态</th><th>账户</th><th>创建时间</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="5">暂无提现记录</td></tr>'}</tbody>
        </table>
    `;
}

async function submitLookup(event) {
    event.preventDefault();
    setMessage("正在查询节点标识...");
    const formData = new FormData();
    const file = fileNode.files && fileNode.files[0];
    const text = textNode.value.trim();
    if (file) {
        formData.append("identity_file", file);
    } else if (text) {
        formData.append("identity_text", text);
    } else {
        setMessage("请上传节点标识文件或粘贴 JSON 内容", true);
        return;
    }
    try {
        const response = await fetch("/api/node/identity/lookup", {
            method: "POST",
            body: formData
        });
        const payload = await response.json();
        if (!response.ok || payload.code !== 200) {
            setMessage(payload.msg || "节点标识查询失败", true);
            resultNode.innerHTML = '<div class="empty-state">未查询到节点</div>';
            return;
        }
        renderResult(payload.data || {});
        setMessage("节点标识查询完成");
    } catch (error) {
        setMessage(error.message || "节点标识查询失败", true);
    }
}

form.addEventListener("submit", submitLookup);
clearButton.addEventListener("click", () => {
    form.reset();
    setMessage("");
    resultNode.innerHTML = '<div class="empty-state">等待节点标识查询</div>';
});
