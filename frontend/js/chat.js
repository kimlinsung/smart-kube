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

    const open = () => panel.classList.add('open');
    const close = () => panel.classList.remove('open');
    fab.onclick = () => panel.classList.toggle('open');
    panel.querySelector('#chatClose').onclick = close;

    function append(role, content) {
        const div = document.createElement('div');
        div.className = 'chat-msg ' + role;
        const b = document.createElement('div');
        b.className = 'chat-bubble'; b.textContent = content;
        div.appendChild(b); msgsEl.appendChild(div);
        msgsEl.scrollTop = msgsEl.scrollHeight;
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
        append('user', t); textEl.value = '';
        append('assistant', '思考中...');
        const lastBubble = msgsEl.lastChild.querySelector('.chat-bubble');
        try {
            const r = await API.chat(t);
            lastBubble.textContent = r.reply;
            // 操作后通知 dashboard 刷新资源
            window.dispatchEvent(new CustomEvent('chat:done'));
        } catch (e) {
            lastBubble.textContent = '错误：' + e.message;
        }
    }
    panel.querySelector('#chatSend').onclick = send;
    textEl.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });

    // 加载历史
    API.chatHistory().then(r => {
        (r.history || []).forEach(h => {
            if (h.role === 'user' || h.role === 'assistant') append(h.role, h.content);
        });
    }).catch(()=>{});
}
window.addEventListener('DOMContentLoaded', injectChat);
