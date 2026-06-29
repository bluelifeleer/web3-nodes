const token = localStorage.getItem("user_token") || "";
    const notice = document.getElementById("loginNotice");
    const resultBox = document.getElementById("resultBox");
    const fileHashInput = document.getElementById("fileHashInput");
    const shareLinkBox = document.getElementById("shareLinkBox");
    let defaultExtractCodeTouched = false;
    function generateDefaultExtractCode(){
        const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
        let code = "";
        const cryptoObj = window.crypto || window.msCrypto;
        const values = new Uint32Array(6);
        if(cryptoObj && cryptoObj.getRandomValues){
            cryptoObj.getRandomValues(values);
        }else{
            for(let i = 0; i < values.length; i++){ values[i] = Math.floor(Math.random() * alphabet.length); }
        }
        for(let i = 0; i < values.length; i++){ code += alphabet[values[i] % alphabet.length]; }
        return code;
    }
    function ensureDefaultExtractCode(){
        const input = document.getElementById("extractCodeInput");
        if(!input.value.trim()){
            input.value = generateDefaultExtractCode();
            defaultExtractCodeTouched = false;
        }
    }
    function redirectToLogin(){
        const loginUrl = new URL("/user/login", window.location.origin);
        loginUrl.searchParams.set("next", window.location.pathname + window.location.search);
        window.location.href = loginUrl.toString();
    }
    function requireUserLogin(){
        if(!token){
            notice.hidden = false;
            resultBox.textContent = "缺少 user_token，请先登录。";
            redirectToLogin();
            return false;
        }
        return true;
    }
    requireUserLogin();
    function authHeaders(extra){
        return Object.assign({"Authorization": `Bearer ${token}`}, extra || {});
    }
    function toApiDatetime(value){
        return value ? value.replace("T", " ") + ":00" : "";
    }
    async function createShare(fileHash){
        const payload = {
            visibility: "public",
            extract_code: document.getElementById("extractCodeInput").value.trim(),
            expires_at: toApiDatetime(document.getElementById("expiresAtInput").value),
            max_downloads: document.getElementById("maxDownloadsInput").value || 0,
            status: "active"
        };
        const response = await fetch(`/api/user/files/${encodeURIComponent(fileHash)}/shares`, {
            method: "POST",
            headers: authHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if(!response.ok){
            throw new Error(data.msg || response.statusText);
        }
        const shareData = data.data || {};
        const sharePath = shareData.share_url_with_extract_code || shareData.share_url || `/s/${encodeURIComponent(shareData.share_code || "")}`;
        const publicUrl = new URL(sharePath, location.origin).toString();
        shareLinkBox.hidden = false;
        shareLinkBox.innerHTML = `分享链接：<a href="${sharePath}" target="_blank" rel="noopener">${publicUrl}</a>`;
        return publicUrl;
    }
    document.getElementById("extractCodeInput").addEventListener("input", () => {
        defaultExtractCodeTouched = true;
    });
    ensureDefaultExtractCode();
    document.getElementById("uploadForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if(!requireUserLogin()){ return; }
        ensureDefaultExtractCode();
        const file = document.getElementById("fileInput").files[0];
        const visibility = document.getElementById("visibilityInput").value;
        const body = new FormData();
        body.append("file", file);
        body.append("visibility", visibility);
        resultBox.textContent = "上传中...";
        try{
            const response = await fetch("/api/user/files", {
                method: "POST",
                headers: authHeaders(),
                body
            });
            const payload = await response.json();
            const data = payload.data || {};
            if(!response.ok){
                resultBox.textContent = `上传失败\n${payload.msg || response.statusText}`;
                return;
            }
            fileHashInput.value = data.file_hash || "";
            resultBox.textContent = `上传完成\nfile_hash: ${data.file_hash || ""}\n正在自动创建分享链接...`;
            try{
                const publicUrl = await createShare(data.file_hash || "");
                resultBox.textContent = `上传完成，分享已创建\nfile_hash: ${data.file_hash || ""}\n${publicUrl}`;
            }catch(shareError){
                resultBox.textContent = `上传完成\nfile_hash: ${data.file_hash || ""}\n自动创建分享失败：${shareError.message}\n你可以修改提取码后重新生成分享链接。`;
            }
        }catch(error){
            resultBox.textContent = `上传失败\n${error.message}`;
        }
    });
    document.getElementById("shareForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if(!requireUserLogin()){ return; }
        const fileHash = fileHashInput.value.trim();
        resultBox.textContent = "正在创建分享...";
        try{
            const publicUrl = await createShare(fileHash);
            resultBox.textContent = `分享已创建\n${publicUrl}`;
        }catch(error){
            resultBox.textContent = `分享创建失败\n${error.message}`;
        }
    });
