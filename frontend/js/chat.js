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
                if (!window.marked) await _load('https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js');
                if (!window.DOMPurify) await _load('https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js');
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
      <div class="assistant-suggest" id="aSuggest"></div>
      <div class="assistant-input">
        <div class="upload-hint" id="aHint"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg><span id="aHintText">未上传脚本</span></div>
        <div class="in-wrap"><textarea id="aText" placeholder="用自然语言描述你的需求，例如：创建一个 riscv 架构机器上的 Ubuntu SSH 系统"></textarea></div>
        <div class="in-row">
          <label class="file-lbl"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>上传 .py
            <input type="file" id="aFile" style="display:none" accept=".py,.txt,.json,.yaml,.yml,.sh" />
          </label>
          <button class="primary send" id="aSend">发送</button>
        </div>
      </div>`;
    document.body.appendChild(panel);

    const msgsEl = panel.querySelector('#aMsgs');
    const textEl = panel.querySelector('#aText');
    const fileEl = panel.querySelector('#aFile');
    const hintText = panel.querySelector('#aHintText');
    const suggestEl = panel.querySelector('#aSuggest');

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

    // 建议 chips
    suggestEl.innerHTML = SUGGESTIONS.map(s => `<button class="suggest-chip">${s}</button>`).join('');
    suggestEl.querySelectorAll('.suggest-chip').forEach(c => {
        c.onclick = () => { textEl.value = c.textContent; textEl.focus(); };
    });

    panel.querySelector('#aClear').onclick = async () => {
        if (!confirm('清空所有对话上下文？')) return;
        await API.clearChat(); msgsEl.innerHTML = ''; showSuggest();
    };
    function showSuggest() { suggestEl.style.display = msgsEl.children.length ? 'none' : 'flex'; }

    fileEl.onchange = async () => {
        if (!fileEl.files[0]) return;
        try {
            const r = await API.upload_(fileEl.files[0]);
            hintText.textContent = '已上传：' + r.filename;
            hintText.parentElement.style.color = 'var(--success)';
        } catch (e) {
            hintText.textContent = '上传失败：' + e.message;
            hintText.parentElement.style.color = 'var(--danger)';
        }
    };

    async function send() {
        const t = textEl.value.trim();
        if (!t) return;
        textEl.value = '';
        append('user', t);
        showSuggest();

        const { bubble } = append('assistant', '');
        // 生成中指示器：三点跳动 + 状态文案，直到首个正文 token 到达
        function setThinking(text) {
            bubble.classList.remove('md');
            bubble.innerHTML = `<span class="a-typing"><i></i><i></i><i></i></span><span class="a-typing-text"></span>`;
            bubble.querySelector('.a-typing-text').textContent = text || 'AI 正在思考…';
            msgsEl.scrollTop = msgsEl.scrollHeight;
        }
        setThinking('AI 正在思考…');

        let started = false, acc = '', renderTimer = null;
        const scheduleRender = (force) => {
            if (force) { if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; } renderBubbleMarkdown(bubble, acc); msgsEl.scrollTop = msgsEl.scrollHeight; return; }
            if (renderTimer) return;
            renderTimer = setTimeout(() => { renderTimer = null; renderBubbleMarkdown(bubble, acc); msgsEl.scrollTop = msgsEl.scrollHeight; }, 60);
        };
        function showStatus(text) {
            if (!started) { setThinking(text); return; }
            scheduleRender(true);
            const status = document.createElement('div');
            status.className = 'a-tool-status';
            status.innerHTML = '<span class="a-typing"><i></i><i></i><i></i></span><span class="a-typing-text"></span>';
            status.querySelector('.a-typing-text').textContent = text;
            bubble.appendChild(status);
            msgsEl.scrollTop = msgsEl.scrollHeight;
        }

        try {
            const resp = await fetch('/api/chat/stream', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: t }),
            });
            if (resp.status === 401) { window.location.href = '/login.html'; return; }
            if (!resp.ok) { const d = await resp.json().catch(() => ({})); bubble.classList.remove('md'); bubble.textContent = '错误：' + (d.error || 'HTTP ' + resp.status); return; }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            outer: while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += decoder.decode(value, { stream: true });
                let idx;
                while ((idx = buf.indexOf('\n\n')) !== -1) {
                    const raw = buf.slice(0, idx); buf = buf.slice(idx + 2);
                    if (!raw.startsWith('data: ')) continue;
                    const payload = raw.slice(6);
                    if (payload === '[DONE]') break outer;
                    let parsed; try { parsed = JSON.parse(payload); } catch { continue; }
                    if (parsed.error) { bubble.classList.remove('md'); bubble.textContent = '错误：' + parsed.error; break outer; }
                    // 工具调用前模型可能已输出引导语；此时在正文下方追加临时进度行
                    if (parsed.status) { showStatus(parsed.status); continue; }
                    if (parsed.delta) {
                        bubble.querySelector('.a-tool-status')?.remove();
                        if (!started) { acc = ''; started = true; }
                        acc += parsed.delta; scheduleRender(false);
                    }
                }
            }
            await MD.ready();
            if (started) scheduleRender(true);
            else { bubble.classList.remove('md'); bubble.textContent = '（无回复）'; }
            window.dispatchEvent(new CustomEvent('chat:done'));
        } catch (e) { bubble.classList.remove('md'); bubble.textContent = '错误：' + e.message; }
    }
    panel.querySelector('#aSend').onclick = send;
    textEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });

    async function reloadHistory() {
        msgsEl.innerHTML = '';
        try {
            const r = await API.chatHistory();
            (r.history || []).forEach(h => { if (h.role === 'user' || h.role === 'assistant') append(h.role, h.content, h.created_at); });
            await MD.ready();
            msgsEl.querySelectorAll('.a-msg.assistant .a-bubble').forEach(b => { if (b.dataset.md != null) renderBubbleMarkdown(b, b.dataset.md); });
        } catch (_) { /* noop */ }
        showSuggest();
    }
    reloadHistory();
    window.addEventListener('experiment:changed', reloadHistory);
    window.addEventListener('keydown', e => { if (e.key === 'Escape' && panel.classList.contains('open')) close(); });
}
window.addEventListener('DOMContentLoaded', injectAssistant);
