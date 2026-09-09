window.createInventoryView = (bodyId, kind) => {
    const body = document.getElementById(bodyId), section = body.closest('.card');
    section.classList.add('resource-console');
    const controls = document.createElement('div'); controls.className = 'inventory-controls';
    controls.innerHTML = `<div class="inventory-tabs" role="tablist" aria-label="资源状态"><button role="tab" data-status="all" aria-selected="true">全部 <span>0</span></button><button role="tab" data-status="ready" aria-selected="false">${kind === 'nodes' ? '可调度' : '运行中'} <span>0</span></button><button role="tab" data-status="attention" aria-selected="false">需关注 <span>0</span></button></div><div class="inventory-toolbar"><label>${icon('node')}<input type="search" placeholder="${kind === 'nodes' ? '搜索节点名称、IP、架构' : '搜索实例名称、用户、节点'}" aria-label="搜索资源" /></label><select data-tier aria-label="资源层级"><option value="">全部层级</option><option value="cloud">云</option><option value="edge">边</option><option value="device">端</option></select><select data-arch aria-label="架构"><option value="">全部架构</option></select><select data-sort aria-label="排序"><option value="name">名称 A–Z</option><option value="attention">异常优先</option></select><span class="inventory-updated"></span></div>`;
    section.insertBefore(controls, section.querySelector('.card-body'));
    const footer = document.createElement('div'); footer.className = 'inventory-pagination';
    footer.innerHTML = '<span role="status"></span><label>每页 <select aria-label="每页条数"><option>20</option><option>50</option><option>100</option></select></label><button data-prev aria-label="上一页" title="上一页">‹</button><b></b><button data-next aria-label="下一页" title="下一页">›</button>';
    section.appendChild(footer);
    let rows = [], status = 'all', page = 1;
    const ready = row => kind === 'nodes' ? row.ready === 'True' && !row.unschedulable : row.phase === 'Running';
    function render() {
        const query = controls.querySelector('input').value.trim().toLowerCase();
        const tier = controls.querySelector('[data-tier]').value, arch = controls.querySelector('[data-arch]').value;
        const selected = rows.filter(row => (!tier || row.node_type === tier) && (!arch || row.arch === arch)
            && (status === 'all' || ready(row) === (status === 'ready'))
            && [row.name, row.hostname, row.internal_ip, row.node, row.owner_username, row.arch].join(' ').toLowerCase().includes(query));
        selected.sort((a, b) => (controls.querySelector('[data-sort]').value === 'attention' ? Number(ready(a)) - Number(ready(b)) : 0) || a.name.localeCompare(b.name));
        const size = Number(footer.querySelector('select').value), pages = Math.max(1, Math.ceil(selected.length / size));
        page = Math.min(page, pages);
        const names = new Set(selected.slice((page - 1) * size, page * size).map(row => row.name));
        const positions = new Map(selected.map((row, index) => [row.name, index]));
        const tableRows = [...body.rows].filter(tr => !tr.classList.contains('nt-group') && !tr.classList.contains('filter-empty'));
        tableRows.sort((a, b) => (positions.get(a.querySelector('[data-name]')?.dataset.name) ?? Infinity) - (positions.get(b.querySelector('[data-name]')?.dataset.name) ?? Infinity));
        for (const tr of tableRows) {
            const name = tr.querySelector('[data-name]')?.dataset.name;
            if (name) { tr.hidden = !names.has(name); body.appendChild(tr); }
        }
        body.querySelectorAll('.nt-group').forEach(tr => tr.remove());
        body.querySelector('.filter-empty')?.remove();
        if (rows.length && !selected.length) body.insertAdjacentHTML('beforeend', `<tr class="filter-empty"><td colspan="${body.closest('table').tHead.rows[0].cells.length}">没有符合筛选条件的资源</td></tr>`);
        controls.querySelectorAll('[data-status]').forEach(button => {
            button.setAttribute('aria-selected', String(button.dataset.status === status));
            button.querySelector('span').textContent = button.dataset.status === 'all' ? rows.length : rows.filter(row => ready(row) === (button.dataset.status === 'ready')).length;
        });
        footer.querySelector('[role=status]').textContent = `共 ${selected.length} 条`;
        footer.querySelector('b').textContent = `${page} / ${pages}`;
        footer.querySelector('[data-prev]').disabled = page <= 1; footer.querySelector('[data-next]').disabled = page >= pages;
        body.dispatchEvent(new CustomEvent('resource:visibility'));
    }
    controls.querySelectorAll('input,select').forEach(input => input.addEventListener(input.tagName === 'INPUT' ? 'input' : 'change', () => { page = 1; render(); }));
    controls.querySelectorAll('[data-status]').forEach(button => button.onclick = () => { status = button.dataset.status; page = 1; render(); });
    controls.querySelector('.inventory-tabs').onkeydown = event => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        const buttons = [...controls.querySelectorAll('[data-status]')], index = buttons.indexOf(document.activeElement);
        event.preventDefault(); const next = buttons[(index + (event.key === 'ArrowRight' ? 1 : 2)) % 3]; next.focus(); next.click();
    };
    footer.querySelector('select').onchange = () => { page = 1; render(); };
    footer.querySelector('[data-prev]').onclick = () => { page--; render(); };
    footer.querySelector('[data-next]').onclick = () => { page++; render(); };
    return {update(value) {
        rows = value;
        const arch = controls.querySelector('[data-arch]'), previous = arch.value;
        arch.innerHTML = '<option value="">全部架构</option>' + [...new Set(rows.map(row => row.arch).filter(Boolean))].sort().map(value => `<option>${escapeHtml(value)}</option>`).join('');
        arch.value = [...arch.options].some(option => option.value === previous) ? previous : '';
        controls.querySelector('.inventory-updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN', {hour12: false});
        render();
    }};
};
