window.createInventoryView = (bodyId, kind) => {
    const body=document.getElementById(bodyId), section=body.closest('.card'), content=section.parentElement;
    const head=document.createElement('section');head.className='inventory-overview';
    head.innerHTML=`<div class="inventory-heading"><div><span>TESTBED / ${kind==='nodes'?'COMPUTE FABRIC':'EXECUTION UNITS'}</span><h1>${kind==='nodes'?'算力基础设施':'运行实例'}</h1></div><span class="inventory-updated"></span></div><div class="inventory-metrics"></div><div class="inventory-toolbar"><label>${icon('node')}<input type="search" placeholder="${kind==='nodes'?'搜索节点、架构、IP':'搜索实例、用户、节点'}" aria-label="搜索资源" /></label><select aria-label="资源层级"><option value="">全部层级</option><option value="cloud">云 Cloud</option><option value="edge">边 Edge</option><option value="device">端 Device</option></select><div class="inventory-modes"><button type="button" data-mode="table" aria-pressed="true" title="表格视图" aria-label="表格视图">${icon('server')}</button><button type="button" data-mode="grid" aria-pressed="false" title="网格视图" aria-label="网格视图">${icon('dashboard')}</button></div></div>`;
    content.insertBefore(head,section);
    const grid=document.createElement('div');grid.className='inventory-grid';grid.hidden=true;content.insertBefore(grid,section);
    let rows=[],mode='table';
    const ready=row=>kind==='nodes'?row.ready==='True'&&!row.unschedulable:row.phase==='Running';
    const matches=row=>(!head.querySelector('select').value||row.node_type===head.querySelector('select').value)&&[row.name,row.hostname,row.internal_ip,row.node,row.owner_username,row.arch].join(' ').toLowerCase().includes(head.querySelector('input').value.toLowerCase());
    function render() {
        const selected=rows.filter(matches);
        const totals=[['已登记',rows.length,'box'],[kind==='nodes'?'可调度':'运行中',rows.filter(ready).length,'check'],['需关注',rows.filter(row=>!ready(row)).length,'node'],['架构类型',new Set(rows.map(row=>row.arch).filter(Boolean)).size,'layers']];
        head.querySelector('.inventory-metrics').innerHTML=totals.map(([label,count,ico])=>`<article>${icon(ico)}<span>${label}</span><b>${count}</b></article>`).join('');
        section.hidden=mode!=='table';grid.hidden=mode!=='grid';
        for(const tr of body.rows) {
            const name=tr.querySelector('button[data-name]')?.dataset.name;
            if(name)tr.hidden=!selected.some(row=>row.name===name);
        }
        for(const tr of body.querySelectorAll('.nt-group')) {let next=tr.nextElementSibling, visible=false;while(next&&!next.classList.contains('nt-group')){visible ||= !next.hidden;next=next.nextElementSibling;}tr.hidden=!visible;}
        grid.innerHTML=selected.map(row=>`<article class="inventory-item"><header><span class="inventory-node-icon">${icon(kind==='nodes'?'server':'box')}</span>${badgeNodeType(row.node_type)}<i class="inventory-status ${ready(row)?'ready':''}"></i></header><h2>${escapeHtml(row.name)}</h2><p>${escapeHtml(kind==='nodes'?row.hostname || row.internal_ip || '':row.owner_username || '')}</p><dl><div><dt>架构</dt><dd>${escapeHtml(row.arch || '—')}</dd></div><div><dt>${kind==='nodes'?'状态':'落位节点'}</dt><dd>${escapeHtml(kind==='nodes'?(row.unschedulable?'已封锁':row.ready==='True'?'Ready':'NotReady'):row.node || '待调度')}</dd></div></dl><footer>${[...body.querySelectorAll('button[data-name]')].filter(b=>b.dataset.name===row.name).map(b=>`<button type="button" data-inventory-action="${escapeHtml(b.dataset.act||'delete')}" data-name="${escapeHtml(row.name)}" class="${b.classList.contains('danger')?'danger':''}">${escapeHtml(b.textContent)}</button>`).join('')}</footer></article>`).join('')||'<div class="inventory-empty">没有符合条件的资源</div>';
    }
    head.querySelector('input').oninput=render;head.querySelector('select').onchange=render;
    head.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>{mode=button.dataset.mode;head.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));render();});
    grid.onclick=event=>{const b=event.target.closest('[data-inventory-action]');if(!b)return;const target=[...body.querySelectorAll('button[data-name]')].find(target=>target.dataset.name===b.dataset.name&&(target.dataset.act||'delete')===b.dataset.inventoryAction);target?.click();};
    return {update(value){rows=value;head.querySelector('.inventory-updated').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});render();}};
};
