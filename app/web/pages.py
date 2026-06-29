from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"

COMMERCIAL_PAGE_CSS = '''
        :root{--ink:#172033;--muted:#64748b;--line:#dbe6ef;--surface:#fff;--soft:#f6f9fc;--brand:#0f766e;--brand-2:#14b8a6;--accent:#f0b429;--hot:#ff6b6b;}
        *{box-sizing:border-box;}
        body.commercial-page{margin:0;background:
            radial-gradient(circle at 14% 8%,rgba(20,184,166,.18),transparent 28%),
            radial-gradient(circle at 84% 2%,rgba(240,180,41,.15),transparent 24%),
            linear-gradient(180deg,#f7fbfc 0%,#edf4f7 100%);
            color:var(--ink);font-family:Arial,"Microsoft YaHei",sans-serif;}
        a{text-decoration:none;color:inherit;}
        .page-shell{width:min(1180px,calc(100vw - 32px));margin:0 auto;padding:24px 0 42px;}
        .modern-nav{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px;}
        .brand-lockup{display:flex;align-items:center;gap:12px;font-weight:800;color:#0f3440;}
        .brand-mark{width:34px;height:34px;border-radius:8px;background:linear-gradient(135deg,#0b4f56,var(--brand-2) 58%,var(--accent));box-shadow:0 14px 30px rgba(20,184,166,.30);}
        .nav-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:#33515c;}
        .nav-actions a{position:relative;overflow:hidden;padding:9px 13px;border:1px solid rgba(15,118,110,.18);border-radius:7px;background:rgba(255,255,255,.72);box-shadow:0 10px 26px rgba(15,23,42,.06);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;}
        .nav-actions a:hover{transform:translateY(-2px);border-color:rgba(20,184,166,.46);box-shadow:0 18px 34px rgba(20,184,166,.16);}
        .page-hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;align-items:end;margin:10px 0 20px;}
        .page-kicker{display:inline-flex;margin-bottom:10px;padding:7px 10px;border-radius:999px;background:linear-gradient(135deg,#e8f8f2,#fff7df);color:#116454;font-size:13px;font-weight:700;box-shadow:inset 0 0 0 1px rgba(20,184,166,.16);}
        .page-hero h1{margin:0;font-size:34px;line-height:1.14;letter-spacing:0;color:#102a36;}
        .page-hero p{margin:10px 0 0;color:var(--muted);line-height:1.7;max-width:720px;}
        .commercial-card,.box,.panel,main.auth-card{background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(248,252,252,.92));border:1px solid rgba(148,163,184,.30);border-radius:8px;box-shadow:0 18px 42px rgba(15,23,42,.08),inset 0 1px 0 rgba(255,255,255,.72);}
        .commercial-card.hover-lift,.hover-lift{transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;}
        .commercial-card.hover-lift:hover,.hover-lift:hover{transform:translateY(-3px);border-color:rgba(20,184,166,.36);box-shadow:0 24px 52px rgba(15,23,42,.12);}
        .box,.panel,main.auth-card{padding:18px;}
        .commercial-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;}
        .premium-button,.primary-action,body.commercial-page button,body.commercial-page .btn{position:relative!important;isolation:isolate;overflow:hidden!important;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:42px;padding:10px 17px!important;background:linear-gradient(135deg,#0f766e,#14b8a6 48%,#f0b429)!important;color:#ffffff!important;border:1px solid rgba(255,255,255,.28)!important;border-radius:8px!important;box-shadow:0 16px 34px rgba(20,184,166,.24),0 4px 12px rgba(15,118,110,.20),inset 0 1px 0 rgba(255,255,255,.38)!important;cursor:pointer;font-weight:800!important;letter-spacing:0;transition:transform .18s ease,box-shadow .18s ease,filter .18s ease!important;}
        .premium-button::before,.primary-action::before,body.commercial-page button::before,body.commercial-page .btn::before{content:"";position:absolute;inset:0;background:linear-gradient(120deg,transparent 0%,rgba(255,255,255,.34) 45%,transparent 62%);transform:translateX(-120%);transition:transform .55s ease;z-index:-1;}
        .premium-button:hover,.primary-action:hover,body.commercial-page button:hover,body.commercial-page .btn:hover{transform:translateY(-2px)!important;filter:saturate(1.08);box-shadow:0 22px 42px rgba(20,184,166,.30),0 8px 18px rgba(240,180,41,.18),inset 0 1px 0 rgba(255,255,255,.45)!important;}
        .premium-button:hover::before,.primary-action:hover::before,body.commercial-page button:hover::before,body.commercial-page .btn:hover::before{transform:translateX(115%);}
        .button-shine{position:absolute;inset:1px;border-radius:7px;background:linear-gradient(180deg,rgba(255,255,255,.28),transparent 42%);pointer-events:none;}
        .secondary-action,body.commercial-page button.secondary,body.commercial-page .btn.secondary{background:linear-gradient(135deg,rgba(255,255,255,.96),#eefbf8)!important;color:#155e63!important;border:1px solid rgba(20,184,166,.34)!important;box-shadow:0 14px 30px rgba(15,23,42,.08),inset 0 1px 0 rgba(255,255,255,.85)!important;}
        input,select{background:#fff;border:1px solid #cbd5e1;border-radius:7px;color:#172033;}
        table{background:white;border-radius:8px;overflow:hidden;}
        th{background:#edf7f6!important;color:#183b44;}
        .status,.notice,.linkbox,pre{border-radius:8px;}
        @media (max-width:800px){.modern-nav,.page-hero{align-items:flex-start;flex-direction:column;display:flex;}.nav-actions{width:100%;}.nav-actions a{flex:1;text-align:center;}.page-hero h1{font-size:28px;}}
'''

