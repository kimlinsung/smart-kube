// 公共：控制台 Shell（侧栏 + 顶栏）渲染 + 当前用户 + 通用工具。

// ---------- 图标 ----------
const ICONS = {
    dashboard: '<path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z"/>',
    experiments: '<path d="M9 3h6M10 3v6.5L5.2 18a2 2 0 0 0 1.8 3h10a2 2 0 0 0 1.8-3L14 9.5V3"/><path d="M8 14h8"/>',
    logs: '<path d="M8 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-2"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M8 11h8M8 15h6"/>',
    admin: '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    layers: '<path d="M12 3 3 8l9 5 9-5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    caret: '<path d="M6 9l6 6 6-6"/>',
    menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
    sparkle: '<path d="M12 3l1.9 4.9L19 9.8l-5.1 1.9L12 17l-1.9-5.3L5 9.8l5.1-1.9L12 3zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15z"/>',
    box: '<path d="M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8"/>',
    server: '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    node: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
    users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    workflow: '<rect x="3" y="4" width="6" height="5" rx="1"/><rect x="15" y="4" width="6" height="5" rx="1"/><rect x="9" y="15" width="6" height="5" rx="1"/><path d="M9 6.5h6M6 9v3h6v3M18 9v3h-6"/>',
};
function icon(name, cls = '') {
    return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`;
}
function brandMark() {
    return `<span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="5.5" r="2.25"/>
            <circle cx="5.5" cy="17.5" r="2.25"/>
            <circle cx="18.5" cy="17.5" r="2.25"/>
            <path d="M10.9 7.5 6.6 15.5M13.1 7.5l4.3 8M7.8 17.5h8.4"/>
            <path d="M12 11.2l2.1 1.2v2.4L12 16l-2.1-1.2v-2.4L12 11.2z"/>
        </svg>
    </span>`;
}

// ---------- 导航 & 页面元信息 ----------
const NAV = [
    { key: 'dashboard',   href: '/dashboard.html',   label: '我的资源', ico: 'dashboard' },
    { key: 'experiments', href: '/experiments.html', label: '实验管理', ico: 'experiments' },
    { key: 'paper_workspace', href: '/paper_workspace.html', label: '论文工作区', ico: 'workflow' },
    { key: 'logs',        href: '/logs.html',        label: '操作日志', ico: 'logs' },
    { key: 'admin',       href: '/admin.html',       label: '集群管理', ico: 'admin', admin: true },
    { key: 'all_units',   href: '/all_units.html',   label: '全部 Units', ico: 'box', admin: true },
    { key: 'users',       href: '/users.html',       label: '用户管理', ico: 'users', admin: true },
];
const PAGE_META = {
    dashboard:         { nav: 'dashboard',   title: '我的资源',   sub: '管理你的云 / 边 / 端容器实例' },
    experiments:       { nav: 'experiments', title: '实验管理',   sub: '组织与切换你的实验环境' },
    experiment_detail: { nav: 'experiments', title: '实验详情',   sub: '实验内的云边端资源明细' },
    paper_workspace:    { nav: 'paper_workspace', title: '论文工作区', sub: '配置、调度、分析与实验产物' },
    logs:              { nav: 'logs',        title: '操作日志',   sub: '系统操作审计记录' },
    admin:             { nav: 'admin',       title: '集群管理',   sub: '集群节点状态与调度控制' },
    all_units:         { nav: 'all_units',   title: '全部 Units', sub: '管理所有用户的云 / 边 / 端容器' },
    users:             { nav: 'users',       title: '用户管理',   sub: '平台账号、角色与访问权限' },
};

let ME = window.ME || null;
let _presenceSocket = null;
let _presenceRetryTimer = null;
let _presenceRetryDelay = 1000;

function connectPresence() {
    if (!ME || !('WebSocket' in window)) return;
    if (_presenceSocket && (_presenceSocket.readyState === WebSocket.OPEN || _presenceSocket.readyState === WebSocket.CONNECTING)) return;
    if (_presenceRetryTimer) { clearTimeout(_presenceRetryTimer); _presenceRetryTimer = null; }
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${protocol}://${location.host}/ws/presence`);
    _presenceSocket = socket;
    socket.onopen = () => { _presenceRetryDelay = 1000; };
    socket.onmessage = event => {
        try {
            const detail = JSON.parse(event.data);
            window.dispatchEvent(new CustomEvent('presence:update', { detail }));
        } catch (_) { /* ignore malformed presence events */ }
    };
    socket.onclose = () => {
        if (_presenceSocket !== socket) return;
        _presenceSocket = null;
        _presenceRetryTimer = setTimeout(connectPresence, _presenceRetryDelay);
        _presenceRetryDelay = Math.min(_presenceRetryDelay * 2, 30000);
    };
}
window.addEventListener('online', connectPresence);

