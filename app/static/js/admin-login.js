const form = document.getElementById("adminLoginForm");
    const statusBox = document.getElementById("loginStatus");
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const token = document.getElementById("adminTokenInput").value.trim();
        statusBox.textContent = "正在登录...";
        try{
            const response = await fetch("/api/admin/login", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({token})
            });
            const payload = await response.json();
            if(!response.ok){ throw new Error(payload.msg || "登录失败"); }
            localStorage.setItem("admin_token", token);
            window.location.href = "/admin";
        }catch(error){
            localStorage.removeItem("admin_token");
            statusBox.textContent = error.message;
        }
    });