CONSOLE_SHELL_CSS = '''
        .unified-console-shell{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh;background:#eef4f7;}
        .console-sidebar{position:sticky;top:0;height:100vh;padding:18px;background:#102a36;color:#e8f8f2;overflow:auto;}
        .console-brand{display:flex;align-items:center;gap:10px;font-weight:900;margin-bottom:22px;}
        .console-brand-mark{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#14b8a6,#f0b429);}
        .console-role-label{display:inline-flex;margin-bottom:14px;padding:6px 9px;border-radius:999px;background:rgba(20,184,166,.18);color:#bff7ed;font-size:12px;font-weight:800;}
        .console-sidebar nav{display:grid;gap:8px;}
        .console-sidebar a{display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:8px;color:#d9f8f3;border:1px solid transparent;}
        .console-sidebar a:hover{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.12);}
        .console-sidebar [data-permission="admin"]{box-shadow:inset 3px 0 0 rgba(240,180,41,.9);}
        .console-sidebar [data-permission="user"]{box-shadow:inset 3px 0 0 rgba(20,184,166,.9);}
        .console-main{min-width:0;padding:0;}
        .console-topbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px;padding:12px 14px;border:1px solid rgba(148,163,184,.26);border-radius:8px;background:rgba(255,255,255,.76);}
        .console-permission-note{color:#64748b;font-size:13px;}
        @media (max-width:900px){.unified-console-shell{grid-template-columns:1fr;}.console-sidebar{position:relative;height:auto;}.console-sidebar nav{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));}.console-main{padding:0;}}
'''

CONSOLE_SIDEBAR_HTML = '''
        <aside class="console-sidebar">
            <div class="console-brand"><span class="console-brand-mark"></span><span>Web3 Nodes 管理台</span></div>
            <span class="console-role-label">统一权限入口</span>
            <nav>
                <a data-permission="user" href="/user/dashboard">用户工作台</a>
                <a data-permission="user" href="/user/upload">上传文件</a>
                <a data-permission="user" href="/user/dashboard#sharesBox">我的分享</a>
                <a data-permission="user" href="/user/dashboard#withdrawalsBox">收益提现</a>
                <a data-permission="admin" href="/admin">管理员</a>
                <a data-permission="admin" href="/admin#nodeTable">节点管理</a>
                <a data-permission="admin" href="/admin#storageAuditTable">审计日志</a>
                <a data-permission="admin" href="/admin#fileTable">文件存证</a>
            </nav>
        </aside>
'''

MANAGEMENT_CONSOLE_TEMPLATE = "management_console.html"

HOME_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Web3 节点激励与文件分享系统</title>
    <style>
