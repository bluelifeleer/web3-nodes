const PUBLIC_SHARE_CONFIG = window.PUBLIC_SHARE_CONFIG || {};
const shareCode = PUBLIC_SHARE_CONFIG.shareCode || "";
    const statusBox = document.getElementById("statusBox");
    const shareMeta = document.getElementById("shareMeta");
    const extractCodeLabel = document.getElementById("extractCodeLabel");
    const inlineExtractCode = new URLSearchParams(window.location.search).get("extract_code") || "";
    function esc(value){
        return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
            "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
        }[ch]));
    }
    function showStatus(message){ statusBox.textContent = message; }
    async function loadShare(){
        try{
            const response = await fetch(`/api/share/${encodeURIComponent(shareCode)}`);
            const payload = await response.json();
            if(!response.ok){ throw new Error(payload.msg || response.statusText); }
            const data = payload.data || {};
            shareMeta.innerHTML = `文件：${esc(data.file_name || "")}<br>大小(MB)：${esc(data.file_size || 0)}<br>下载次数：${esc(data.download_count || 0)} / ${esc(data.max_downloads || 0)}<br>过期时间：${esc(data.expires_at || "不限")}`;
            extractCodeLabel.hidden = !data.extract_code_required;
            if(inlineExtractCode){
                document.getElementById("extractCodeInput").value = inlineExtractCode;
            }
            showStatus(data.extract_code_required ? (inlineExtractCode ? "提取码已从分享链接填入，可直接下载。" : "请输入提取码后下载。") : "分享可直接下载。");
        }catch(error){
            shareMeta.textContent = "分享不可用";
            showStatus(`加载失败\n${error.message}`);
        }
    }
    document.getElementById("downloadButton").addEventListener("click", async () => {
        const code = document.getElementById("extractCodeInput").value.trim();
        const query = code ? `?extract_code=${encodeURIComponent(code)}` : "";
        window.location.href = `/api/share/${encodeURIComponent(shareCode)}/download${query}`;
    });
    loadShare();