async function loadMe() {
    try {
        const me = await API.me();
        ME = me; window.ME = me;
        renderShell(me);
        connectPresence();
        return me;
    } catch (e) {
        window.location.href = '/login.html';
    }
}

function renderShell(me) {
    ME = me; window.ME = me;
    const pageKey = document.body.dataset.page || '';
    const meta = PAGE_META[pageKey] || { nav: pageKey, title: document.title, sub: '' };
    const isAdmin = me.role === 'admin';

    // ---- 侧栏 ----
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        const navItems = NAV.filter(n => !n.admin || isAdmin).map(n => `
            <a href="${n.href}" class="nav-item ${n.key === meta.nav ? 'active' : ''}">
                ${icon(n.ico, 'ico')}<span>${n.label}</span>
            </a>`).join('');
        const expChip = me.current_experiment_name ? `
            <a class="exp-chip" href="/experiments.html" title="当前实验，点击切换">
                ${icon('layers', 'ico')}
                <span style="min-width:0;display:flex;flex-direction:column;line-height:1.2;">
                    <span class="lbl">当前实验</span>
                    <span class="val">${escapeHtml(me.current_experiment_name)}</span>
                </span>
            </a>` : '';
        sidebar.innerHTML = `
            <div class="sidebar-brand">
                ${brandMark()}
                <span class="brand-text"><span class="t1">智能云边端</span><span class="t2">CLOUD · EDGE · DEVICE</span></span>
            </div>
            <div class="sidebar-section">导航</div>
            <nav class="sidebar-nav">${navItems}</nav>
            <div class="sidebar-spacer"></div>
            <div class="sidebar-foot">
                ${expChip}
                <button class="user-btn" id="userBtn">
                    <span class="avatar">${avatarInner(me)}</span>
                    <span class="u-meta">
                        <span class="u-name">${escapeHtml(me.name || me.username)}</span>
                        <span class="u-role">${isAdmin ? '管理员' : '普通用户'}</span>
                    </span>
                    ${icon('caret', 'u-caret')}
                </button>
            </div>`;
        const ub = sidebar.querySelector('#userBtn');
        if (ub) ub.onclick = e => { e.stopPropagation(); toggleUserMenu(ub, me); };
    }

    // ---- 顶栏 ----
    const topbar = document.getElementById('topbar');
    if (topbar) {
        topbar.innerHTML = `
            <button class="icon-btn btn-ghost menu-toggle" id="menuToggle" title="菜单">${icon('menu')}</button>
            <div class="tb-titles">
                <div class="tb-title">${escapeHtml(meta.title)}</div>
                <div class="tb-sub">${escapeHtml(meta.sub || '')}</div>
            </div>
            <div class="tb-right">
                <button class="ai-btn" id="aiBtn">${icon('sparkle', 'ico')}<span>AI 助手</span></button>
            </div>`;
        const aiBtn = topbar.querySelector('#aiBtn');
        if (aiBtn) aiBtn.onclick = () => { if (window.Assistant) window.Assistant.toggle(); };
        const mt = topbar.querySelector('#menuToggle');
        if (mt) mt.onclick = toggleSidebar;
    }
}
// 兼容旧调用名
const renderTopbar = renderShell;

