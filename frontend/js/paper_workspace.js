/* Paper workspace: persistent configuration, scheduling, analysis and artifacts. */
(() => {
    const STATUS_LABELS = {
        queued: '排队中', running: '执行中', completed: '已完成', failed: '失败',
        interrupted: '已中断', reclaimed: '已回收',
    };
    const PHASE_LABELS = {
        intake: '文档理解 Agent', config: '配置 Agent', code: '代码生成 Agent', schedule: '调度',
        execute: '真实执行', analysis: '分析 Agent', report: '报告 Agent',
        completed: '完成', lifecycle: '生命周期', system: '系统',
    };
    const CHART_PHASE_LABELS = {
        intake: '文档理解', config: '配置生成', code: '代码生成', schedule: '资源调度',
        execute: '真实执行', analysis: '证据分析', report: '报告生成',
    };
    const EXECUTION_STATUS_LABELS = {
        succeeded: '成功', failed: '失败', timed_out: '超时', invalid_output: '输出无效',
    };
    const TIER_LABELS = { cloud: '云', edge: '边', device: '端' };
    const PHASE_PROGRESS = { intake: 4, config: 18, schedule: 55, code: 74, execute: 82, analysis: 90, report: 97, completed: 100 };
    const ACTIVE = new Set(['queued', 'running']);
    const state = {
        summaries: [], workspace: null, files: [], tab: 'config', cy: null,
        durationChart: null, resourceChart: null, reloadTimer: null, summaryTimer: null,
        workflowMode: null, detailsStale: false,
        launchMode: null,
        selected: new Set(), deleting: false,
        flow: null, search: '', loadingStatus: false, loadVersion: 0,
        inspectorRaw: false,
    };

    const $ = selector => document.querySelector(selector);
    const fileInput = $('#paperFiles');
    const launch = $('#launchBackdrop');
    const modeBackdrop = $('#modeBackdrop');

    function formatBytes(value) {
        const bytes = Number(value || 0);
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    function jsonText(value) {
        return JSON.stringify(value || {}, null, 2);
    }

    function latestTask(workspace) {
        return [...(workspace.tasks || [])].sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))[0] || null;
    }

    function selectedFileKey(file) {
        return `${file.name}:${file.size}:${file.lastModified}`;
    }

    function renderSelectedFiles() {
        $('#selectedFiles').innerHTML = state.files.map((file, index) => `
            <div class="selected-file">
              <b title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</b>
              <span>${formatBytes(file.size)}</span>
              <button type="button" data-remove-file="${index}" title="移除" aria-label="移除 ${escapeHtml(file.name)}">×</button>
            </div>`).join('');
    }

    function addFiles(fileList) {
        const known = new Set(state.files.map(selectedFileKey));
        for (const file of fileList || []) {
            if (state.files.length >= 8) break;
            if (file.size > 20 * 1024 * 1024 || known.has(selectedFileKey(file))) continue;
            state.files.push(file);
            known.add(selectedFileKey(file));
        }
        renderSelectedFiles();
    }

    function resetLaunch() {
        $('#launchForm').reset();
        state.launchMode = null;
        state.files = [];
        renderSelectedFiles();
        $('#launchError').textContent = '';
        $('#launchProgress').hidden = true;
        $('#startWorkspace').disabled = false;
    }

    function openLaunch() {
        resetLaunch();
        modeBackdrop.hidden = false;
        $('#closeMode').hidden = !state.summaries.length;
        modeBackdrop.querySelector('.mode-option').focus();
    }

    function closeLaunch() {
        if (!state.summaries.length) return;
        launch.hidden = true;
        modeBackdrop.hidden = true;
    }

    function selectMode(mode) {
        state.launchMode = mode;
        modeBackdrop.hidden = true;
        launch.hidden = false;
        $('#closeLaunch').hidden = !state.summaries.length;
        $('#paperFileDrop').focus();
    }

    function backToMode() {
        launch.hidden = true;
        modeBackdrop.hidden = false;
        modeBackdrop.querySelector(`[data-workspace-mode="${state.launchMode}"]`)?.focus();
    }

    async function createWorkspace(event) {
        event.preventDefault();
        const mode = state.launchMode;
        if (!mode) { backToMode(); return; }
        if (!state.files.length) { $('#launchError').textContent = '请至少加入一个输入文件'; return; }
        const form = new FormData();
        form.append('mode', mode);
        state.files.forEach(file => form.append('files', file, file.name));
        $('#startWorkspace').disabled = true;
        $('#launchError').textContent = '';
        $('#launchProgress').hidden = false;
        try {
            const response = await API.createPaperWorkspace(form, progress => {
                $('#launchProgressBar').style.width = `${progress}%`;
                $('#launchProgressText').textContent = `${progress}%`;
            });
            state.workspace = response.workspace;
            launch.hidden = true;
            await refreshShellExperiment();
            await loadWorkspace(response.workspace.id);
            await loadSummaries();
        } catch (error) {
            $('#launchError').textContent = error.message;
        } finally {
            $('#startWorkspace').disabled = false;
        }
    }

    async function refreshShellExperiment() {
        try {
            const me = await API.me();
            ME = me; window.ME = me; renderShell(me);
            window.dispatchEvent(new CustomEvent('experiment:changed'));
        } catch (_) { /* global auth handler redirects when needed */ }
    }

    function renderHistory() {
        const root = $('#workspaceHistory');
        const manageable = state.summaries.filter(item => item.access_role !== 'collaborator' && !ACTIVE.has(item.status));
        const eligible = manageable.filter(item => item.name.toLowerCase().includes(state.search));
        for (const id of state.selected) if (!manageable.some(item => item.id === id)) state.selected.delete(id);
        const checked = eligible.filter(item => state.selected.has(item.id)).length;
        $('#selectWorkspaces').checked = eligible.length > 0 && checked === eligible.length;
        $('#selectWorkspaces').indeterminate = checked > 0 && checked < eligible.length;
        $('#selectWorkspaces').disabled = state.deleting || !eligible.length;
        $('#deleteSelectedWorkspaces').disabled = state.deleting || !state.selected.size;
        $('#deleteSelectedWorkspaces').textContent = state.deleting ? '正在删除…' : `删除所选 (${state.selected.size})`;
        if (!state.summaries.length) {
            root.innerHTML = '<div class="history-empty">暂无工作记录</div>';
            return;
        }
        root.innerHTML = state.summaries.filter(item => item.name.toLowerCase().includes(state.search)).map(item => `
          <div class="history-row">
          ${item.access_role !== 'collaborator' ? `<input type="checkbox" data-select-workspace="${item.id}" aria-label="选择 ${escapeHtml(item.name)}" ${state.selected.has(item.id) ? 'checked' : ''} ${state.deleting || ACTIVE.has(item.status) ? 'disabled' : ''} />` : ''}
          <button type="button" class="history-item ${escapeHtml(item.status)} ${state.workspace?.id === item.id ? 'active' : ''}" data-workspace-id="${item.id}">
            <span class="history-dot"></span>
            <span class="history-copy"><b>${escapeHtml(item.name)}</b><small>${item.access_role === 'collaborator' ? `协作 · @${escapeHtml(item.owner_username || 'unknown')} · ` : ''}${STATUS_LABELS[item.status] || item.status} · ${fmtTime(item.updated_at)}</small></span>
          </button>
          ${item.access_role !== 'collaborator' ? `<button type="button" class="history-delete danger" data-delete-workspace="${item.id}" title="${ACTIVE.has(item.status) ? '任务执行中，暂不能删除' : '彻底删除工作区'}" aria-label="删除 ${escapeHtml(item.name)}" ${state.deleting || ACTIVE.has(item.status) ? 'disabled' : ''}><i data-lucide="trash-2"></i></button>` : ''}
          </div>`).join('');
        window.lucide?.createIcons();
    }

    async function loadSummaries() {
        const response = await API.paperWorkspaces();
        state.summaries = response.workspaces || [];
        if (state.workspace && !state.summaries.some(item => item.id === state.workspace.id)) {
            state.workspace = null;
            renderWorkspace();
            history.replaceState(null, '', '/paper_workspace.html');
        }
        renderHistory();
        return state.summaries;
    }

    async function loadWorkspace(id) {
        if (!id) return;
        const version = ++state.loadVersion;
        const response = await API.paperWorkspace(id);
        if (version !== state.loadVersion) return;
        state.workspace = response.workspace;
        state.detailsStale = false;
        renderWorkspace();
        renderHistory();
    }

    async function loadWorkspaceStatus(id) {
        if (!state.workspace || state.workspace.id !== id) return;
        const version = state.loadVersion;
        const response = await API.paperWorkspaceStatus(id);
        if (version !== state.loadVersion || state.workspace?.id !== id) return;
        const before = state.workspace;
        state.workspace = { ...before, ...response.workspace };
        const events = new Map((before.events || []).map(event => [event.id, event]));
        for (const event of response.workspace.events || []) events.set(event.id, { ...events.get(event.id), ...event });
        state.workspace.events = [...events.values()].sort((a,b) => a.id-b.id);
        state.detailsStale ||= before.updated_at !== response.workspace.updated_at
            || before.stage !== response.workspace.stage
            || before.status !== response.workspace.status;
        renderWorkspace(true);
        renderHistory();
        // A terminal result is stable, so refresh the full artifact payload once.
        if (!ACTIVE.has(state.workspace.status) && state.detailsStale) await loadWorkspace(id);
    }

    function scheduleReload(id) {
        if (!state.workspace || state.workspace.id !== id) return;
        clearTimeout(state.reloadTimer);
        state.reloadTimer = setTimeout(() => loadWorkspaceStatus(id).catch(() => {}), 500);
    }

    function scheduleSummaryReload() {
        clearTimeout(state.summaryTimer);
        state.summaryTimer = setTimeout(() => loadSummaries().catch(() => {}), 150);
    }

    function renderWorkflow(workspace) {
        if (!window.WorkspaceFlow) return;
        state.flow ||= WorkspaceFlow.create($('#workflowGraph'), {
            onArtifact(tab) {
                if ($('#flowStudio').classList.contains('flow-focused')) $('#flowFocus').click();
                state.tab = tab;
                document.querySelectorAll('.inspector-tabs button').forEach(item => item.classList.toggle('active', item.dataset.tab === tab));
                renderInspector();
                $('.artifact-inspector').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
                if (state.detailsStale) loadWorkspace(state.workspace?.id).catch(error => alert(error.message));
            },
        });
        state.flow.update(workspace);
    }

    function renderArtifacts(workspace) {
        $('#fileCount').textContent = `${(workspace.files || []).length} 个`;
        $('#artifactList').innerHTML = (workspace.files || []).map(file => `
          <div class="artifact-item">
            <span class="artifact-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 2h8l4 4v16H6zM14 2v5h5M9 13h6M9 17h4"/></svg></span>
            <span class="artifact-meta"><b title="${escapeHtml(file.original_name)}">${escapeHtml(file.original_name)}</b><small>${file.artifact_type === 'generated_code' ? 'Agent 生成 · ' : ''}${formatBytes(file.size)}</small></span>
            <span class="artifact-actions">
              <button type="button" data-preview-file="${file.id}" title="预览" aria-label="预览"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/></svg></button>
              <a href="/api/paper/workspaces/${workspace.id}/files/${file.id}/download" title="下载" aria-label="下载"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg></a>
            </span>
          </div>`).join('') || '<div class="inspector-empty">暂无输入文件</div>';
    }

    function derivedDurations(workspace) {
        const analysis = workspace.analysis_json || {};
        if (!(workspace.events || []).length && analysis.stage_durations?.length) return analysis.stage_durations;
        const groups = {};
        (workspace.events || []).forEach(event => {
            if (!['intake', 'config', 'code', 'schedule', 'execute', 'analysis', 'report'].includes(event.phase)) return;
            const values = groups[event.phase] || [event.created_at, event.created_at];
            groups[event.phase] = [Math.min(values[0], event.created_at), Math.max(values[1], event.created_at)];
        });
        return Object.entries(groups).map(([phase, values]) => ({ phase, seconds: Math.max(0, values[1] - values[0]) }));
    }

    function renderCharts(workspace) {
        const placements = workspace.schedule_json?.placements || [];
        const executions = workspace.schedule_json?.executions || [];
        const durations = derivedDurations(workspace);
        const checks = workspace.analysis_json?.checks || [];
        $('#metricRow').innerHTML = [
            [(workspace.files || []).filter(file => file.artifact_type !== 'generated_code').length, '输入文件'],
            [placements.length, '已调度 Units'],
            [executions.filter(item => item.status === 'succeeded').length, `运行成功 / ${executions.length}`],
            [checks.filter(item => item.passed).length, `通过检查 / ${checks.length}`],
        ].map(([value, label]) => `<div class="paper-metric"><b>${value}</b><small>${label}</small></div>`).join('');
        if (!window.echarts) return;
        state.durationChart ||= echarts.init($('#durationChart'));
        state.resourceChart ||= echarts.init($('#resourceChart'));
        state.durationChart.setOption({
            animationDuration: 350, grid: { left: 48, right: 12, top: 12, bottom: 22 },
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
            xAxis: { type: 'value', name: '秒', nameTextStyle: { fontSize: 9 }, axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#edf0f4' } } },
            yAxis: { type: 'category', data: durations.map(item => CHART_PHASE_LABELS[item.phase] || item.phase), axisLabel: { fontSize: 9 }, axisTick: { show: false }, axisLine: { show: false } },
            series: [{ type: 'bar', data: durations.map(item => item.seconds), barWidth: 12, itemStyle: { color: '#168557', borderRadius: [0, 3, 3, 0] } }],
        }, true);
        const counts = ['cloud', 'edge', 'device'].map(tier => ({
            name: TIER_LABELS[tier], value: placements.filter(item => item.node_type === tier).length,
        }));
        state.resourceChart.setOption({
            animationDuration: 350, color: ['#187c73', '#527d47', '#b36b18'],
            tooltip: { trigger: 'item' }, legend: { bottom: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 9 } },
            series: [{ type: 'pie', stillShowZeroSum: false, radius: ['42%', '67%'], center: ['50%', '43%'], label: { fontSize: 9, formatter: '{b} {c}' }, data: counts }],
        }, true);
    }

    function renderEvents(workspace) {
        const query = $('#eventSearch').value.toLowerCase();
        const filter = $('#eventFilter').value;
        const events = (workspace.events || []).filter(event =>
            (!query || event.content.toLowerCase().includes(query)) &&
            (filter === 'all' || (filter === 'failure' ? /failed|interrupted|retry/.test(event.event_type) : /execution|prepared/.test(event.event_type)))
        );
        $('#eventCount').textContent = `${events.length} 条`;
        $('#workspaceEvents').innerHTML = [...events].reverse().map(event => `
          <li class="${escapeHtml(event.event_type)}">
            <span class="event-node"></span>
            <time class="event-time">${new Date(event.created_at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}</time>
            <span class="event-phase">${PHASE_LABELS[event.phase] || escapeHtml(event.phase)}</span>
            <span class="event-content">${escapeHtml(event.content)}</span>
          </li>`).join('') || '<li class="event-empty"><span class="event-content">等待过程事件</span></li>';
    }

    function renderInspector() {
        const workspace = state.workspace;
        if (!workspace) return;
        const body = $('#inspectorBody');
        $('#inspectorRaw').disabled = !['config','schedule','analysis'].includes(state.tab);
        $('#downloadReport').hidden = state.tab !== 'report' || !workspace.report_md;
        if (state.inspectorRaw && ['config','schedule','analysis'].includes(state.tab)) {
            body.innerHTML = `<pre class="json-view">${escapeHtml(jsonText(workspace[state.tab + '_json']))}</pre>`;
            return;
        }
        $('#downloadReport').hidden = state.tab !== 'report' || !workspace.report_md;
        $('#downloadReport').href = `/api/paper/workspaces/${workspace.id}/report`;
        if (state.tab === 'report') {
            if (!workspace.report_md) { body.innerHTML = '<div class="inspector-empty">报告将在流程结束后生成</div>'; return; }
            const html = window.marked && window.DOMPurify
                ? DOMPurify.sanitize(marked.parse(workspace.report_md, { gfm: true, breaks: true }))
                : `<pre class="json-view">${escapeHtml(workspace.report_md)}</pre>`;
            body.innerHTML = `<article class="report-view">${html}</article>`;
            return;
        }
        if (state.tab === 'code') {
            const program = workspace.config_json?.generated_program;
            if (!program) { body.innerHTML = '<div class="inspector-empty">代码生成 Agent 尚未产出程序</div>'; return; }
            body.innerHTML = `
              <div class="program-meta"><b>${escapeHtml(program.runtime?.language || '')} ${escapeHtml(program.runtime?.version || '')}</b><span>${escapeHtml(program.runtime?.image || '')}</span><span>${program.runs?.length || 0} 个运行目标</span></div>
              <pre class="code-view"><code>${escapeHtml(program.code || '')}</code></pre>`;
            return;
        }
        if (state.tab === 'run') {
            const executions = workspace.schedule_json?.executions || [];
            body.innerHTML = executions.length ? executions.map(item => `
              <section class="execution-result ${escapeHtml(item.status)}">
                <header><b>${escapeHtml(item.pod_name || item.run_id)}</b><span>${EXECUTION_STATUS_LABELS[item.status] || escapeHtml(item.status)} · ${Number(item.duration_seconds || 0).toFixed(3)}s</span></header>
                <small>${escapeHtml(item.node || '')} · exit ${item.exit_code ?? 'unknown'} · ${escapeHtml((item.arguments || []).join(' '))}</small>
                <label>stdout</label><pre>${escapeHtml(item.stdout || '无输出')}</pre>
                ${item.stderr ? `<label>stderr</label><pre class="stderr">${escapeHtml(item.stderr)}</pre>` : ''}
              </section>`).join('') : '<div class="inspector-empty">尚未收集 Unit 运行输出</div>';
            return;
        }
        const values = {
            config: workspace.config_json,
            schedule: workspace.schedule_json,
            analysis: workspace.mode === 'resources' ? { skipped: true, reason: '本次执行至调度阶段' } : workspace.analysis_json,
        };
        const value = values[state.tab];
        if (!value || !Object.keys(value).length) {
            body.innerHTML = `<div class="inspector-empty">${PHASE_LABELS[state.tab] || state.tab}产物尚未生成</div>`;
            return;
        }
        if (state.tab === 'config') {
            const intelligence = value.document_intelligence || {};
            body.innerHTML = `<div class="structured-inspector"><h3>资源计划</h3><div class="resource-plan">${(value.resources || []).map(row=>`<article><header><b>${TIER_LABELS[row.tier] || escapeHtml(row.tier || '')}</b><span>${escapeHtml(row.arch)} · ${row.count || 1} Units</span></header><code>${escapeHtml(row.image || '默认镜像')}</code><dl><div><dt>CPU</dt><dd>${escapeHtml(row.cpu || '—')}</dd></div><div><dt>内存</dt><dd>${escapeHtml(row.memory || '—')}</dd></div><div><dt>GPU</dt><dd>${Number(row.gpu || 0)}</dd></div></dl></article>`).join('')}</div>${intelligence.summary?`<h3>文档理解</h3><p>${escapeHtml(intelligence.summary)}</p>`:''}${(value.assumptions || []).length?'<h3>范围与假设</h3><ul>'+value.assumptions.map(text=>'<li>'+escapeHtml(text)+'</li>').join('')+'</ul>':''}</div>`;
        } else if (state.tab === 'schedule') {
            body.innerHTML = `<div class="structured-inspector"><h3>节点落位 <small>${value.created || 0} / ${value.requested || 0}</small></h3>${(value.placements || []).map(item=>`<article class="placement-row"><i data-lucide="server"></i><div><b>${escapeHtml(item.node || '等待节点')}</b><small>${escapeHtml(item.pod_name)}</small><span>${escapeHtml(item.arch || '')} · ${escapeHtml(item.node_type || '')}</span>${item.scheduling?.relaxed?.length?'<em>已记录节点类型回退</em>':''}</div></article>`).join('')}<p class="artifact-note">${workspace.resources_reclaimed?'计算资源已回收，记录保留。':'已创建资源保持运行，直到主动回收。'}</p></div>`;
        } else {
            const verdicts={passed:'验收通过',needs_attention:'结果需要关注',failed:'验收未通过'};
            body.innerHTML = value.skipped ? '<div class="inspector-empty">本次仅执行至调度阶段</div>' : `<div class="structured-inspector"><div class="analysis-verdict ${escapeHtml(value.verdict || '')}"><i data-lucide="${value.verdict==='passed'?'circle-check':'triangle-alert'}"></i><b>${verdicts[value.verdict] || '等待结论'}</b></div><p>${escapeHtml(value.summary || '')}</p><h3>证据检查</h3>${(value.checks||[]).map(check=>`<div class="evidence-check ${check.passed?'passed':'failed'}"><i data-lucide="${check.passed?'check':'x'}"></i><div><b>${escapeHtml(check.name)}</b><p>${escapeHtml(check.detail || '')}</p></div></div>`).join('')}${(value.risks||[]).length?'<h3>风险与局限</h3><ul>'+value.risks.map(text=>'<li>'+escapeHtml(text)+'</li>').join('')+'</ul>':''}${(value.recommendations||[]).length?'<h3>下一步</h3><ul>'+value.recommendations.map(text=>'<li>'+escapeHtml(text)+'</li>').join('')+'</ul>':''}</div>`;
        }
        window.lucide?.createIcons();
    }

    function renderWorkspace(lightweight = false) {
        const workspace = state.workspace;
        $('#workspaceEmpty').hidden = !!workspace;
        $('#workspaceView').hidden = !workspace;
        if (!workspace) { state.flow?.clear(); return; }
        const task = latestTask(workspace);
        const progress = task?.progress ?? PHASE_PROGRESS[workspace.stage] ?? 0;
        $('#workspaceMode').textContent = workspace.mode === 'full' ? '完整流程' : '执行至调度';
        $('#workspaceStatus').textContent = STATUS_LABELS[workspace.status] || workspace.status;
        $('#workspaceStatus').dataset.status = workspace.status;
        $('.run-strip').dataset.status = workspace.status;
        $('#workspaceName').textContent = workspace.name;
        $('#workspaceGoal').textContent = workspace.goal;
        $('#workspaceUpdated').textContent = `更新于 ${fmtTime(workspace.updated_at)}`;
        $('#runProgressBar').style.width = `${progress}%`;
        $('#runProgressText').textContent = task?.detail || (workspace.resources_reclaimed ? '资源已回收，实验归档仍保留' : ['failed','interrupted'].includes(workspace.status) ? '流程已停止，已有产物与资源已保留' : ACTIVE.has(workspace.status) ? '正在执行实验流程' : '实验产物已持久化');
        $('#openExperiment').href = `/experiment_detail.html?id=${workspace.experiment_id}`;
        const canManageSharing = ['owner', 'admin'].includes(workspace.access_role || 'owner');
        const canOperate = workspace.user_id === ME?.id || (workspace.access_role || 'owner') === 'owner';
        $('#manageSharing').hidden = !canManageSharing;
        $('#manageSharing').href = `/experiment_detail.html?id=${workspace.experiment_id}#sharing`;
        $('#retryAnalysis').hidden = !canOperate || workspace.mode !== 'full' || ACTIVE.has(workspace.status);
        $('#reclaimResources').hidden = !canOperate || ACTIVE.has(workspace.status) || workspace.resources_reclaimed || !(workspace.schedule_json?.created > 0);
        $('#deleteWorkspace').hidden = !canManageSharing;
        $('#deleteWorkspace').disabled = state.deleting || ACTIVE.has(workspace.status);
        $('#deleteWorkspace').title = ACTIVE.has(workspace.status) ? '任务执行中，暂不能删除' : '彻底删除工作区及文件';
        renderWorkflow(workspace);
        renderArtifacts(workspace);
        renderCharts(workspace);
        renderEvents(workspace);
        if (!lightweight) renderInspector();
    }

    async function previewFile(fileId) {
        if (state.workspace) await FilePreview.open(state.workspace.id, fileId);
    }

    async function retryAnalysis() {
        if (!state.workspace) return;
        const button = $('#retryAnalysis');
        button.disabled = true;
        try {
            await API.retryPaperAnalysis(state.workspace.id);
            await loadWorkspace(state.workspace.id);
        } catch (error) {
            alert(`重新分析失败：${error.message}`);
        } finally {
            button.disabled = false;
        }
    }

    async function reclaimResources() {
        if (!state.workspace || !confirm('确认回收本次实验的全部 Units？输入文件、过程记录和报告会继续保留。')) return;
        const button = $('#reclaimResources');
        button.disabled = true;
        try {
            const response = await API.reclaimPaperWorkspace(state.workspace.id);
            state.workspace = response.workspace;
            renderWorkspace();
            await loadSummaries();
        } catch (error) {
            alert(`回收失败：${error.message}`);
        } finally {
            button.disabled = false;
        }
    }

    async function deleteWorkspace() {
        if (state.workspace) await deleteWorkspaces([state.workspace.id]);
    }

    async function deleteWorkspaces(ids) {
        if (state.deleting || !ids.length || !confirm(`确认彻底删除选中的 ${ids.length} 个工作区？所有容器、关联实验、上传文件、生成代码、报告和过程记录都会被删除，且无法恢复。`)) return;
        state.deleting = true; renderHistory(); renderWorkspace();
        try {
            const result = await API.deletePaperWorkspaces(ids);
            for (const item of result.results) {
                if (!item.ok) continue;
                state.selected.delete(item.id);
                if (state.workspace?.id === item.id) { state.workspace = null; state.loadVersion++; }
            }
            renderWorkspace();
            await loadSummaries();
            if (!state.workspace) {
                const next = state.summaries[0];
                if (next) await loadWorkspace(next.id);
                else history.replaceState(null, '', '/paper_workspace.html');
            }
            await refreshShellExperiment();
            const failures = result.results.filter(item => !item.ok);
            if (failures.length) alert('以下工作未删除：\n' + failures.map(item => `${item.id}: ${item.error}`).join('\n'));
        } catch (error) {
            alert(`删除工作区失败：${error.message}`);
        } finally {
            state.deleting = false; renderHistory(); renderWorkspace();
        }
    }

    $('#newWorkspaceBtn').onclick = openLaunch;
    $('#emptyStartBtn').onclick = openLaunch;
    $('#closeMode').onclick = closeLaunch;
    $('#modeBackdrop').onclick = event => {
        const button = event.target.closest('[data-workspace-mode]');
        if (button) selectMode(button.dataset.workspaceMode);
    };
    $('#closeLaunch').onclick = closeLaunch;
    $('#cancelLaunch').onclick = backToMode;
    $('#launchForm').onsubmit = createWorkspace;
    $('#paperFileDrop').onclick = () => fileInput.click();
    fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ''; };
    $('#paperFileDrop').ondragover = event => { event.preventDefault(); event.currentTarget.classList.add('dragging'); };
    $('#paperFileDrop').ondragleave = event => event.currentTarget.classList.remove('dragging');
    $('#paperFileDrop').ondrop = event => {
        event.preventDefault(); event.currentTarget.classList.remove('dragging'); addFiles(event.dataTransfer.files);
    };
    $('#selectedFiles').onclick = event => {
        const button = event.target.closest('[data-remove-file]');
        if (!button) return;
        state.files.splice(Number(button.dataset.removeFile), 1); renderSelectedFiles();
    };
    $('#workspaceHistory').onclick = event => {
        const remove = event.target.closest('[data-delete-workspace]');
        if (remove) { deleteWorkspaces([remove.dataset.deleteWorkspace]); return; }
        const button = event.target.closest('[data-workspace-id]');
        if (button) loadWorkspace(button.dataset.workspaceId).catch(error => alert(error.message));
    };
    $('#workspaceHistory').onchange = event => {
        const id = event.target.dataset.selectWorkspace;
        if (!id) return;
        event.target.checked ? state.selected.add(id) : state.selected.delete(id);
        renderHistory();
    };
    $('#workspaceSearch').oninput = event => { state.search = event.target.value.trim().toLowerCase(); renderHistory(); };
    $('#eventFilter').onchange = () => { if(state.workspace) renderEvents(state.workspace); };
    $('#eventSearch').oninput = () => { if(state.workspace) renderEvents(state.workspace); };
    $('#workspacePanelTabs').onclick = event => {
        const button = event.target.closest('[data-panel]');
        if (!button) return;
        document.querySelectorAll('[data-workspace-panel]').forEach(panel => { panel.hidden = panel.dataset.workspacePanel !== button.dataset.panel; });
        document.querySelectorAll('#workspacePanelTabs button').forEach(item => item.setAttribute('aria-selected',String(item === button)));
        if (button.dataset.panel === 'telemetry') { state.durationChart?.resize(); state.resourceChart?.resize(); }
    };
    $('#inspectorRaw').onclick = () => { state.inspectorRaw = !state.inspectorRaw; $('#inspectorRaw').setAttribute('aria-pressed',String(state.inspectorRaw)); renderInspector(); };
    $('#selectWorkspaces').onchange = event => {
        state.selected.clear();
        if (event.target.checked) state.summaries.filter(item => item.access_role !== 'collaborator' && !ACTIVE.has(item.status) && item.name.toLowerCase().includes(state.search)).forEach(item => state.selected.add(item.id));
        renderHistory();
    };
    $('#deleteSelectedWorkspaces').onclick = () => deleteWorkspaces([...state.selected]);
    $('#artifactList').onclick = event => {
        const button = event.target.closest('[data-preview-file]');
        if (button) previewFile(Number(button.dataset.previewFile));
    };
    $('.inspector-tabs').onclick = event => {
        const button = event.target.closest('[data-tab]');
        if (!button) return;
        state.tab = button.dataset.tab;
        document.querySelectorAll('.inspector-tabs button').forEach(item => item.classList.toggle('active', item === button));
        renderInspector();
        if (state.detailsStale && ['code', 'run', 'report'].includes(state.tab)) {
            loadWorkspace(state.workspace?.id).catch(() => {});
        }
    };
    $('#retryAnalysis').onclick = retryAnalysis;
    $('#reclaimResources').onclick = reclaimResources;
    $('#deleteWorkspace').onclick = deleteWorkspace;
    window.addEventListener('task:update', event => {
        const workspaceId = event.detail?.metadata?.workspace_id;
        if (workspaceId) { scheduleReload(workspaceId); scheduleSummaryReload(); }
        if (event.detail?.kind === 'chat' && ['succeeded', 'failed'].includes(event.detail.status)) scheduleSummaryReload();
    });
    window.addEventListener('task-socket:state', event => {
        $('#liveIndicator').classList.toggle('offline', !event.detail?.connected);
        $('#liveIndicator').lastChild.textContent = event.detail?.connected ? '实时连接' : '正在重连';
    });
    window.addEventListener('resize', () => {
        state.durationChart?.resize(); state.resourceChart?.resize();
        if (state.workspace) renderWorkflow(state.workspace);
    });
    setInterval(async () => {
        if (document.hidden || !state.workspace || !ACTIVE.has(state.workspace.status) || state.loadingStatus) return;
        state.loadingStatus = true;
        try { await loadWorkspaceStatus(state.workspace.id); }
        catch (_) { /* Retain the last observed state until connectivity returns. */ }
        finally { state.loadingStatus = false; }
    }, 5000);

    (async () => {
        ME = await loadMe();
        if (!ME) return;
        try {
            const summaries = await loadSummaries();
            const requestedId = new URLSearchParams(location.search).get('id');
            const initial = summaries.find(item => item.id === requestedId) || summaries[0];
            if (initial) await loadWorkspace(initial.id);
            else openLaunch();
        } catch (error) {
            $('#workspaceEmpty').querySelector('p').textContent = `加载失败：${error.message}`;
        }
    })();
})();
