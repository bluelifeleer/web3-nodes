const statusBox = document.getElementById("statusBox");
    function showStatus(message){ statusBox.textContent = message; }
    function redirectAfterLogin(){
        const params = new URLSearchParams(window.location.search);
        const next = params.get("next") || "/user/dashboard";
        if(next.startsWith("/") && !next.startsWith("//")){
            return next;
        }
        return "/user/dashboard";
    }
    function switchAuthTab(nextTab){
        document.querySelectorAll("[data-auth-tab]").forEach((button) => {
            button.classList.toggle("active", button.dataset.authTab === nextTab);
        });
        document.querySelectorAll("[data-auth-panel]").forEach((panel) => {
            panel.classList.toggle("active", panel.dataset.authPanel === nextTab);
        });
    }
    document.querySelectorAll("[data-auth-tab]").forEach((button) => {
        button.addEventListener("click", () => switchAuthTab(button.dataset.authTab));
    });
    function openOtherLoginModal(method){
        document.getElementById("otherLoginModal").classList.add("active");
        document.getElementById("otherLoginModal").setAttribute("aria-hidden", "false");
        document.querySelectorAll("[data-login-modal]").forEach((panel) => {
            panel.style.display = panel.dataset.loginModal === method ? "block" : "none";
        });
    }
    function closeOtherLoginModal(){
        document.getElementById("otherLoginModal").classList.remove("active");
        document.getElementById("otherLoginModal").setAttribute("aria-hidden", "true");
    }
    document.getElementById("otherLoginButton").addEventListener("click", () => openOtherLoginModal("phone"));
    document.querySelectorAll("[data-other-login]").forEach((button) => {
        button.addEventListener("click", () => openOtherLoginModal(button.dataset.otherLogin));
    });
    document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", closeOtherLoginModal);
    });
    function saveSession(payload, shouldRedirect){
        const token = payload.token || payload.user_token || "";
        if(!token){ throw new Error(payload.msg || "接口未返回 user_token"); }
        localStorage.setItem("user_token", token);
        showStatus(`登录成功\nuser_token 已保存\n用户：${((payload.user || {}).username) || ""}`);
        if(shouldRedirect){
            window.location.href = redirectAfterLogin();
        }
    }
    async function postJson(url, body){
        const response = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body)
        });
        const payload = await response.json();
        if(!response.ok){ throw new Error(payload.msg || response.statusText); }
        return payload;
    }
    document.getElementById("registerForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try{
            const payload = await postJson("/api/auth/register", {
                username: document.getElementById("registerUsername").value.trim(),
                password: document.getElementById("registerPassword").value
            });
            saveSession(payload, true);
        }catch(error){ showStatus(`注册失败\n${error.message}`); }
    });
    document.getElementById("passwordLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try{
            const payload = await postJson("/api/auth/login", {
                username: document.getElementById("loginUsername").value.trim(),
                password: document.getElementById("loginPassword").value
            });
            saveSession(payload, true);
        }catch(error){ showStatus(`登录失败\n${error.message}`); }
    });
    document.getElementById("phoneSendCodeButton").addEventListener("click", () => {
        showStatus(`短信验证码已发送\n手机号：${document.getElementById("phoneLoginIdentifier").value.trim()}`);
    });
    document.getElementById("phoneLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        showStatus(`手机验证码登录已提交\n手机号：${document.getElementById("phoneLoginIdentifier").value.trim()}`);
    });
    document.getElementById("emailSendCodeButton").addEventListener("click", () => {
        showStatus(`邮箱验证码已发送\n邮箱：${document.getElementById("emailLoginIdentifier").value.trim()}`);
    });
    document.getElementById("emailLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        showStatus(`邮箱验证码登录已提交\n邮箱：${document.getElementById("emailLoginIdentifier").value.trim()}`);
    });
    document.getElementById("nonceButton").addEventListener("click", async () => {
        try{
            const payload = await postJson("/api/wallet/nonce", {
                wallet_address: document.getElementById("walletAddress").value.trim(),
                purpose: "login"
            });
            document.getElementById("walletNonce").value = payload.nonce || "";
            document.getElementById("walletMessage").textContent = payload.message || "";
            showStatus("nonce 已生成，请在钱包中签名后填入签名。");
        }catch(error){ showStatus(`nonce 获取失败\n${error.message}`); }
    });
    document.getElementById("walletLoginForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        try{
            const payload = await postJson("/api/wallet/login", {
                wallet_address: document.getElementById("walletAddress").value.trim(),
                nonce: document.getElementById("walletNonce").value.trim(),
                signature: document.getElementById("walletSignature").value.trim()
            });
            saveSession(payload, true);
        }catch(error){ showStatus(`钱包登录失败\n${error.message}`); }
    });