function avatarInner(me) {
    const src = me.avatar_url || me.avatar_big;
    if (src) return `<img src="${escapeHtml(src)}" alt="" />`;
    return escapeHtml((me.name || me.username || '?').trim().slice(0, 1).toUpperCase());
}

// ---------- 移动端侧栏 ----------
function toggleSidebar() {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    let bd = document.querySelector('.sidebar-backdrop');
    if (!bd) {
        bd = document.createElement('div'); bd.className = 'sidebar-backdrop';
        bd.onclick = toggleSidebar; document.body.appendChild(bd);
    }
    const open = sb.classList.toggle('open');
    bd.classList.toggle('open', open);
}

// ---------- 用户菜单 ----------
let _userMenu = null;
function toggleUserMenu(btn, me) {
    if (_userMenu && _userMenu.classList.contains('open')) { _userMenu.classList.remove('open'); return; }
    if (!_userMenu) {
        _userMenu = document.createElement('div');
        _userMenu.className = 'user-menu';
        document.body.appendChild(_userMenu);
        document.addEventListener('click', e => {
            if (_userMenu && !_userMenu.contains(e.target) && !btn.contains(e.target)) _userMenu.classList.remove('open');
        });
    }
    _userMenu.innerHTML = renderUserMenu(me);
    const lo = _userMenu.querySelector('#menuLogout');
    if (lo) lo.onclick = async () => { await API.logout(); window.location.href = '/login.html'; };
    _userMenu.classList.add('open');
    // 定位在用户按钮上方
    const r = btn.getBoundingClientRect();
    const mr = _userMenu.getBoundingClientRect();
    let left = r.left;
    if (left + mr.width > window.innerWidth - 10) left = window.innerWidth - mr.width - 10;
    let top = r.top - mr.height - 8;
    if (top < 10) top = r.bottom + 8;
    _userMenu.style.left = Math.max(10, left) + 'px';
    _userMenu.style.top = top + 'px';
}

