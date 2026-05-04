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
    const expName = me.current_experiment_name
        ? `<span class="topbar-exp" title="当前实验">实验：<b>${escapeHtml(me.current_experiment_name)}</b></span>`
        : '';
    el.innerHTML = `
      <h1>智能云边端(Cloud-Edge-Device)调度系统</h1>
      <nav>
        <a href="/experiments.html" class="${path.endsWith('experiments.html') ? 'active' : ''}">实验管理</a>
        <a href="/dashboard.html" class="${path.endsWith('dashboard.html') ? 'active' : ''}">我的资源</a>
        <a href="/logs.html" class="${path.endsWith('logs.html') ? 'active' : ''}">操作日志</a>
        ${isAdmin ? `<a href="/admin.html" class="${path.endsWith('admin.html') ? 'active' : ''}">集群管理</a>` : ''}
      </nav>
      <div class="user">
        ${expName}
        ${me.username} <span class="badge ${isAdmin ? 'badge-blue' : 'badge-green'}">${isAdmin ? '管理员' : '用户'}</span>
        <button id="btnLogout">退出</button>
      </div>`;
    document.getElementById('btnLogout').onclick = async () => {
        await API.logout(); window.location.href = '/login.html';
    };
}

function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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

// 云边端分层分组工具
const _NT_ORDER = ['cloud', 'edge', 'device'];
const _NT_META  = {
    cloud:  { label: '云节点 (Cloud)',   bg: '#e0f2fe', color: '#0369a1' },
    edge:   { label: '边缘节点 (Edge)',  bg: '#ede9fe', color: '#6d28d9' },
    device: { label: '端设备 (Device)',  bg: '#ffedd5', color: '#c2410c' },
};

function groupByNodeType(items, key = 'node_type') {
    const groups = {};
    items.forEach(item => {
        const k = item[key] || 'edge';
        (groups[k] = groups[k] || []).push(item);
    });
    const ordered = _NT_ORDER.filter(k => groups[k]);
    const rest    = Object.keys(groups).filter(k => !_NT_ORDER.includes(k));
    return [...ordered, ...rest].map(k => ({ type: k, items: groups[k] }));
}

function ntGroupHeaderHTML(type, count, colSpan) {
    const m = _NT_META[type] || { label: type, bg: '#f3f4f6', color: '#374151' };
    return `<tr><td colspan="${colSpan}" style="background:${m.bg};color:${m.color};font-weight:600;font-size:12px;padding:5px 10px;border-bottom:2px solid ${m.color}30;">${m.label}（${count} 个）</td></tr>`;
}
