// 全局 AI 助手：右侧抽屉。所有控制台页面通用。

// ---------- Markdown（marked + DOMPurify，CDN 懒加载，失败降级纯文本） ----------
const MD = (() => {
    let _ready = null;
    function _load(src) {
        return new Promise((res, rej) => {
            const s = document.createElement('script');
            s.src = src; s.async = true; s.onload = res; s.onerror = () => rej(new Error(src));
            document.head.appendChild(s);
        });
    }
    function ready() {
        if (_ready) return _ready;
        _ready = (async () => {
            try {
                if (!window.marked) await _load('/vendor/marked.min.js');
                if (!window.DOMPurify) await _load('/vendor/purify.min.js');
                if (window.marked && window.marked.setOptions) window.marked.setOptions({ breaks: true, gfm: true });
            } catch (e) { console.warn('markdown 库加载失败，降级纯文本：', e); }
        })();
        return _ready;
    }
    function render(text) {
        const src = text == null ? '' : String(text);
        if (window.marked && window.DOMPurify) {
            try { return { html: window.DOMPurify.sanitize(window.marked.parse(src)), md: true }; } catch (e) { /* noop */ }
        }
        return { html: esc(src), md: false };
    }
    function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
    return { ready, render };
})();

function renderBubbleMarkdown(bubble, text) {
    bubble.dataset.md = text == null ? '' : String(text);
    const { html, md } = MD.render(text);
    bubble.innerHTML = html;
    bubble.classList.toggle('md', md);
}

const SUGGESTIONS = [
    '创建一个 riscv 架构的 Ubuntu SSH 容器',
    '列出我的资源',
    '批量创建 3 个 Ubuntu SSH 容器',
];

