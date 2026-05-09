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
    // 显示名优先飞书 name，其次本地 username
    const displayName = me.name || me.username;
    const avatar = me.avatar_url
        ? `<img src="${me.avatar_url}" alt="" style="width:24px;height:24px;border-radius:50%;border:1px solid rgba(255,255,255,.15);" />`
        : '';
    const feishuTag = me.feishu_open_id
        ? `<span class="badge badge-blue" title="飞书登录">飞书</span>` : '';
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
        <span class="topbar-user" tabindex="0" style="display:inline-flex;align-items:center;gap:8px;cursor:default;">
          ${avatar}${escapeHtml(displayName)}
        </span>
        ${feishuTag}
        <span class="badge ${isAdmin ? 'badge-blue' : 'badge-green'}">${isAdmin ? '管理员' : '用户'}</span>
        <button id="btnLogout">退出</button>
      </div>`;
    document.getElementById('btnLogout').onclick = async () => {
        await API.logout(); window.location.href = '/login.html';
    };
    bindUserCardHover(el.querySelector('.topbar-user'), me);
}

// ---------- 用户名悬停名片 ----------
let _userCard = null;
let _userCardHideTimer = null;

function _userCardEl() {
    if (_userCard) return _userCard;
    _userCard = document.createElement('div');
    _userCard.className = 'user-card';
    _userCard.addEventListener('mouseenter', () => {
        if (_userCardHideTimer) { clearTimeout(_userCardHideTimer); _userCardHideTimer = null; }
    });
    _userCard.addEventListener('mouseleave', _scheduleHideUserCard);
    document.body.appendChild(_userCard);
    return _userCard;
}

function _scheduleHideUserCard() {
    if (_userCardHideTimer) clearTimeout(_userCardHideTimer);
    _userCardHideTimer = setTimeout(() => {
        if (_userCard) _userCard.classList.remove('open');
    }, 180);
}

function _renderUserCard(me) {
    const isAdmin = me.role === 'admin';
    const isFeishu = !!me.feishu_open_id;
    const avatarSrc = me.avatar_big || me.avatar_url || '';
    const initials = (me.name || me.username || '?').trim().slice(0, 1).toUpperCase();
    const avatarBlock = avatarSrc
        ? `<img src="${escapeHtml(avatarSrc)}" alt="" />`
        : `<div class="user-card-initials">${escapeHtml(initials)}</div>`;

    const rows = [];
    rows.push(['用户名', `<code>${escapeHtml(me.username)}</code>`]);
    if (me.en_name && me.en_name !== me.name) {
        rows.push(['英文名', escapeHtml(me.en_name)]);
    }
    if (me.email) {
        rows.push(['邮箱', `<a href="mailto:${escapeHtml(me.email)}">${escapeHtml(me.email)}</a>`]);
    }
    if (me.enterprise_email && me.enterprise_email !== me.email) {
        rows.push(['企业邮箱', `<a href="mailto:${escapeHtml(me.enterprise_email)}">${escapeHtml(me.enterprise_email)}</a>`]);
    }
    if (me.mobile) {
        rows.push(['手机', `<a href="tel:${escapeHtml(me.mobile)}">${escapeHtml(me.mobile)}</a>`]);
    }
    if (me.created_at) {
        rows.push(['加入时间', escapeHtml(fmtTime(me.created_at))]);
    }
    if (isFeishu && me.tenant_key) {
        rows.push(['飞书租户', `<code title="tenant_key">${escapeHtml(me.tenant_key.slice(0, 12))}…</code>`]);
    }

    const sourceTag = isFeishu
        ? '<span class="badge badge-blue">飞书登录</span>'
        : '<span class="badge badge-green">本地账号</span>';
    const roleTag = isAdmin
        ? '<span class="badge badge-blue">管理员</span>'
        : '<span class="badge badge-green">普通用户</span>';

    const rowsHtml = rows.map(([k, v]) =>
        `<div class="user-card-row"><span class="k">${k}</span><span class="v">${v}</span></div>`
    ).join('');

    return `
      <div class="user-card-head">
        <div class="user-card-avatar">${avatarBlock}</div>
        <div class="user-card-id">
          <div class="user-card-name">${escapeHtml(me.name || me.username)}</div>
          ${me.en_name && me.en_name !== me.name ? `<div class="user-card-sub">${escapeHtml(me.en_name)}</div>` : ''}
          <div class="user-card-tags">${roleTag} ${sourceTag}</div>
        </div>
      </div>
      <div class="user-card-body">${rowsHtml}</div>`;
}

function _showUserCard(target, me) {
    const card = _userCardEl();
    card.innerHTML = _renderUserCard(me);
    card.classList.add('open');
    // 暂时显示以测量实际尺寸，再定位
    const rect = target.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    let left = rect.right + window.scrollX - cardRect.width;
    if (left < 12) left = 12;
    if (left + cardRect.width > window.innerWidth - 12) {
        left = window.innerWidth - cardRect.width - 12;
    }
    let top = rect.bottom + window.scrollY + 8;
    if (top + cardRect.height > window.innerHeight + window.scrollY - 8) {
        top = rect.top + window.scrollY - cardRect.height - 8;
    }
    card.style.left = left + 'px';
    card.style.top = top + 'px';
}

function bindUserCardHover(target, me) {
    if (!target) return;
    const open = () => {
        if (_userCardHideTimer) { clearTimeout(_userCardHideTimer); _userCardHideTimer = null; }
        _showUserCard(target, me);
    };
    target.addEventListener('mouseenter', open);
    target.addEventListener('focus', open);
    target.addEventListener('mouseleave', _scheduleHideUserCard);
    target.addEventListener('blur', _scheduleHideUserCard);
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

function badgePhase(p, podName) {
    let cls = 'badge';
    if (p === 'Running') cls = 'badge badge-green';
    else if (p === 'Pending' || p === 'ContainerCreating') cls = 'badge badge-yellow';
    else if (p === 'Failed' || p === 'Unknown' || p === 'CrashLoopBackOff') cls = 'badge badge-red';
    const text = p || '-';
    if (!podName) {
        return `<span class="${cls}">${text}</span>`;
    }
    return `<span class="${cls} phase-hover" data-pod="${escapeHtml(podName)}" tabindex="0">${text}</span>`;
}

// 容器状态悬停 → 展示 kubectl describe 风格信息（懒加载，节流缓存）。
const _DESCRIBE_CACHE = new Map();  // pod -> { ts, data, promise }
const _DESCRIBE_TTL_MS = 8000;
let _phaseTip = null;
let _phaseTipTarget = null;

function _phaseTipEl() {
    if (_phaseTip) return _phaseTip;
    _phaseTip = document.createElement('div');
    _phaseTip.className = 'phase-tip';
    document.body.appendChild(_phaseTip);
    return _phaseTip;
}

function _renderDescribe(d) {
    if (!d) return '加载中…';
    if (d.error) return '错误：' + escapeHtml(d.error);
    const lines = [];
    lines.push(`<div class="phase-tip-title">Pod: <code>${escapeHtml(d.name)}</code></div>`);
    lines.push(`<div>Phase: <b>${escapeHtml(d.phase || '-')}</b>`
        + (d.reason ? `  Reason: <b>${escapeHtml(d.reason)}</b>` : '')
        + (d.node ? `  Node: ${escapeHtml(d.node)}` : '')
        + `</div>`);
    if (d.message) lines.push(`<div class="phase-tip-msg">Message: ${escapeHtml(d.message)}</div>`);
    if (d.container_statuses && d.container_statuses.length) {
        lines.push('<div class="phase-tip-section">容器状态</div>');
        d.container_statuses.forEach(cs => {
            let line = `· ${escapeHtml(cs.name)}: <b>${escapeHtml(cs.state)}</b>`;
            if (cs.reason) line += ` (${escapeHtml(cs.reason)})`;
            line += ` ready=${cs.ready ? '是' : '否'} restarts=${cs.restart_count}`;
            if (cs.message) line += `<div class="phase-tip-msg">${escapeHtml(cs.message)}</div>`;
            if (cs.last_state) line += `<div class="phase-tip-msg">${escapeHtml(cs.last_state)}</div>`;
            lines.push(`<div>${line}</div>`);
        });
    }
    const events = d.events || [];
    lines.push(`<div class="phase-tip-section">最近事件 (${events.length})</div>`);
    if (!events.length) {
        lines.push('<div class="phase-tip-msg">无事件</div>');
    } else {
        events.slice(0, 8).forEach(ev => {
            const t = ev.time ? new Date(ev.time).toLocaleString() : '';
            const tcls = ev.type === 'Warning' ? 'phase-ev-warn' : 'phase-ev-norm';
            lines.push(
                `<div class="phase-ev"><span class="${tcls}">[${escapeHtml(ev.type || '-')}]</span> ` +
                `<b>${escapeHtml(ev.reason || '-')}</b> ` +
                `<span class="phase-tip-meta">×${ev.count} ${escapeHtml(t)}</span>` +
                `<div class="phase-tip-msg">${escapeHtml(ev.message || '')}</div></div>`
            );
        });
    }
    return lines.join('');
}

function _showPhaseTip(target, html) {
    const tip = _phaseTipEl();
    tip.innerHTML = html;
    tip.style.display = 'block';
    const rect = target.getBoundingClientRect();
    const tipRect = tip.getBoundingClientRect();
    let left = rect.left + window.scrollX;
    if (left + tipRect.width + 12 > window.innerWidth + window.scrollX) {
        left = window.innerWidth + window.scrollX - tipRect.width - 12;
    }
    let top = rect.bottom + window.scrollY + 6;
    if (top + tipRect.height > window.innerHeight + window.scrollY) {
        top = rect.top + window.scrollY - tipRect.height - 6;
    }
    tip.style.left = Math.max(8, left) + 'px';
    tip.style.top = Math.max(8, top) + 'px';
}

function _hidePhaseTip() {
    if (_phaseTip) _phaseTip.style.display = 'none';
    _phaseTipTarget = null;
}

function _fetchDescribe(podName) {
    const cached = _DESCRIBE_CACHE.get(podName);
    if (cached && Date.now() - cached.ts < _DESCRIBE_TTL_MS) {
        return Promise.resolve(cached.data);
    }
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
        const pod = t.dataset.pod;
        _showPhaseTip(t, '加载中…');
        _fetchDescribe(pod).then(d => {
            if (_phaseTipTarget !== t) return;
            _showPhaseTip(t, _renderDescribe(d));
        });
    });
    root.addEventListener('mouseout', e => {
        const t = e.target.closest('.phase-hover');
        if (!t) return;
        if (e.relatedTarget && t.contains(e.relatedTarget)) return;
        _hidePhaseTip();
    });
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
