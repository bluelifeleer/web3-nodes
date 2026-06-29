// 服务端接口地址（本地/公网部署自行修改）
        const API_URL = "http://127.0.0.1:8000";
        let selectFile = null;

        // 元素获取
        const fileBox = document.getElementById("fileBox");
        const fileInput = document.getElementById("fileInput");
        const uploadBtn = document.getElementById("uploadBtn");
        const progressBox = document.getElementById("progressBox");
        const progressInner = document.getElementById("progressInner");
        const progressText = document.getElementById("progressText");
        const resultBox = document.getElementById("resultBox");
        const visibilitySelect = document.getElementById("visibilitySelect");

        function getAdminToken() {
            let token = localStorage.getItem("admin_token") || "";
            if(!token) {
                token = prompt("请输入后台访问 Token") || "";
                if(token) localStorage.setItem("admin_token", token);
            }
            return token;
        }

        // 选择文件
        fileBox.onclick = () => fileInput.click();
        fileInput.onchange = (e) => {
            selectFile = e.target.files[0];
            if(selectFile) {
                fileBox.innerHTML = `<p>已选择文件：${selectFile.name}</p><p class="file-size-note">文件大小：${(selectFile.size / 1024 / 1024).toFixed(2)}MB</p>`;
                uploadBtn.disabled = false;
            }
        };

        // 拖拽上传
        fileBox.ondragover = (e) => e.preventDefault();
        fileBox.ondrop = (e) => {
            e.preventDefault();
            selectFile = e.dataTransfer.files[0];
            if(selectFile) {
                fileBox.innerHTML = `<p>已拖拽文件：${selectFile.name}</p><p class="file-size-note">文件大小：${(selectFile.size / 1024 / 1024).toFixed(2)}MB</p>`;
                uploadBtn.disabled = false;
            }
        };

        // 获取本地节点虚拟地址（适配客户端设备指纹，绑定算力）
        function getLocalNodeAddr() {
            // 优先读取本地节点缓存，无则临时生成
            let nodeAddr = localStorage.getItem("node_addr");
            if(!nodeAddr) {
                const randomStr = Math.random().toString(36).slice(2);
                nodeAddr = "TEMP_NODE_" + randomStr;
                localStorage.setItem("node_addr", nodeAddr);
            }
            return nodeAddr;
        }

        // 上传文件主逻辑
        uploadBtn.onclick = async () => {
            if(!selectFile) return;
            uploadBtn.disabled = true;
            progressBox.style.display = "block";
            resultBox.style.display = "none";

            // 构造表单数据
            const formData = new FormData();
            formData.append("file", selectFile);
            formData.append("user_addr", getLocalNodeAddr());
            formData.append("visibility", visibilitySelect.value);

            // 发送请求
            try {
                const res = await fetch(`${API_URL}/api/upload_file`, {
                    method: "POST",
                    headers: {
                        "X-Admin-Token": getAdminToken()
                    },
                    body: formData
                });

                // 模拟进度条
                let progress = 0;
                const progressTimer = setInterval(() => {
                    if(progress < 95) {
                        progress += 5;
                        progressInner.style.width = progress + "%";
                        progressText.innerText = progress + "%";
                    }
                }, 100);

                const data = await res.json();
                clearInterval(progressTimer);
                progressInner.style.width = "100%";
                progressText.innerText = "100%";

                // 渲染结果
                resultBox.style.display = "block";
                if(data.code === 200) {
                    document.getElementById("statusText").innerText = "✅ 加密分片上链成功";
                    document.getElementById("statusText").className = "success";
                    document.getElementById("fileName").innerText = selectFile.name;
                    document.getElementById("fileHash").innerText = data.data.file_hash;
                    document.getElementById("ipfsCid").innerText = data.data.ipfs_cid;
                    document.getElementById("shardNum").innerText = data.data.shard_count + " 片";
                    document.getElementById("nodeNum").innerText = data.data.storage_nodes.length + " 个";
                    document.getElementById("visibilityText").innerText = data.data.visibility === "private" ? "私有" : "公开";
                    document.getElementById("accessToken").innerText = data.data.access_token || "无";
                    const downloadUrl = `${API_URL}${data.data.download_url}`;
                    document.getElementById("downloadUrl").innerText = downloadUrl;
                    document.getElementById("downloadUrl").href = downloadUrl;
                } else {
                    document.getElementById("statusText").innerText = "❌ 上传失败：" + data.msg;
                    document.getElementById("statusText").className = "error";
                }
            } catch (err) {
                resultBox.style.display = "block";
                document.getElementById("statusText").innerText = "❌ 服务端连接失败，请检查节点服务是否启动";
                document.getElementById("statusText").className = "error";
            }

            uploadBtn.disabled = false;
        };