function injectAssistant() {
    MD.ready();

    // FAB
    const fab = document.createElement('button');
    fab.className = 'assistant-fab'; fab.title = 'AI 助手';
    fab.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.9L19 9.8l-5.1 1.9L12 17l-1.9-5.3L5 9.8l5.1-1.9L12 3z"/><path d="M19 15l.6 1.6L21 17l-1.4.4L19 19l-.6-1.6L17 17l1.4-.4L19 15z"/></svg>';
    document.body.appendChild(fab);

    const backdrop = document.createElement('div');
    backdrop.className = 'assistant-backdrop';
    document.body.appendChild(backdrop);

    const panel = document.createElement('div');
    panel.className = 'assistant';
    panel.innerHTML = `
      <div class="assistant-head">
        <span class="a-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.9L19 9.8l-5.1 1.9L12 17l-1.9-5.3L5 9.8l5.1-1.9L12 3z"/></svg></span>
        <div class="a-tt">
          <div class="a-title">AI 助手</div>
          <div class="a-sub"><span class="live"></span>端边云智能编排 · 在线</div>
        </div>
        <div class="a-actions">
          <button id="aClear" title="清空对话"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg></button>
          <button id="aClose" title="收起"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg></button>
        </div>
      </div>
      <div class="assistant-msgs" id="aMsgs"></div>
      <section class="assistant-tasks" id="aTaskCenter" hidden>
        <button class="task-center-head" id="aTaskToggle" type="button" aria-expanded="true">
          <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M9 3h6M10 3v6.5L5.2 18a2 2 0 0 0 1.8 3h10a2 2 0 0 0 1.8-3L14 9.5V3"/><path d="M8 14h8"/></svg>执行动态</span>
          <span class="task-center-meta"><b id="aActiveCount">0</b><svg class="task-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></span>
        </button>
        <div class="task-list" id="aTasks"></div>
      </section>
      <div class="assistant-suggest" id="aSuggest"></div>
      <div class="assistant-input">
        <div class="script-workspace">
          <button class="script-picker" id="aScriptPicker" type="button">
            <span class="script-picker-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg></span>
            <span><b>选择脚本</b><small>Python、Shell 或配置文件</small></span>
          </button>
          <input type="file" id="aFile" hidden accept=".py,.txt,.json,.yaml,.yml,.sh" />
          <div class="script-upload-progress" id="aUploadProgress" hidden>
            <div><span>正在上传</span><b id="aUploadPercent">0%</b></div>
            <span class="task-progress"><i id="aUploadBar"></i></span>
          </div>
          <div class="script-current" id="aScriptCurrent" hidden>
            <span class="script-file-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 13h6M9 17h4"/></svg></span>
            <span class="script-file-meta"><b id="aScriptName"></b><small id="aScriptMeta"></small></span>
            <button class="icon-btn" id="aReplaceScript" type="button" title="替换脚本" aria-label="替换脚本"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M20 11a8.1 8.1 0 1 0 2 5M20 4v7h-7"/></svg></button>
          </div>
          <div class="script-run-panel" id="aRunPanel" hidden>
            <details>
              <summary>运行设置</summary>
              <div class="script-run-options">
                <label>架构<select id="aRunArch"><option value="">自动选择</option><option value="amd64">amd64</option><option value="arm64">arm64</option><option value="riscv64">riscv64</option></select></label>
                <label>节点<input id="aRunHost" type="text" placeholder="自动选择" /></label>
                <label>超时（秒）<input id="aRunTimeout" type="number" min="10" max="600" value="120" /></label>
              </div>
            </details>
            <button class="script-run-btn" id="aRunScript" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m8 5 11 7-11 7z"/></svg>直接运行</button>
          </div>
        </div>
        <div class="in-wrap"><textarea id="aText" placeholder="用自然语言描述你的需求，例如：创建一个 riscv 架构机器上的 Ubuntu SSH 系统"></textarea></div>
        <div class="in-row">
          <span class="composer-state" id="aComposerState">可发送新任务</span>
          <button class="primary send" id="aSend">发送</button>
        </div>
      </div>`;
    document.body.appendChild(panel);

    const msgsEl = panel.querySelector('#aMsgs');
    const textEl = panel.querySelector('#aText');
    const fileEl = panel.querySelector('#aFile');
    const suggestEl = panel.querySelector('#aSuggest');
    const tasksEl = panel.querySelector('#aTasks');
    const taskCenter = panel.querySelector('#aTaskCenter');
    const sendButton = panel.querySelector('#aSend');
    let currentScript = null;
    let taskSocket = null;
    let taskRetryTimer = null;
    let taskRetryDelay = 1000;
    const tasks = new Map();
    const chatTaskBubbles = new Map();

    function open() {
        panel.classList.add('open'); backdrop.classList.add('open'); fab.classList.add('hidden');
        msgsEl.scrollTop = msgsEl.scrollHeight; setTimeout(() => textEl.focus(), 120);
    }
    function close() { panel.classList.remove('open'); backdrop.classList.remove('open'); fab.classList.remove('hidden'); }
    function toggle() { panel.classList.contains('open') ? close() : open(); }
    window.Assistant = { open, close, toggle };

    fab.onclick = toggle;
    backdrop.onclick = close;
    panel.querySelector('#aClose').onclick = close;

    function fmtChatTime(ts) {
        const d = ts ? new Date(ts * 1000) : new Date();
        const p = n => String(n).padStart(2, '0');
        return `${p(d.getHours())}:${p(d.getMinutes())}`;
    }
    function avatarFor(role) {
        if (role === 'user') {
            const me = window.ME;
            const src = me && (me.avatar_url || me.avatar_big);
            if (src) return `<img src="${escapeHtml(src)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:9px;" />`;
            return me ? (me.name || me.username || '我').trim().slice(0, 1).toUpperCase() : '我';
        }
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="M12 3l1.9 4.9L19 9.8l-5.1 1.9L12 17l-1.9-5.3L5 9.8l5.1-1.9L12 3z"/></svg>';
    }

    function append(role, content, ts) {
        const div = document.createElement('div');
        div.className = 'a-msg ' + role;
        const av = document.createElement('div');
        av.className = 'a-avatar'; av.innerHTML = avatarFor(role);
        const wrap = document.createElement('div');
        wrap.className = 'a-bubble-wrap';
        const b = document.createElement('div');
        b.className = 'a-bubble';
        if (role === 'assistant') renderBubbleMarkdown(b, content); else b.textContent = content;
        const time = document.createElement('div');
        time.className = 'a-time'; time.textContent = fmtChatTime(ts);
        wrap.appendChild(b); wrap.appendChild(time);
        div.appendChild(av); div.appendChild(wrap);
        msgsEl.appendChild(div);
        msgsEl.scrollTop = msgsEl.scrollHeight;
        return { bubble: b };
    }

    const STATUS_LABELS = {
        queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', interrupted: '已中断',
    };
    const ACTIVE_STATUSES = new Set(['queued', 'running']);

    function currentExperimentId() {
        return window.ME && Number(window.ME.current_experiment_id);
    }
    function isCurrentTask(task) {
        const current = currentExperimentId();
        return !current || Number(task.experiment_id) === current;
    }
    function formatBytes(size) {
        const bytes = Number(size || 0);
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }
    function renderScriptMeta() {
        if (!currentScript) return;
        const latestRun = [...tasks.values()]
            .filter(task => task.kind === 'script' && Number(task.metadata?.file_id) === Number(currentScript.id))
            .sort((a, b) => (b.updated_at || b.created_at) - (a.updated_at || a.created_at))[0];
        let state = '已上传，尚未执行';
        if (latestRun?.status === 'queued') state = '等待执行';
        if (latestRun?.status === 'running') state = '正在执行';
        if (latestRun?.status === 'succeeded') state = '最近运行完成';
        if (latestRun?.status === 'failed') state = '最近运行失败';
        if (latestRun?.status === 'interrupted') state = '最近运行中断';
        panel.querySelector('#aScriptMeta').textContent = `${formatBytes(currentScript.size)} · ${state}`;
    }
    function taskIcon(kind) {
        if (kind === 'script') return '<path d="M8 5h8M9 3v5l-4 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 17l-4-9V3M8 14h8"/>';
        if (kind === 'upload') return '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>';
        return '<path d="M21 15a4 4 0 0 1-4 4H7l-4 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>';
    }
    function setThinking(bubble, text) {
        bubble.classList.remove('md');
        bubble.innerHTML = '<span class="a-typing"><i></i><i></i><i></i></span><span class="a-typing-text"></span>';
        bubble.querySelector('.a-typing-text').textContent = text || 'AI 正在处理…';
    }
    function renderChatTaskBubble(task) {
        let bubble = chatTaskBubbles.get(task.id);
        if (!bubble && ACTIVE_STATUSES.has(task.status)) {
            bubble = append('assistant', '', task.created_at).bubble;
            bubble.closest('.a-msg').dataset.taskId = task.id;
            chatTaskBubbles.set(task.id, bubble);
        }
        if (!bubble) return;
        if (task.status === 'failed' || task.status === 'interrupted') {
            bubble.classList.remove('md');
            bubble.textContent = '错误：' + (task.error || task.detail || '任务未完成');
        } else if (task.status === 'succeeded') {
            renderBubbleMarkdown(bubble, task.result || '（无回复）');
            window.dispatchEvent(new CustomEvent('chat:done'));
        } else if (task.result) {
            renderBubbleMarkdown(bubble, task.result);
            const status = document.createElement('div');
            status.className = 'a-tool-status';
            status.innerHTML = '<span class="a-typing"><i></i><i></i><i></i></span><span class="a-typing-text"></span>';
            status.querySelector('.a-typing-text').textContent = task.detail || '正在处理';
            bubble.appendChild(status);
        } else {
            setThinking(bubble, task.detail || 'AI 正在处理…');
        }
        msgsEl.scrollTop = msgsEl.scrollHeight;
    }
    function renderTasks() {
        const visible = [...tasks.values()].filter(isCurrentTask).sort((a, b) => b.created_at - a.created_at).slice(0, 8);
        taskCenter.hidden = !visible.length;
        const activeCount = visible.filter(task => ACTIVE_STATUSES.has(task.status)).length;
        panel.querySelector('#aActiveCount').textContent = activeCount ? `${activeCount} 进行中` : `${visible.length} 条`;
        tasksEl.innerHTML = visible.map(task => {
            const events = (task.events || []).slice(-4);
            const terminal = !ACTIVE_STATUSES.has(task.status);
            const result = task.result || task.error || '';
            return `<article class="task-item ${escapeHtml(task.status)}" data-task-id="${escapeHtml(task.id)}">
              <div class="task-item-head">
                <span class="task-kind-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">${taskIcon(task.kind)}</svg></span>
                <span class="task-title"><b>${escapeHtml(task.title)}</b><small>${escapeHtml(task.detail || '')}</small></span>
                <span class="task-status">${escapeHtml(STATUS_LABELS[task.status] || task.status)}</span>
              </div>
              <span class="task-progress"><i style="width:${Number(task.progress || 0)}%"></i></span>
              <details class="task-details" ${terminal && result ? '' : 'open'}>
                <summary>${terminal && result ? '查看结果与过程' : '执行过程'}</summary>
                <ol>${events.map(event => `<li><time>${fmtChatTime(event.created_at)}</time><span>${escapeHtml(event.content || '')}</span></li>`).join('')}</ol>
                ${result ? '<div class="task-result" data-task-result></div>' : ''}
              </details>
            </article>`;
        }).join('');
        tasksEl.querySelectorAll('[data-task-result]').forEach(element => {
            const task = tasks.get(element.closest('[data-task-id]').dataset.taskId);
            renderBubbleMarkdown(element, (task && (task.result || task.error)) || '');
        });
        renderScriptMeta();
        sendButton.disabled = visible.some(task => task.kind === 'chat' && ACTIVE_STATUSES.has(task.status));
        panel.querySelector('#aRunScript').disabled = !currentScript || visible.some(task => task.kind === 'script' && ACTIVE_STATUSES.has(task.status));
        panel.querySelector('#aComposerState').textContent = sendButton.disabled ? '对话任务执行中' : '可发送新任务';
    }
    function handleTask(task) {
        if (!task || !task.id) return;
        tasks.set(task.id, task);
        if (task.kind === 'chat' && isCurrentTask(task)) renderChatTaskBubble(task);
        renderTasks();
        window.dispatchEvent(new CustomEvent('task:update', { detail: task }));
    }
    async function loadTasks() {
        try {
            const response = await API.tasks();
            tasks.clear();
            (response.tasks || []).forEach(task => tasks.set(task.id, task));
            (response.tasks || []).filter(task => task.kind === 'chat' && ACTIVE_STATUSES.has(task.status)).forEach(renderChatTaskBubble);
            renderTasks();
        } catch (_) { /* websocket reconnect will retry */ }
    }
    function connectTaskSocket() {
        if (taskSocket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(taskSocket.readyState)) return;
        if (taskRetryTimer) { clearTimeout(taskRetryTimer); taskRetryTimer = null; }
        const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
        const socket = new WebSocket(`${protocol}://${location.host}/ws/tasks`);
        taskSocket = socket;
        socket.onopen = () => {
            taskRetryDelay = 1000;
            window.dispatchEvent(new CustomEvent('task-socket:state', { detail: { connected: true } }));
        };
        socket.onmessage = event => {
            try {
                const payload = JSON.parse(event.data);
                if (payload.type === 'task_snapshot') {
                    tasks.clear();
                    (payload.tasks || []).forEach(task => tasks.set(task.id, task));
                    (payload.tasks || []).filter(task => task.kind === 'chat' && ACTIVE_STATUSES.has(task.status)).forEach(renderChatTaskBubble);
                    renderTasks();
                    window.dispatchEvent(new CustomEvent('task:snapshot', { detail: payload.tasks || [] }));
                } else if (payload.type === 'task_update') {
                    handleTask(payload.task);
                } else if (payload.type === 'workspace_task_update') {
                    window.dispatchEvent(new CustomEvent('task:update', { detail: payload.task }));
                }
            } catch (_) { /* ignore malformed events */ }
        };
        socket.onclose = () => {
            if (taskSocket !== socket) return;
            taskSocket = null;
            window.dispatchEvent(new CustomEvent('task-socket:state', { detail: { connected: false } }));
            taskRetryTimer = setTimeout(connectTaskSocket, taskRetryDelay);
            taskRetryDelay = Math.min(taskRetryDelay * 2, 30000);
        };
    }

    panel.querySelector('#aTaskToggle').onclick = event => {
        const button = event.currentTarget;
        const collapsed = taskCenter.classList.toggle('collapsed');
        button.setAttribute('aria-expanded', String(!collapsed));
    };

    function showScript(script) {
        currentScript = script || null;
        panel.querySelector('#aScriptPicker').hidden = !!currentScript;
        panel.querySelector('#aScriptCurrent').hidden = !currentScript;
        panel.querySelector('#aRunPanel').hidden = !currentScript;
        if (currentScript) {
            panel.querySelector('#aScriptName').textContent = currentScript.original_name;
            renderScriptMeta();
            const canRun = currentScript.original_name.toLowerCase().endsWith('.py');
            panel.querySelector('#aRunScript').hidden = !canRun;
        }
        renderTasks();
    }
    async function loadCurrentScript() {
        try { showScript((await API.currentScript()).script); } catch (_) { showScript(null); }
    }
    async function uploadFile(file) {
        if (!file) return;
        const progress = panel.querySelector('#aUploadProgress');
        const bar = panel.querySelector('#aUploadBar');
        const percent = panel.querySelector('#aUploadPercent');
        progress.hidden = false;
        panel.querySelector('#aScriptPicker').hidden = true;
        bar.style.width = '0%'; percent.textContent = '0%';
        try {
            const response = await API.uploadWithProgress(file, value => {
                bar.style.width = value + '%'; percent.textContent = value + '%';
            });
            bar.style.width = '100%'; percent.textContent = '100%';
            if (response.task) handleTask(response.task);
            showScript(response.script);
        } catch (error) {
            showScript(currentScript);
            panel.querySelector('#aComposerState').textContent = '上传失败：' + error.message;
        } finally {
            setTimeout(() => { progress.hidden = true; }, 500);
            fileEl.value = '';
        }
    }
    panel.querySelector('#aScriptPicker').onclick = () => fileEl.click();
    panel.querySelector('#aReplaceScript').onclick = () => fileEl.click();
    fileEl.onchange = () => uploadFile(fileEl.files[0]);
    const workspace = panel.querySelector('.script-workspace');
    workspace.ondragover = event => { event.preventDefault(); workspace.classList.add('dragging'); };
    workspace.ondragleave = () => workspace.classList.remove('dragging');
    workspace.ondrop = event => {
        event.preventDefault(); workspace.classList.remove('dragging'); uploadFile(event.dataTransfer.files[0]);
    };
    panel.querySelector('#aRunScript').onclick = async () => {
        if (!currentScript) return;
        const button = panel.querySelector('#aRunScript');
        button.disabled = true;
        try {
            const response = await API.runScript(currentScript.id, {
                arch: panel.querySelector('#aRunArch').value,
                hostname: panel.querySelector('#aRunHost').value.trim(),
                timeout: Number(panel.querySelector('#aRunTimeout').value || 120),
            });
            handleTask(response.task);
            taskCenter.classList.remove('collapsed');
            panel.querySelector('#aTaskToggle').setAttribute('aria-expanded', 'true');
        } catch (error) {
            panel.querySelector('#aComposerState').textContent = '启动失败：' + error.message;
        } finally {
            renderTasks();
        }
    };

    // 建议 chips
    suggestEl.innerHTML = SUGGESTIONS.map(s => `<button class="suggest-chip">${s}</button>`).join('');
    suggestEl.querySelectorAll('.suggest-chip').forEach(c => {
        c.onclick = () => { textEl.value = c.textContent; textEl.focus(); };
    });

    panel.querySelector('#aClear').onclick = async () => {
        const activeChat = [...tasks.values()].some(task => isCurrentTask(task) && task.kind === 'chat' && ACTIVE_STATUSES.has(task.status));
        if (activeChat) { alert('当前对话任务仍在执行，请等待任务结束后清空'); return; }
        if (!confirm('清空所有对话上下文？')) return;
        await API.clearChat(); msgsEl.innerHTML = ''; chatTaskBubbles.clear(); showSuggest();
    };
    function showSuggest() { suggestEl.style.display = msgsEl.children.length ? 'none' : 'flex'; }

    async function send() {
        const text = textEl.value.trim();
        if (!text || sendButton.disabled) return;
        textEl.value = '';
        append('user', text);
        const pendingBubble = append('assistant', '').bubble;
        setThinking(pendingBubble, '任务正在排队…');
        sendButton.disabled = true;
        showSuggest();
        try {
            const response = await API.startChatTask(text);
            const task = response.task;
            const existing = chatTaskBubbles.get(task.id);
            if (existing && existing !== pendingBubble) pendingBubble.closest('.a-msg').remove();
            else {
                pendingBubble.closest('.a-msg').dataset.taskId = task.id;
                chatTaskBubbles.set(task.id, pendingBubble);
            }
            handleTask(task);
        } catch (error) {
            pendingBubble.classList.remove('md');
            pendingBubble.textContent = '错误：' + error.message;
            sendButton.disabled = false;
        }
    }
    sendButton.onclick = send;
    textEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });

    async function reloadHistory() {
        msgsEl.innerHTML = '';
        chatTaskBubbles.clear();
        try {
            const r = await API.chatHistory();
            (r.history || []).forEach(h => { if (h.role === 'user' || h.role === 'assistant') append(h.role, h.content, h.created_at); });
            await MD.ready();
            msgsEl.querySelectorAll('.a-msg.assistant .a-bubble').forEach(b => { if (b.dataset.md != null) renderBubbleMarkdown(b, b.dataset.md); });
        } catch (_) { /* noop */ }
        [...tasks.values()].filter(task => task.kind === 'chat' && isCurrentTask(task) && ACTIVE_STATUSES.has(task.status)).forEach(renderChatTaskBubble);
        showSuggest();
    }
    reloadHistory();
    loadTasks();
    loadCurrentScript();
    connectTaskSocket();
    window.addEventListener('online', connectTaskSocket);
    window.addEventListener('experiment:changed', () => {
        reloadHistory(); loadTasks(); loadCurrentScript();
    });
    window.addEventListener('keydown', e => { if (e.key === 'Escape' && panel.classList.contains('open')) close(); });
}
window.addEventListener('DOMContentLoaded', injectAssistant);