''' + COMMERCIAL_PAGE_CSS + CONSOLE_SHELL_CSS + '''
        *{box-sizing:border-box;}
        body{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f4f7fb;color:#172033;}
        a{text-decoration:none;color:inherit;}
        .hero{min-height:90vh;display:grid;align-items:center;background:
            linear-gradient(120deg,rgba(7,19,42,.94),rgba(13,70,83,.86),rgba(21,91,70,.78)),
            url("https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1800&q=80") center/cover;color:white;}
        .wrap{width:min(1180px,calc(100vw - 32px));margin:0 auto;}
        nav{display:flex;justify-content:space-between;align-items:center;padding:26px 0;gap:18px;}
        .brand{font-weight:800;font-size:20px;letter-spacing:.2px;}
        .tagline{color:#b8dfe5;font-size:14px;border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:8px 12px;background:rgba(255,255,255,.08);}
        .btn{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 18px;border-radius:7px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);}
        .hero-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:42px;align-items:center;padding:58px 0 74px;}
        .eyebrow{display:inline-flex;align-items:center;gap:8px;margin-bottom:18px;padding:8px 12px;border:1px solid rgba(94,234,212,.35);border-radius:999px;color:#b6fff1;background:rgba(8,47,73,.42);font-size:14px;}
        h1{font-size:56px;line-height:1.05;margin:0 0 22px;letter-spacing:0;}
        .lead{font-size:18px;line-height:1.8;color:#d9eef2;max-width:680px;}
        .actions{display:flex;gap:14px;flex-wrap:wrap;margin-top:30px;}
        .primary{background:#30d5a0;color:#06251f;border-color:#30d5a0;font-weight:700;}
        .secondary{background:rgba(255,255,255,.1);color:white;}
        .signal-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:28px;max-width:700px;}
        .signal{border-left:2px solid #30d5a0;background:rgba(255,255,255,.08);border-radius:7px;padding:12px 14px;color:#d7f7f1;}
        .signal b{display:block;color:white;margin-bottom:4px;}
        .console{background:rgba(7,16,31,.72);border:1px solid rgba(255,255,255,.16);border-radius:8px;padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.25);}
        .console h2{font-size:18px;margin:0 0 16px;}
        .metric{display:grid;grid-template-columns:1fr auto;gap:8px;padding:13px 0;border-bottom:1px solid rgba(255,255,255,.12);}
        .metric:last-child{border-bottom:0;}
        .metric span{color:#9cc7d0;}
        .metric strong{font-size:18px;}
        section{padding:64px 0;}
        .section-head{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:22px;}
        .section-head h2{font-size:32px;margin:0;}
        .section-head p{margin:0;color:#64748b;max-width:560px;line-height:1.7;}
        .cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;}
        .card{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:22px;min-height:190px;box-shadow:0 10px 24px rgba(15,23,42,.05);}
        .card h3{margin:0 0 10px;font-size:20px;}
        .card p{color:#5b677a;line-height:1.7;margin:0 0 18px;}
        .card a{color:#0f766e;font-weight:700;}
        .flow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;}
        .step{background:#0f172a;color:white;border-radius:8px;padding:18px;min-height:150px;}
        .step b{display:block;color:#5eead4;margin-bottom:12px;}
        footer{padding:28px 0;color:#64748b;border-top:1px solid #e5e7eb;}
        @media (max-width:900px){
            .hero-grid,.cards,.flow{grid-template-columns:1fr;}
            h1{font-size:40px;}
            nav{align-items:flex-start;flex-direction:column;}
            .signal-row{grid-template-columns:1fr;}
        }
    </style>
</head>
<body class="commercial-page home-page">
    <div class="hero">
        <div class="wrap">
            <nav class="modern-nav">
                <div class="brand">Web3 Nodes Store</div>
                <div class="tagline">企业级分布式存储网络</div>
            </nav>
            <div class="hero-grid">
                <main>
                    <div class="eyebrow">存储 · 分享 · 节点激励 · 收益结算</div>
                    <h1>Web3 节点激励与文件分享系统</h1>
                    <p class="lead">面向节点运营、私有文件分发和收益结算的企业级分布式存储一体化平台。用户上传文件生成可控分享链接，节点贡献存储与带宽获得积分，后台实时查看网络、收益和提现审核。</p>
                    <div class="actions">
                        <a class="btn primary premium-button hover-lift" href="/user/login">开始使用<span class="button-shine"></span></a>
                        <a class="btn secondary premium-button hover-lift" href="/user/upload">上传并创建分享<span class="button-shine"></span></a>
                        <a class="btn secondary premium-button hover-lift" href="/admin">进入服务端后台<span class="button-shine"></span></a>
                    </div>
                    <div class="signal-row">
                        <div class="signal"><b>用户侧闭环</b>登录、上传、分享、收益都在同一条路径里完成。</div>
                        <div class="signal"><b>节点侧增长</b>用在线、存储、下载贡献驱动节点积分。</div>
                        <div class="signal"><b>运营侧可视</b>后台自动刷新网络、文件、收益和提现。</div>
                    </div>
                </main>
                <aside class="console commercial-card">
                    <h2>商业化能力概览</h2>
                    <div class="metric"><span>文件分享</span><strong>提取码 / 过期 / 限次</strong></div>
                    <div class="metric"><span>节点激励</span><strong>存储 + 下载积分</strong></div>
                    <div class="metric"><span>收益闭环</span><strong>积分 / 余额 / 提现</strong></div>
                    <div class="metric"><span>后台运营</span><strong>自动刷新监控</strong></div>
                </aside>
            </div>
        </div>
    </div>

    <section>
        <div class="wrap">
            <div class="section-head">
                <h2>业务入口</h2>
                <p>把分散页面收进一个首页，用户、节点和管理员都能从这里进入自己的工作流。</p>
            </div>
            <div class="cards">
                <article class="card commercial-card">
                    <h3>用户产品</h3>
                    <p>注册登录、钱包绑定、上传文件、创建分享链接，并查看积分收益和提现记录。</p>
                    <a href="/user/login">登录注册</a> · <a href="/user/dashboard">用户面板</a> · <a href="/user/upload">上传文件</a>
                </article>
                <article class="card commercial-card">
                    <h3>服务端运营</h3>
                    <p>管理节点、文件、分享、下载、积分流水与提现审核，后台数据自动刷新。</p>
                    <a href="/admin/login">后台登录</a> · <a href="/admin">后台面板</a>
                </article>
                <article class="card commercial-card">
                    <h3>节点接入</h3>
                    <p>客户端节点自动注册、心跳上报和断线重连，适合批量扩展存储网络。</p>
                    <a href="/api/health">服务健康检查</a>
                </article>
            </div>
        </div>
    </section>

    <section>
        <div class="wrap">
            <div class="section-head">
                <h2>从上传到收益</h2>
                <p>围绕文件分发做闭环，后续可以继续扩展套餐、容量计费、节点等级和企业工作台。</p>
            </div>
            <div class="flow">
                <div class="step"><b>01</b>用户登录后上传文件，系统加密并写入 IPFS。</div>
                <div class="step"><b>02</b>创建 `/s/&lt;share_code&gt;` 分享链接，设置提取码、过期和下载次数。</div>
                <div class="step"><b>03</b>下载成功后记录日志，给分享者和存储节点写入积分流水。</div>
                <div class="step"><b>04</b>用户在面板查看收益并提交提现，管理员在后台审核。</div>
            </div>
        </div>
    </section>

    <footer>
        <div class="wrap">本地服务入口：<a href="/">首页</a> / <a href="/admin">后台</a> / <a href="/user/dashboard">用户面板</a> / <a href="/api/health">健康检查</a></div>
    </footer>
</body>
</html>
'''

ADMIN_LOGIN_TEMPLATE = "admin_login.html"
ADMIN_LOGIN_HTML = (TEMPLATE_DIR / ADMIN_LOGIN_TEMPLATE).read_text(encoding="utf-8")

ADMIN_DASHBOARD_TEMPLATE = "admin_dashboard.html"
ADMIN_HTML = (TEMPLATE_DIR / ADMIN_DASHBOARD_TEMPLATE).read_text(encoding="utf-8")

USER_UPLOAD_TEMPLATE = "user_upload.html"
USER_UPLOAD_HTML = (TEMPLATE_DIR / USER_UPLOAD_TEMPLATE).read_text(encoding="utf-8")

USER_LOGIN_TEMPLATE = "user_login.html"
USER_LOGIN_HTML = (TEMPLATE_DIR / USER_LOGIN_TEMPLATE).read_text(encoding="utf-8")

USER_DASHBOARD_TEMPLATE = "user_dashboard.html"
USER_DASHBOARD_HTML = (TEMPLATE_DIR / USER_DASHBOARD_TEMPLATE).read_text(encoding="utf-8")

PUBLIC_SHARE_TEMPLATE = "public_share.html"
PUBLIC_SHARE_HTML = (TEMPLATE_DIR / PUBLIC_SHARE_TEMPLATE).read_text(encoding="utf-8")

