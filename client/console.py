# Local node management console page template.
CLIENT_MANAGE_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>节点控制台</title></head>
<body>
  <style>
    :root {
      color-scheme: light;
      font-family: "Segoe UI", Arial, sans-serif;
      background: #f4f7fb;
      color: #14213d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #f7f9fc 0%, #edf3fb 100%);
      color: #14213d;
    }
    main {
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }
    .node-console-shell {
      max-width: 1180px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: 30px;
    }
    p.subhead {
      margin: 0 0 24px;
      color: #4f5d75;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }
    .node-hero-grid {
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr);
      align-items: stretch;
    }
    section {
      background: #ffffff;
      border: 1px solid #d8e2ef;
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(20, 33, 61, 0.06);
    }
    section.wide {
      grid-column: 1 / -1;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 18px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .node-kpi-board {
      grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
    }
    .stat {
      border: 1px solid #e3e9f3;
      border-radius: 8px;
      padding: 12px;
      background: #f9fbff;
      min-height: 86px;
    }
    .label {
      display: block;
      font-size: 12px;
      color: #6b7a90;
      margin-bottom: 8px;
    }
    .value {
      font-size: 22px;
      font-weight: 600;
      word-break: break-word;
    }
    .muted {
      color: #6b7a90;
      font-size: 13px;
    }
    .status-pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
      background: #d9f5e8;
      color: #166534;
    }
    .status-pill.offline {
      background: #fde2e1;
      color: #b42318;
    }
    .toolbar, form {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    input, select, button {
      min-height: 40px;
      border-radius: 8px;
      border: 1px solid #c7d3e3;
      padding: 0 12px;
      font: inherit;
    }
    input, select {
      flex: 1 1 180px;
      background: #fff;
    }
    button {
      cursor: pointer;
      background: #1769ff;
      color: #fff;
      border: 0;
      min-width: 120px;
      font-weight: 600;
    }
    button.secondary {
      background: #eef3fb;
      color: #17325c;
      border: 1px solid #c7d3e3;
    }
    button.danger {
      background: #d92d20;
    }
    button:disabled {
      opacity: 0.6;
      cursor: wait;
    }
    .list {
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
    }
    .list li {
      border-top: 1px solid #eef2f7;
      padding: 12px 0;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }
    .list li.local-shard-card {
      padding: 14px;
      margin-top: 10px;
      border: 1px solid #e3e9f3;
      border-radius: 8px;
      background: #f9fbff;
    }
    .list li:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .message {
      min-height: 22px;
      margin-top: 12px;
      font-size: 14px;
      color: #17325c;
    }
    .message.error {
      color: #b42318;
    }
    .mono {
      font-family: Consolas, "Courier New", monospace;
      word-break: break-all;
    }
    .usage-meter {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 8px;
      border-radius: 999px;
      background: #e8f8f2;
      color: #116454;
      font-weight: 700;
      font-size: 12px;
    }
    .auto-refresh-state {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-left: 10px;
      padding: 4px 8px;
      border-radius: 999px;
      background: #edf7ff;
      color: #24528f;
      font-size: 12px;
      font-weight: 700;
    }
    @media (max-width: 720px) {
      main { padding: 16px; }
      .node-hero-grid { grid-template-columns: 1fr; }
      h1 { font-size: 26px; }
      .list li {
        flex-direction: column;
        align-items: stretch;
      }
      button {
        width: 100%;
      }
    }
  </style>
  <main class="node-console-shell">
    <h1>节点控制台</h1>
    <p class="subhead">本地管理页只访问本机接口，不直接暴露服务端地址。<span id="autoRefreshState" class="auto-refresh-state">自动刷新待启动</span></p>

    <div class="grid node-hero-grid">
      <section>
        <h2>运行概览</h2>
        <div class="stats node-kpi-board">
          <div class="stat">
            <span class="label">运行状态</span>
            <div id="runningState" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">服务端连接</span>
            <div id="serverUrl" class="value muted mono">-</div>
          </div>
          <div class="stat">
            <span class="label">最后心跳</span>
            <div id="lastHeartbeat" class="value muted">-</div>
          </div>
          <div class="stat">
            <span class="label">最近状态</span>
            <div id="lastMessage" class="value muted">-</div>
          </div>
        </div>
      </section>

      <section>
        <h2>目录健康与容量</h2>
        <div class="stats node-kpi-board">
          <div class="stat">
            <span class="label">目录状态</span>
            <div id="storageState" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">总容量</span>
            <div id="storageTotal" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">已使用</span>
            <div id="storageUsed" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">可用容量</span>
            <div id="storageFree" class="value">-</div>
          </div>
        </div>
        <div class="muted mono" id="storagePath">-</div>
      </section>

      <section class="wide">
        <h2>存储目录管理</h2>
        <form id="storageForm">
          <input id="storageDirInput" name="storage_dir" placeholder="输入新的本地存储目录，例如 D:\\web3-node-data" />
          <input id="storageQuotaInput" name="storage_quota_gb" inputmode="decimal" placeholder="目录可用容量 GB，必填" />
          <button type="submit">添加目录 / 更新目录</button>
          <button class="secondary" id="refreshButton" type="button">重新检测</button>
        </form>
        <ul id="storageDirectoryList" class="list">
          <li><span class="muted">暂无目录</span></li>
        </ul>
        <div id="storageMessage" class="message"></div>
      </section>

      <section>
        <h2>收益概览</h2>
        <div class="stats">
          <div class="stat">
            <span class="label">累计收益</span>
            <div id="totalEarnings" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">已提现</span>
            <div id="withdrawnAmount" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">审核中</span>
            <div id="pendingAmount" class="value">-</div>
          </div>
          <div class="stat">
            <span class="label">可提现</span>
            <div id="availableAmount" class="value">-</div>
          </div>
        </div>
        <div id="earningsMessage" class="message"></div>
      </section>

      <section>
        <h2>提交提现</h2>
        <form id="withdrawalForm">
          <input id="withdrawalAmount" name="amount" placeholder="提现金额" />
          <input id="walletAddress" name="wallet_address" placeholder="钱包地址" />
          <select id="withdrawalChannel" name="withdrawal_channel">
            <option value="wallet">wallet</option>
            <option value="bank">bank</option>
            <option value="alipay">alipay</option>
          </select>
          <input id="withdrawalAccount" name="withdrawal_account" placeholder="提现账号，默认等于钱包地址" />
          <button type="submit">提交提现</button>
        </form>
        <div id="withdrawalMessage" class="message"></div>
      </section>

      <section class="wide">
        <h2>提现记录</h2>
        <ul id="withdrawalList" class="list">
          <li><span class="muted">加载中...</span></li>
        </ul>
      </section>

      <section class="wide">
        <h2>本机已存文件 <span id="localShardUsage" class="usage-meter">0 B</span></h2>
        <ul id="localShardList" class="list">
          <li><span class="muted">暂无本机分片</span></li>
        </ul>
      </section>

      <section class="wide">
        <h2>控制操作</h2>
        <div class="toolbar">
          <button class="danger" id="stopButton" type="button">停止节点</button>
          <button class="secondary" id="restartButton" type="button">重启节点</button>
          <span id="controlState" class="status-pill">待加载</span>
        </div>
        <div id="controlMessage" class="message"></div>
      </section>
    </div>
  </main>
  <script>
    const CSRF_TOKEN = "__CSRF_TOKEN__";
    const CLIENT_CONSOLE_REFRESH_INTERVAL_MS = 5000;
    let clientConsoleRefreshTimer = null;
    const formatAmount = (value) => {
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    };
    const formatBytes = (bytes) => {
      const value = Number(bytes || 0);
      if (!Number.isFinite(value) || value <= 0) return "0 B";
      if (value >= 1024 * 1024 * 1024) return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
      if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB`;
      if (value >= 1024) return `${(value / 1024).toFixed(2)} KB`;
      return `${Math.round(value)} B`;
    };
    const formatStorageDisplay = (item, key = "storage_used_gb") => {
      if (item && item.storage_used_display) return item.storage_used_display;
      if (item && item.storage_used_bytes !== undefined) return formatBytes(item.storage_used_bytes);
      return formatAmount(item ? item[key] : "") + " GB";
    };
    const setMessage = (id, text, isError = false) => {
      const node = document.getElementById(id);
      node.textContent = text || "";
      node.className = "message" + (isError ? " error" : "");
    };
    const api = async (path, options = {}) => {
      const opts = {...options};
      if (opts.method && opts.method.toUpperCase() !== "GET") {
        opts.headers = {...(opts.headers || {}), "Content-Type": "application/json", "X-CSRF-Token": CSRF_TOKEN};
        if (!opts.body) opts.body = "{}";
      }
      try {
        const res = await fetch(path, opts);
        const payload = await res.json().catch(() => ({ok:false, error:"响应解析失败"}));
        if (!res.ok && payload && payload.ok === undefined) payload.ok = false;
        return payload;
      } catch (error) {
        return {ok:false, error:error.message || "请求失败"};
      }
    };
    const applyStatus = (payload) => {
      if (!payload || !payload.ok) {
        setMessage("controlMessage", payload && payload.error ? payload.error : "状态加载失败", true);
        return;
      }
      const data = payload.data || {};
      const storage = data.storage || {};
      const isRunning = !!data.running;
      const heartbeatOk = !!data.heartbeat_ok;
      document.getElementById("runningState").textContent = isRunning ? "运行中" : "已停止";
      document.getElementById("serverUrl").textContent = data.server_configured ? (heartbeatOk ? "连接正常" : "等待心跳") : "-";
      document.getElementById("lastHeartbeat").textContent = data.last_heartbeat || "-";
      document.getElementById("lastMessage").textContent = data.last_notice || data.last_error || "-";
      document.getElementById("storageState").textContent = storage.storage_status || "-";
      document.getElementById("storageTotal").textContent = formatAmount(storage.storage_total_gb) + " GB";
      document.getElementById("storageUsed").textContent = formatStorageDisplay(storage);
      document.getElementById("storageFree").textContent = formatAmount(storage.storage_free_gb) + " GB";
      document.getElementById("storagePath").textContent = storage.storage_path || data.storage_dir || "-";
      document.getElementById("storageDirInput").value = data.storage_dir || "";
      document.getElementById("storageQuotaInput").value = "";
      renderStorageDirectories(storage.storage_directories || data.storage_dirs || []);
      renderLocalShards(data.stored_files || []);
      const pill = document.getElementById("controlState");
      pill.textContent = isRunning ? (heartbeatOk ? "运行中" : "重连中") : "已停止";
      pill.className = "status-pill" + (isRunning ? "" : " offline");
      document.getElementById("stopButton").disabled = !isRunning;
    };
    const renderStorageDirectories = (directories) => {
      const list = document.getElementById("storageDirectoryList");
      list.innerHTML = "";
      const rows = Array.isArray(directories) ? directories : [];
      if (!rows.length) {
        list.innerHTML = '<li><span class="muted">暂无目录</span></li>';
        return;
      }
      for (const item of rows) {
        const li = document.createElement("li");
        const left = document.createElement("div");
        const path = document.createElement("strong");
        path.className = "mono";
        path.textContent = item.storage_dir || item.storage_path || "-";
        const meta = document.createElement("div");
        meta.className = "muted";
        meta.textContent = `额度 ${formatAmount(item.storage_quota_gb)} GB / 已用 ${formatStorageDisplay(item)} / 可用 ${formatAmount(item.storage_available_gb || item.storage_free_gb)} GB`;
        left.appendChild(path);
        left.appendChild(meta);
        const right = document.createElement("div");
        right.textContent = item.storage_status || "-";
        li.appendChild(left);
        li.appendChild(right);
        list.appendChild(li);
      }
    };
    const renderLocalShards = (files) => {
      const list = document.getElementById("localShardList");
      const usage = document.getElementById("localShardUsage");
      list.innerHTML = "";
      const rows = Array.isArray(files) ? files : [];
      const totalBytes = rows.reduce((sum, item) => sum + Number(item.storage_used_bytes || 0), 0);
      usage.textContent = rows.length ? `${rows.length} 个文件 / ${formatBytes(totalBytes)}` : "0 B";
      if (!rows.length) {
        list.innerHTML = '<li><span class="muted">暂无本机分片</span></li>';
        return;
      }
      for (const item of rows) {
        const li = document.createElement("li");
        li.className = "local-shard-card";
        const left = document.createElement("div");
        const hash = document.createElement("strong");
        hash.className = "mono";
        hash.textContent = item.file_hash || "-";
        const meta = document.createElement("div");
        meta.className = "muted";
        meta.textContent = `分片 ${formatAmount(item.chunk_count)} / ${formatAmount(item.chunk_total)} ｜ ${item.storage_used_display || formatBytes(item.storage_used_bytes)} ｜ ${item.updated_at || ""}`;
        left.appendChild(hash);
        left.appendChild(meta);
        const right = document.createElement("div");
        right.className = "muted mono";
        right.textContent = item.storage_dir || "";
        li.appendChild(left);
        li.appendChild(right);
        list.appendChild(li);
      }
    };
    const applyEarnings = (payload) => {
      if (!payload || !payload.ok) {
        setMessage("earningsMessage", payload && payload.error ? payload.error : "收益加载失败", true);
        return;
      }
      const data = payload.data || {};
      document.getElementById("totalEarnings").textContent = formatAmount(data.total_amount || data.total_earnings || data.total_income || "0");
      document.getElementById("withdrawnAmount").textContent = formatAmount(data.withdrawn_amount || data.withdrawn_earnings || "0");
      document.getElementById("pendingAmount").textContent = formatAmount(data.pending_amount || data.pending_withdrawals || "0");
      document.getElementById("availableAmount").textContent = formatAmount(data.available_amount || data.available_earnings || "0");
      setMessage("earningsMessage", payload.message || "收益数据已更新");
    };
    const applyWithdrawals = (payload) => {
      const list = document.getElementById("withdrawalList");
      list.innerHTML = "";
      if (!payload || !payload.ok) {
        setMessage("withdrawalMessage", payload && payload.error ? payload.error : "提现记录加载失败", true);
        list.innerHTML = '<li><span class="muted">暂时无法读取提现记录</span></li>';
        return;
      }
      const rows = Array.isArray(payload.data) ? payload.data : (payload.data && payload.data.items) || [];
      if (!rows.length) {
        list.innerHTML = '<li><span class="muted">暂无提现记录</span></li>';
      } else {
        for (const item of rows) {
          const li = document.createElement("li");
          const left = document.createElement("div");
          const amount = document.createElement("strong");
          amount.textContent = formatAmount(item.amount);
          const wallet = document.createElement("div");
          wallet.className = "muted mono";
          wallet.textContent = item.wallet_address || item.withdrawal_account || "-";
          left.appendChild(amount);
          left.appendChild(wallet);
          const right = document.createElement("div");
          const status = document.createElement("div");
          status.textContent = item.status || "-";
          const created = document.createElement("div");
          created.className = "muted";
          created.textContent = item.created_at || item.created_time || "";
          right.appendChild(status);
          right.appendChild(created);
          li.appendChild(left);
          li.appendChild(right);
          list.appendChild(li);
        }
      }
      setMessage("withdrawalMessage", payload.message || "提现记录已更新");
    };
    async function refreshStatus() {
      applyStatus(await api("/api/status"));
    }
    async function refreshEarnings() {
      applyEarnings(await api("/api/earnings"));
    }
    async function refreshWithdrawals() {
      applyWithdrawals(await api("/api/withdrawals"));
    }
    async function refreshAll(){
      await Promise.all([refreshStatus(), refreshEarnings(), refreshWithdrawals()]);
      const node = document.getElementById("autoRefreshState");
      if (node) node.textContent = `自动刷新中｜${new Date().toLocaleTimeString()}`;
    }
    function startClientConsoleAutoRefresh(){
      if (clientConsoleRefreshTimer) clearInterval(clientConsoleRefreshTimer);
      clientConsoleRefreshTimer = setInterval(refreshAll, CLIENT_CONSOLE_REFRESH_INTERVAL_MS);
      const node = document.getElementById("autoRefreshState");
      if (node) node.textContent = "自动刷新中";
    }
    function stopClientConsoleAutoRefresh(){
      if (clientConsoleRefreshTimer) clearInterval(clientConsoleRefreshTimer);
      clientConsoleRefreshTimer = null;
      const node = document.getElementById("autoRefreshState");
      if (node) node.textContent = "自动刷新已暂停";
    }
    async function updateStorage(event){
      event.preventDefault();
      const storageDir = document.getElementById("storageDirInput").value.trim();
      const storageQuota = document.getElementById("storageQuotaInput").value.trim();
      const payload = await api("/api/storage", {method:"POST", body: JSON.stringify({storage_dir: storageDir, storage_quota_gb: storageQuota})});
      if (payload.ok) {
        applyStatus(payload);
        setMessage("storageMessage", "存储目录已更新并重新检测");
      } else {
        setMessage("storageMessage", payload.error || "存储目录更新失败", true);
      }
    }
    async function recheckStorage(){
      const payload = await api("/api/refresh", {method:"POST", body:"{}"});
      if (payload.ok) {
        applyStatus(payload);
        setMessage("storageMessage", "已重新检测本地目录");
      } else {
        setMessage("storageMessage", payload.error || "重新检测失败", true);
      }
    }
    async function submitWithdrawal(event){
      event.preventDefault();
      const walletAddress = document.getElementById("walletAddress").value.trim();
      const channel = document.getElementById("withdrawalChannel").value.trim() || "wallet";
      const accountInput = document.getElementById("withdrawalAccount").value.trim();
      const payload = await api("/api/withdrawals", {
        method:"POST",
        body: JSON.stringify({
          amount: document.getElementById("withdrawalAmount").value.trim(),
          wallet_address: walletAddress,
          withdrawal_channel: channel,
          withdrawal_account: accountInput || walletAddress
        })
      });
      if (payload.ok) {
        setMessage("withdrawalMessage", payload.message || "提现申请已提交");
        await Promise.all([refreshEarnings(), refreshWithdrawals()]);
      } else {
        setMessage("withdrawalMessage", payload.error || "提现申请失败", true);
      }
    }
    async function stopNode(){
      if (!confirm("确认停止节点？")) return;
      const payload = await api("/api/control/stop", {method:"POST", body:"{}"});
      if (payload.ok) {
        setMessage("controlMessage", payload.message || "节点停止请求已提交");
        applyStatus(payload);
      } else {
        setMessage("controlMessage", payload.error || "停止节点失败", true);
      }
    }
    async function restartNode(){
      if (!confirm("确认重启节点？")) return;
      const payload = await api("/api/control/restart", {method:"POST", body:"{}"});
      setMessage("controlMessage", payload.message || payload.error || "重启请求已处理", !payload.ok);
      if (payload.data) applyStatus(payload);
    }
    window.addEventListener("load", () => {
      document.getElementById("storageForm").addEventListener("submit", updateStorage);
      document.getElementById("refreshButton").addEventListener("click", recheckStorage);
      document.getElementById("withdrawalForm").addEventListener("submit", submitWithdrawal);
      document.getElementById("stopButton").addEventListener("click", stopNode);
      document.getElementById("restartButton").addEventListener("click", restartNode);
      refreshAll();
      startClientConsoleAutoRefresh();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stopClientConsoleAutoRefresh();
      } else {
        refreshAll();
        startClientConsoleAutoRefresh();
      }
    });
  </script>
</body>
</html>
"""



def render_client_console_html(csrf_token):
    return CLIENT_MANAGE_HTML.replace("__CSRF_TOKEN__", csrf_token)
