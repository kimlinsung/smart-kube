// 全局对话弹窗：所有页面通用。
function injectChat() {
    const fab = document.createElement('button');
    fab.className = 'chat-fab'; fab.textContent = '💬'; fab.title = 'AI 助手';
    document.body.appendChild(fab);

    const panel = document.createElement('div');
    panel.className = 'chat-panel';
    panel.innerHTML = `
      <div class="chat-head">
        <span>👌 端边云(CED) Chat</span>
        <span class="actions">
          <button id="chatClear" title="清除上下文">清空</button>
          <button id="chatClose">×</button>
        </span>
      </div>
      <div class="chat-msgs" id="chatMsgs"></div>
      <div class="chat-input">
        <div class="upload-hint" id="uploadHint">未上传脚本</div>
        <textarea id="chatText" placeholder="例如：创建一个riscv架构机器上的Ubuntu SSH可用系统"></textarea>
        <div class="row">
          <label>📎 上传 .py
            <input type="file" id="chatFile" style="display:none" accept=".py,.txt,.json,.yaml,.yml,.sh" />
          </label>
          <button class="send" id="chatSend">发送</button>
        </div>
      </div>`;
    document.body.appendChild(panel);

    const msgsEl = panel.querySelector('#chatMsgs');
    const textEl = panel.querySelector('#chatText');
    const fileEl = panel.querySelector('#chatFile');
    const hintEl = panel.querySelector('#uploadHint');

    const open = () => { panel.classList.add('open'); msgsEl.scrollTop = msgsEl.scrollHeight; };
    const close = () => panel.classList.remove('open');
    fab.onclick = () => panel.classList.toggle('open');
    panel.querySelector('#chatClose').onclick = close;

    function fmtChatTime(ts) {
        const d = ts ? new Date(ts * 1000) : new Date();
        const pad = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ` +
               `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }

    function append(role, content, ts) {
        const div = document.createElement('div');
        div.className = 'chat-msg ' + role;
        const wrap = document.createElement('div');
        wrap.className = 'chat-bubble-wrap';
        const b = document.createElement('div');
        b.className = 'chat-bubble'; b.textContent = content;
        const time = document.createElement('div');
        time.className = 'chat-time'; time.textContent = fmtChatTime(ts);
        wrap.appendChild(b);
        wrap.appendChild(time);
        div.appendChild(wrap);
        msgsEl.appendChild(div);
        msgsEl.scrollTop = msgsEl.scrollHeight;
        return { bubble: b, time };
    }

    panel.querySelector('#chatClear').onclick = async () => {
        if (!confirm('清空所有对话上下文？')) return;
        await API.clearChat(); msgsEl.innerHTML = '';
    };

    fileEl.onchange = async () => {
        if (!fileEl.files[0]) return;
        try {
            const r = await API.upload_(fileEl.files[0]);
            hintEl.textContent = '已上传：' + r.filename;
            hintEl.style.color = '#059669';
        } catch (e) {
            hintEl.textContent = '上传失败：' + e.message;
            hintEl.style.color = '#dc2626';
        }
    };
    panel.querySelector('label[for]'); // noop

    async function send() {
        const t = textEl.value.trim();
        if (!t) return;
        textEl.value = '';
        append('user', t);

        // 创建助手气泡（占位）
        const div = document.createElement('div');
        div.className = 'chat-msg assistant';
        const wrap = document.createElement('div');
        wrap.className = 'chat-bubble-wrap';
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        bubble.textContent = '思考中...';
        const timeEl = document.createElement('div');
        timeEl.className = 'chat-time';
        timeEl.textContent = fmtChatTime();
        wrap.appendChild(bubble);
        wrap.appendChild(timeEl);
        div.appendChild(wrap);
        msgsEl.appendChild(div);
        msgsEl.scrollTop = msgsEl.scrollHeight;

        let started = false;
        try {
            const resp = await fetch('/api/chat/stream', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: t }),
            });
            if (resp.status === 401) { window.location.href = '/login.html'; return; }
            if (!resp.ok) {
                const d = await resp.json().catch(() => ({}));
                bubble.textContent = '错误：' + (d.error || 'HTTP ' + resp.status);
                return;
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            outer: while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += decoder.decode(value, { stream: true });
                let idx;
                while ((idx = buf.indexOf('\n\n')) !== -1) {
                    const raw = buf.slice(0, idx);
                    buf = buf.slice(idx + 2);
                    if (!raw.startsWith('data: ')) continue;
                    const payload = raw.slice(6);
                    if (payload === '[DONE]') break outer;
                    let parsed;
                    try { parsed = JSON.parse(payload); } catch { continue; }
                    if (parsed.error) { bubble.textContent = '错误：' + parsed.error; break outer; }
                    if (parsed.delta) {
                        if (!started) { bubble.textContent = ''; started = true; }
                        bubble.textContent += parsed.delta;
                        msgsEl.scrollTop = msgsEl.scrollHeight;
                    }
                }
            }
            if (!started) bubble.textContent = '（无回复）';
            window.dispatchEvent(new CustomEvent('chat:done'));
        } catch (e) {
            bubble.textContent = '错误：' + e.message;
        }
    }
    panel.querySelector('#chatSend').onclick = send;
    textEl.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });

    function reloadHistory() {
        msgsEl.innerHTML = '';
        return API.chatHistory().then(r => {
            (r.history || []).forEach(h => {
                if (h.role === 'user' || h.role === 'assistant') append(h.role, h.content, h.created_at);
            });
        }).catch(()=>{});
    }
    reloadHistory();
    window.addEventListener('experiment:changed', reloadHistory);
}
window.addEventListener('DOMContentLoaded', injectChat);