function renderUserMenu(me) {
    const isAdmin = me.role === 'admin';
    const isFeishu = !!me.feishu_open_id;
    const rows = [];
    rows.push(['用户名', `<code>${escapeHtml(me.username)}</code>`]);
    if (me.email) rows.push(['邮箱', `<a href="mailto:${escapeHtml(me.email)}">${escapeHtml(me.email)}</a>`]);
    if (me.enterprise_email && me.enterprise_email !== me.email) rows.push(['企业邮箱', `<a href="mailto:${escapeHtml(me.enterprise_email)}">${escapeHtml(me.enterprise_email)}</a>`]);
    if (me.mobile) rows.push(['手机', escapeHtml(me.mobile)]);
    if (me.current_experiment_name) rows.push(['当前实验', escapeHtml(me.current_experiment_name)]);
    if (me.created_at) rows.push(['加入', escapeHtml(fmtTime(me.created_at))]);
    const roleTag = isAdmin ? '<span class="badge badge-blue">管理员</span>' : '<span class="badge badge-green">普通用户</span>';
    const srcTag = isFeishu ? '<span class="badge badge-blue">飞书登录</span>' : '<span class="badge badge-green">本地账号</span>';
    return `
        <div class="user-menu-head">
            <span class="avatar">${avatarInner(me)}</span>
            <div style="min-width:0;">
                <div class="u-name">${escapeHtml(me.name || me.username)}</div>
                ${me.en_name && me.en_name !== me.name ? `<div class="u-sub">${escapeHtml(me.en_name)}</div>` : ''}
                <div class="user-menu-tags">${roleTag} ${srcTag}</div>
            </div>
        </div>
        <div class="user-menu-body">
            ${rows.map(([k, v]) => `<div class="user-menu-row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join('')}
        </div>
        <div class="user-menu-foot">
            <button class="danger" id="menuLogout">${icon('logout')}<span>退出登录</span></button>
        </div>`;
}

// ---------- 通用工具 ----------
function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function fmtTime(s) {
    if (!s) return '-';
    if (typeof s === 'number') return new Date(s * 1000).toLocaleString('zh-CN', { hour12: false });
    return new Date(s).toLocaleString('zh-CN', { hour12: false });
}

// 可见性感知轮询：隐藏标签页时暂停，切回时立即刷新。fn 应做静默刷新。
function startPolling(fn, ms) {
    let timer = null;
    const start = () => { if (timer == null) timer = setInterval(() => { if (!document.hidden) fn(); }, ms); };
    const stop  = () => { if (timer != null) { clearInterval(timer); timer = null; } };
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stop(); else { fn(); start(); }
    });
    start();
    return { stop, refresh: fn };
}

// ---------- Phase 徽章 + describe 悬停 ----------
function badgePhase(p, podName) {
    let cls = 'badge dot';
    if (p === 'Running') cls = 'badge dot badge-green';
    else if (p === 'Pending' || p === 'ContainerCreating') cls = 'badge dot badge-yellow';
    else if (p === 'Failed' || p === 'Unknown' || p === 'CrashLoopBackOff') cls = 'badge dot badge-red';
    else cls = 'badge dot badge-blue';
    const text = p || '-';
    if (!podName) return `<span class="${cls}">${text}</span>`;
    return `<span class="${cls} phase-hover" data-pod="${escapeHtml(podName)}" tabindex="0">${text}</span>`;
}

const _DESCRIBE_CACHE = new Map();
const _DESCRIBE_TTL_MS = 8000;
let _phaseTip = null, _phaseTipTarget = null;

function _phaseTipEl() {
    if (_phaseTip) return _phaseTip;
    _phaseTip = document.createElement('div');
    _phaseTip.className = 'phase-tip';
    document.body.appendChild(_phaseTip);
    return _phaseTip;
}
function _renderDescribe(d) {
    if (!d) return '<div class="phase-tip-inner">加载中…</div>';
    if (d.error) return `<div class="phase-tip-inner">错误：${escapeHtml(d.error)}</div>`;
    const L = [];
    L.push(`<div class="phase-tip-title">Pod: <code>${escapeHtml(d.name)}</code></div>`);
    const inner = [];
    inner.push(`<div>Phase: <b>${escapeHtml(d.phase || '-')}</b>`
        + (d.reason ? `　Reason: <b>${escapeHtml(d.reason)}</b>` : '')
        + (d.node ? `　Node: ${escapeHtml(d.node)}` : '') + `</div>`);
    if (d.message) inner.push(`<div class="phase-tip-msg">${escapeHtml(d.message)}</div>`);
    if (d.container_statuses && d.container_statuses.length) {
        inner.push('<div class="phase-tip-section">容器状态</div>');
        d.container_statuses.forEach(cs => {
            let line = `· ${escapeHtml(cs.name)}: <b>${escapeHtml(cs.state)}</b>`;
            if (cs.reason) line += ` (${escapeHtml(cs.reason)})`;
            line += `　ready=${cs.ready ? '是' : '否'} restarts=${cs.restart_count}`;
            if (cs.message) line += `<div class="phase-tip-msg">${escapeHtml(cs.message)}</div>`;
            if (cs.last_state) line += `<div class="phase-tip-msg">${escapeHtml(cs.last_state)}</div>`;
            inner.push(`<div>${line}</div>`);
        });
    }
    const events = d.events || [];
    inner.push(`<div class="phase-tip-section">最近事件 (${events.length})</div>`);
    if (!events.length) inner.push('<div class="phase-tip-msg">无事件</div>');
    else events.slice(0, 8).forEach(ev => {
        const t = ev.time ? new Date(ev.time).toLocaleString('zh-CN', { hour12: false }) : '';
        const tcls = ev.type === 'Warning' ? 'phase-ev-warn' : 'phase-ev-norm';
        inner.push(`<div class="phase-ev"><span class="${tcls}">[${escapeHtml(ev.type || '-')}]</span> `
            + `<b>${escapeHtml(ev.reason || '-')}</b> `
            + `<span class="phase-tip-meta">×${ev.count} ${escapeHtml(t)}</span>`
            + `<div class="phase-tip-msg">${escapeHtml(ev.message || '')}</div></div>`);
    });
    L.push(`<div class="phase-tip-inner">${inner.join('')}</div>`);
    return L.join('');
}
function _showPhaseTip(target, html) {
    const tip = _phaseTipEl();
    tip.innerHTML = html; tip.style.display = 'block';
    const r = target.getBoundingClientRect(), tr = tip.getBoundingClientRect();
    let left = r.left + window.scrollX;
    if (left + tr.width + 12 > window.innerWidth + window.scrollX) left = window.innerWidth + window.scrollX - tr.width - 12;
    let top = r.bottom + window.scrollY + 6;
    if (top + tr.height > window.innerHeight + window.scrollY) top = r.top + window.scrollY - tr.height - 6;
    tip.style.left = Math.max(8, left) + 'px';
    tip.style.top = Math.max(8, top) + 'px';
}
function _hidePhaseTip() { if (_phaseTip) _phaseTip.style.display = 'none'; _phaseTipTarget = null; }
function _fetchDescribe(podName) {
    const cached = _DESCRIBE_CACHE.get(podName);
    if (cached && Date.now() - cached.ts < _DESCRIBE_TTL_MS) return Promise.resolve(cached.data);
    if (cached && cached.promise) return cached.promise;
    const promise = API.describeResource(podName)
        .then(d => { _DESCRIBE_CACHE.set(podName, { ts: Date.now(), data: d }); return d; })
        .catch(e => { const err = { error: e.message }; _DESCRIBE_CACHE.set(podName, { ts: Date.now(), data: err }); return err; });
    _DESCRIBE_CACHE.set(podName, { ts: 0, promise });
    return promise;
}
function bindPhaseHover(root) {
    if (!root || root.__phaseHoverBound) return;
    root.__phaseHoverBound = true;
    root.addEventListener('mouseover', e => {
        const t = e.target.closest('.phase-hover');
        if (!t || t === _phaseTipTarget) return;
        _phaseTipTarget = t;
        _showPhaseTip(t, '<div class="phase-tip-inner">加载中…</div>');
        _fetchDescribe(t.dataset.pod).then(d => { if (_phaseTipTarget === t) _showPhaseTip(t, _renderDescribe(d)); });
    });
    root.addEventListener('mouseout', e => {
        const t = e.target.closest('.phase-hover');
        if (!t) return;
        if (e.relatedTarget && t.contains(e.relatedTarget)) return;
        _hidePhaseTip();
    });
}

// ---------- 云边端分层 ----------
function badgeNodeType(nt) {
    const map = { cloud: ['badge-cloud', '云 Cloud'], edge: ['badge-edge', '边 Edge'], device: ['badge-device', '端 Device'] };
    const [cls, label] = map[nt] || ['badge-edge', nt || 'edge'];
    return `<span class="badge ${cls}">${label}</span>`;
}
const _NT_ORDER = ['cloud', 'edge', 'device'];
const _NT_META = {
    cloud:  { label: '云节点 · Cloud',  bg: 'var(--cloud-bg)',  color: 'var(--cloud)' },
    edge:   { label: '边缘节点 · Edge',  bg: 'var(--edge-bg)',   color: 'var(--edge)' },
    device: { label: '端设备 · Device',  bg: 'var(--device-bg)', color: 'var(--device)' },
};
function groupByNodeType(items, key = 'node_type') {
    const groups = {};
    items.forEach(item => { const k = item[key] || 'edge'; (groups[k] = groups[k] || []).push(item); });
    const ordered = _NT_ORDER.filter(k => groups[k]);
    const rest = Object.keys(groups).filter(k => !_NT_ORDER.includes(k));
    return [...ordered, ...rest].map(k => ({ type: k, items: groups[k] }));
}
function ntGroupHeaderHTML(type, count, colSpan) {
    const m = _NT_META[type] || { label: type, bg: 'var(--surface-3)', color: 'var(--text-2)' };
    return `<tr class="nt-group"><td colspan="${colSpan}" style="background:${m.bg};color:${m.color};">${m.label}（${count}）</td></tr>`;
}
