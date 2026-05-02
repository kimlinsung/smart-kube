// 公共：顶栏渲染 + 当前用户。
async function loadMe() {
    try {
        const me = await API.me();
        renderTopbar(me);
        return me;
    } catch (e) {
        window.location.href = '/login.html';
    }
}

function renderTopbar(me) {
    const el = document.getElementById('topbar');
    if (!el) return;
    const path = window.location.pathname;
    const isAdmin = me.role === 'admin';
    el.innerHTML = `
      <h1>智能云边端(Cloud-Edge-Device)调度系统</h1>
      <nav>
        <a href="/dashboard.html" class="${path.endsWith('dashboard.html') ? 'active' : ''}">我的资源</a>
        <a href="/logs.html" class="${path.endsWith('logs.html') ? 'active' : ''}">操作日志</a>
        ${isAdmin ? `<a href="/admin.html" class="${path.endsWith('admin.html') ? 'active' : ''}">集群管理</a>` : ''}
      </nav>
      <div class="user">
        ${me.username} <span class="badge ${isAdmin ? 'badge-blue' : 'badge-green'}">${isAdmin ? '管理员' : '用户'}</span>
        <button id="btnLogout">退出</button>
      </div>`;
    document.getElementById('btnLogout').onclick = async () => {
        await API.logout(); window.location.href = '/login.html';
    };
}

function fmtTime(s) {
    if (!s) return '-';
    if (typeof s === 'number') return new Date(s*1000).toLocaleString();
    return new Date(s).toLocaleString();
}

function badgePhase(p) {
    if (p === 'Running') return `<span class="badge badge-green">${p}</span>`;
    if (p === 'Pending' || p === 'ContainerCreating') return `<span class="badge badge-yellow">${p}</span>`;
    if (p === 'Failed' || p === 'Unknown' || p === 'CrashLoopBackOff') return `<span class="badge badge-red">${p}</span>`;
    return `<span class="badge">${p || '-'}</span>`;
}

function badgeNodeType(nt) {
    const map = { cloud: ['badge-cloud', 'Cloud'], edge: ['badge-edge', 'Edge'], device: ['badge-device', 'Device'] };
    const [cls, label] = map[nt] || ['badge-edge', nt || 'edge'];
    return `<span class="badge ${cls}">${label}</span>`;
}
