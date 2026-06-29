// 获取URL推广参数
function getUrlParam(name){
    let reg = new RegExp("(^|&)"+name+"=([^&]*)(&|$)");
    let r = window.location.search.substr(1).match(reg);
    if(r!=null)return unescape(r[2]); return "";
}

let invite = getUrlParam("invite");
document.getElementById("tip").innerText = invite ? "✅ 已绑定上级节点，启动即可产生收益" : "⚠️ 无上级推广";

// 下载链接携带参数，exe启动自动识别
document.getElementById("downloadBtn").onclick = function(){
    this.href = "node.exe";
    this.download = invite ? "node_invite_" + invite + ".exe" : "node.exe";
}

