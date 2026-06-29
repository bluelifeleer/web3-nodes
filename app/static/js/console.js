function requireUserLogin(){
  if(!localStorage.getItem("user_token")){
    const loginUrl = new URL("/user/login", window.location.origin);
    loginUrl.searchParams.set("next", window.location.pathname + window.location.search);
    window.location.href = loginUrl.toString();
    return false;
  }
  return true;
}

function requireAdminLogin(){
  if(!localStorage.getItem("admin_token")){
    window.location.href = "/admin/login";
    return false;
  }
  return true;
}

async function loadUserWorkspace(){
  return fetch("/api/user/files", {
    headers: {"Authorization": `Bearer ${localStorage.getItem("user_token") || ""}`}
  });
}

async function loadAdminWorkspace(){
  return fetch("/api/node_list", {
    headers: {"X-Admin-Token": localStorage.getItem("admin_token") || ""}
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const shell = document.querySelector(".unified-console-shell");
  if(!shell){ return; }
  const role = shell.dataset.consoleRole;
  if(role === "admin"){ requireAdminLogin(); }
  if(role === "user"){ requireUserLogin(); }
});
