window.Collaboration = (() => {
    let active = null;
    function open(experimentId, title) {
        active?.close();
        const trigger = document.activeElement;
        const dialog = document.createElement('dialog');
        dialog.className = 'console-dialog collaboration-dialog';
        dialog.setAttribute('aria-labelledby', 'collaborationTitle');
        dialog.innerHTML = `<header><div><span class="dialog-eyebrow">COLLABORATION</span><h2 id="collaborationTitle">协作与分享</h2><p>${escapeHtml(title || '')}</p></div><button type="button" class="icon-btn" data-close aria-label="关闭" title="关闭">×</button></header>
          <div class="dialog-content"><p class="dialog-error" role="alert"></p>
            <section><h3>邀请协作者 <span class="muted">只读权限</span></h3><div class="people-search"><label for="candidateSearch">姓名或用户名</label><input id="candidateSearch" type="search" placeholder="搜索姓名或用户名" maxlength="80" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="candidateList" /><div id="candidateList" class="candidate-list" role="listbox" aria-label="候选人" hidden></div><span class="search-status" role="status"></span></div><div class="people-list" aria-label="已有协作者"></div></section>
            <section class="public-share"><div><h3>公开只读链接</h3><p>持有链接的人可查看实验结果与下载归档文件。</p></div><label class="switch"><input type="checkbox" aria-label="开启公开分享" disabled /><span></span></label><div class="share-address" hidden><input readonly aria-label="分享链接" /><button type="button" data-copy title="复制分享链接">复制链接</button></div></section>
          </div><footer><span data-member-count></span><button type="button" data-close>完成</button></footer>`;
        document.body.appendChild(dialog); active = dialog;
        const $ = selector => dialog.querySelector(selector);
        const input = $('#candidateSearch'), candidates = $('#candidateList'), error = $('.dialog-error');
        let data = null, timer, sequence = 0, busy = false;
        function clearCandidates() {
            candidates.hidden = true; candidates.innerHTML = ''; input.setAttribute('aria-expanded', 'false');
        }
        function render() {
            const members = data.collaborators || [];
            $('.people-list').innerHTML = members.map(item => `<div class="person-row"><span class="person-avatar">${escapeHtml((item.name || item.username).slice(0, 1))}</span><span class="person-copy"><b>${escapeHtml(item.name || item.username)}</b><small>@${escapeHtml(item.username)}</small></span><span class="person-role">协作者</span><button type="button" data-remove="${item.user_id}" title="移除 ${escapeHtml(item.username)}" aria-label="移除 ${escapeHtml(item.username)}">×</button></div>`).join('') || '<p class="people-empty">暂无协作者</p>';
            $('[data-member-count]').textContent = `${members.length} 位协作者`;
            $('.switch input').checked = !!data.share?.enabled; $('.switch input').disabled = false;
            $('.share-address').hidden = !data.share?.enabled;
            $('.share-address input').value = data.share?.url || '';
        }
        async function mutate(action) {
            if (busy) return;
            busy = true; error.textContent = ''; sequence++; clearTimeout(timer); clearCandidates();
            dialog.querySelectorAll('button:not([data-close]), .switch input, #candidateSearch').forEach(el => el.disabled = true);
            try { await action(); if (dialog.open) { data = await API.experimentSharing(experimentId); render(); } }
            catch (err) { error.textContent = err.message; if (data) render(); }
            finally { busy = false; dialog.querySelectorAll('button, #candidateSearch').forEach(el => el.disabled = false); }
        }
        input.oninput = () => {
            clearTimeout(timer); clearCandidates(); const ticket = ++sequence, query = input.value.trim();
            $('.search-status').textContent = query.length < 2 ? '至少输入 2 个字符' : '正在搜索…';
            if (query.length < 2) return;
            timer = setTimeout(async () => {
                try {
                    const result = await API.collaborationCandidates(experimentId, query);
                    if (ticket !== sequence || !dialog.open) return;
                    const people = result.candidates || [];
                    candidates.innerHTML = people.map(person => `<button type="button" role="option" aria-selected="false" data-username="${escapeHtml(person.username)}"><span class="person-avatar">${escapeHtml((person.name || person.username).slice(0, 1))}</span><span class="person-copy"><b>${escapeHtml(person.name || person.username)}</b><small>@${escapeHtml(person.username)}</small></span><span>添加</span></button>`).join('');
                    candidates.hidden = !people.length; input.setAttribute('aria-expanded', String(!!people.length));
                    $('.search-status').textContent = people.length ? `${people.length} 位候选人` : '没有匹配的候选人';
                } catch (err) { if (ticket === sequence) $('.search-status').textContent = err.message; }
            }, 250);
        };
        input.onkeydown = event => { if (event.key === 'ArrowDown' && !candidates.hidden) { event.preventDefault(); candidates.querySelector('button')?.focus(); } };
        candidates.onkeydown = event => {
            const buttons = [...candidates.querySelectorAll('button')], index = buttons.indexOf(document.activeElement);
            if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); buttons[(index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length]?.focus(); }
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); clearCandidates(); input.focus(); }
        };
        candidates.onclick = event => {
            const button = event.target.closest('[data-username]'); if (!button) return;
            mutate(async () => { await API.addExperimentCollaborator(experimentId, button.dataset.username); input.value = ''; $('.search-status').textContent = '已添加协作者'; });
        };
        $('.people-list').onclick = event => {
            const button = event.target.closest('[data-remove]');
            if (button && confirm('确认移除此协作者的访问权限？')) mutate(() => API.removeExperimentCollaborator(experimentId, button.dataset.remove));
        };
        $('.switch input').onchange = event => {
            const enabled = event.target.checked;
            if (!confirm(enabled ? '开启后，任何持有链接的人都能访问实验归档。确认开启？' : '关闭后原分享链接立即失效。确认关闭？')) { render(); return; }
            mutate(() => enabled ? API.enableExperimentShare(experimentId) : API.disableExperimentShare(experimentId));
        };
        $('[data-copy]').onclick = async () => {
            try {
                if (navigator.clipboard && isSecureContext) await navigator.clipboard.writeText($('.share-address input').value);
                else { $('.share-address input').select(); if (!document.execCommand('copy')) throw new Error('复制失败，请选中链接复制'); }
                $('[data-copy]').textContent = '已复制';
            } catch (err) { error.textContent = err.message; }
        };
        dialog.querySelectorAll('[data-close]').forEach(button => button.onclick = () => dialog.close());
        dialog.addEventListener('close', () => { sequence++; clearTimeout(timer); dialog.remove(); if (active === dialog) active = null; trigger?.focus(); window.dispatchEvent(new CustomEvent('collaboration:changed', {detail: {experimentId}})); }, {once: true});
        dialog.showModal();
        input.disabled = true;
        $('.people-list').textContent = '正在加载协作者…';
        API.experimentSharing(experimentId).then(result => { if (dialog.open) { data = result; render(); input.disabled = false; } }).catch(err => { error.textContent = err.message; $('.people-list').textContent = ''; });
    }
    return {open};
})();
