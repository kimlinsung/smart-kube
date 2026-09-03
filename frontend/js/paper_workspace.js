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
    const PHASE_PROGRESS = { intake: 4, config: 18, code: 28, schedule: 55, execute: 78, analysis: 90, report: 97, completed: 100 };
    const ACTIVE = new Set(['queued', 'running']);
    const state = {
        summaries: [], workspace: null, files: [], tab: 'config', cy: null,
        durationChart: null, resourceChart: null, reloadTimer: null, summaryTimer: null,
        launchMode: null,
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
        if (!state.summaries.length) {
            root.innerHTML = '<div class="history-empty">暂无工作记录</div>';
            return;
        }
        root.innerHTML = state.summaries.map(item => `
          <button type="button" class="history-item ${escapeHtml(item.status)} ${state.workspace?.id === item.id ? 'active' : ''}" data-workspace-id="${item.id}">
            <span class="history-dot"></span>
            <span class="history-copy"><b>${escapeHtml(item.name)}</b><small>${STATUS_LABELS[item.status] || item.status} · ${fmtTime(item.updated_at)}</small></span>
          </button>`).join('');
    }

    async function loadSummaries() {
        const response = await API.paperWorkspaces();
        state.summaries = response.workspaces || [];
        renderHistory();
        return state.summaries;
    }

    async function loadWorkspace(id) {
        if (!id) return;
        const response = await API.paperWorkspace(id);
        state.workspace = response.workspace;
        renderWorkspace();
        renderHistory();
    }

    function scheduleReload(id) {
        if (!state.workspace || state.workspace.id !== id) return;
        clearTimeout(state.reloadTimer);
        state.reloadTimer = setTimeout(() => loadWorkspace(id).catch(() => {}), 100);
    }

    function scheduleSummaryReload() {
        clearTimeout(state.summaryTimer);
        state.summaryTimer = setTimeout(() => loadSummaries().catch(() => {}), 150);
    }

    function phaseState(workspace, phase) {
        if (phase === 'retain') return workspace.resources_reclaimed ? 'reclaimed' : 'retained';
        if (['code', 'execute', 'analysis'].includes(phase) && workspace.mode === 'resources') return 'skipped';
        const order = ['intake', 'config', 'code', 'schedule', 'execute', 'analysis', 'report', 'completed'];
        const current = order.indexOf(workspace.stage);
        const target = order.indexOf(phase);
        if (workspace.status === 'failed' && workspace.stage === phase) return 'failed';
        if (workspace.status === 'interrupted' && workspace.stage === phase) return 'failed';
        if (workspace.status === 'completed' || current > target) return 'completed';
        if (workspace.stage === phase && ACTIVE.has(workspace.status)) return 'active';
        return 'pending';
    }

    function workflowPositions() {
        const width = $('#workflowGraph').clientWidth;
        if (width < 520) {
            const ids = ['intake', 'config', 'code', 'schedule', 'execute', 'analysis', 'report', 'retain'];
            return Object.fromEntries(ids.map((id, index) => [id, {
                x: width * [.18, .5, .82][index % 3], y: 40 + Math.floor(index / 3) * 105,
            }]));
        }
        const ids = ['intake', 'config', 'code', 'schedule', 'execute', 'analysis', 'report', 'retain'];
        const gap = (width - 96) / (ids.length - 1);
        return Object.fromEntries(ids.map((id, index) => [id, { x: 48 + gap * index, y: 88 }]));
    }

    function renderWorkflow(workspace) {
        if (!window.cytoscape) return;
        if (state.cy) state.cy.destroy();
        const positions = workflowPositions();
        const labels = {
            intake: '文档理解', config: '配置 Agent', code: '代码生成', schedule: '资源调度',
            execute: '真实执行', analysis: '分析 Agent', report: '报告 Agent', retain: '保留资源',
        };
        const nodes = Object.keys(labels).map(id => ({
            data: { id, label: labels[id], state: phaseState(workspace, id) }, position: positions[id],
        }));
        const edgePairs = workspace.mode === 'resources'
            ? [['intake', 'config'], ['config', 'schedule'], ['schedule', 'report'], ['report', 'retain']]
            : [['intake', 'config'], ['config', 'code'], ['code', 'schedule'], ['schedule', 'execute'], ['execute', 'analysis'], ['analysis', 'report'], ['report', 'retain']];
        state.cy = cytoscape({
            container: $('#workflowGraph'), elements: [...nodes, ...edgePairs.map((pair, index) => ({ data: { id: `e${index}`, source: pair[0], target: pair[1] } }))],
            layout: { name: 'preset', fit: false }, minZoom: 1, maxZoom: 1, userZoomingEnabled: false, userPanningEnabled: false,
            style: [
                { selector: 'node', style: { width: 82, height: 42, shape: 'round-rectangle', 'background-color': '#fafbfa', 'border-width': 1, 'border-color': '#dce4df', label: 'data(label)', color: '#657069', 'font-size': 10, 'font-family': 'sans-serif', 'text-valign': 'center', 'text-halign': 'center' } },
                { selector: 'node[state="active"]', style: { 'background-color': '#eef9f3', 'border-width': 2, 'border-color': '#168557', color: '#0b633d' } },
                { selector: 'node[state="completed"]', style: { 'background-color': '#e9f7ef', 'border-color': '#25a86b', color: '#0f754b' } },
                { selector: 'node[state="retained"]', style: { 'background-color': '#fdf4e3', 'border-color': '#d08a16', color: '#9a6208' } },
                { selector: 'node[state="reclaimed"]', style: { 'background-color': '#f0f3f1', 'border-color': '#9ba39e', color: '#747d77' } },
                { selector: 'node[state="skipped"]', style: { 'background-color': '#fafbfa', 'border-style': 'dashed', color: '#9ba39e' } },
                { selector: 'node[state="failed"]', style: { 'background-color': '#fdecec', 'border-color': '#dc2626', color: '#b91c1c' } },
                { selector: 'edge', style: { width: 1.5, 'line-color': '#cad5ce', 'target-arrow-color': '#87948d', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier' } },
            ],
        });
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
        if (analysis.stage_durations?.length) return analysis.stage_durations;
        const groups = {};
        (workspace.events || []).forEach(event => {
            if (!['config', 'code', 'schedule', 'execute', 'analysis', 'report'].includes(event.phase)) return;
            const values = groups[event.phase] || [event.created_at, event.created_at];
            groups[event.phase] = [Math.min(values[0], event.created_at), Math.max(values[1], event.created_at)];
        });
        return Object.entries(groups).map(([phase, values]) => ({ phase, seconds: Math.max(1, values[1] - values[0] + 1) }));
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
            series: [{ type: 'pie', radius: ['42%', '67%'], center: ['50%', '43%'], label: { fontSize: 9, formatter: '{b} {c}' }, data: counts }],
        }, true);
    }

    function renderEvents(workspace) {
        const events = workspace.events || [];
        $('#eventCount').textContent = `${events.length} 条`;
        $('#workspaceEvents').innerHTML = [...events].reverse().map(event => `
          <li class="${escapeHtml(event.event_type)}">
            <span class="event-node"></span>
            <time class="event-time">${new Date(event.created_at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}</time>
            <span class="event-phase">${PHASE_LABELS[event.phase] || escapeHtml(event.phase)}</span>
            <span class="event-content">${escapeHtml(event.content)}</span>
          </li>`).join('') || '<li><span class="event-content">等待过程事件</span></li>';
    }

    function renderInspector() {
        const workspace = state.workspace;
        if (!workspace) return;
        const body = $('#inspectorBody');
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
        body.innerHTML = value && Object.keys(value).length
            ? `<pre class="json-view">${escapeHtml(jsonText(value))}</pre>`
            : `<div class="inspector-empty">${PHASE_LABELS[state.tab] || state.tab}产物尚未生成</div>`;
    }

    function renderWorkspace() {
        const workspace = state.workspace;
        $('#workspaceEmpty').hidden = !!workspace;
        $('#workspaceView').hidden = !workspace;
        if (!workspace) return;
        const task = latestTask(workspace);
        const progress = task?.progress ?? PHASE_PROGRESS[workspace.stage] ?? 0;
        $('#workspaceMode').textContent = workspace.mode === 'full' ? '完整流程' : '执行至调度';
        $('#workspaceStatus').textContent = STATUS_LABELS[workspace.status] || workspace.status;
        $('#workspaceName').textContent = workspace.name;
        $('#workspaceGoal').textContent = workspace.goal;
        $('#workspaceUpdated').textContent = `更新于 ${fmtTime(workspace.updated_at)}`;
        $('#runProgressBar').style.width = `${progress}%`;
        $('#runProgressText').textContent = task?.detail || (workspace.resources_reclaimed ? '资源已回收，实验归档仍保留' : '实验产物已持久化');
        $('#openExperiment').href = `/experiment_detail.html?id=${workspace.experiment_id}`;
        $('#retryAnalysis').hidden = workspace.mode !== 'full' || ACTIVE.has(workspace.status);
        $('#reclaimResources').hidden = ACTIVE.has(workspace.status) || workspace.resources_reclaimed || !(workspace.schedule_json?.created > 0);
        renderWorkflow(workspace);
        renderArtifacts(workspace);
        renderCharts(workspace);
        renderEvents(workspace);
        renderInspector();
    }

    async function previewFile(fileId) {
        $('#previewFilename').textContent = '加载中';
        $('#filePreview').textContent = '';
        $('#filePreviewBackdrop').hidden = false;
        try {
            const response = await API.paperFileContent(state.workspace.id, fileId);
            $('#previewFilename').textContent = response.filename;
            $('#filePreview').textContent = response.content;
        } catch (error) {
            $('#previewFilename').textContent = '无法预览';
            $('#filePreview').textContent = error.message;
        }
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
        const button = event.target.closest('[data-workspace-id]');
        if (button) loadWorkspace(button.dataset.workspaceId).catch(error => alert(error.message));
    };
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
    };
    $('#retryAnalysis').onclick = retryAnalysis;
    $('#reclaimResources').onclick = reclaimResources;
    $('#closePreview').onclick = () => { $('#filePreviewBackdrop').hidden = true; };
    $('#filePreviewBackdrop').onclick = event => { if (event.target === event.currentTarget) event.currentTarget.hidden = true; };
    window.addEventListener('task:update', event => {
        const workspaceId = event.detail?.metadata?.workspace_id;
        if (workspaceId) { scheduleReload(workspaceId); scheduleSummaryReload(); }
    });
    window.addEventListener('task-socket:state', event => {
        $('#liveIndicator').classList.toggle('offline', !event.detail?.connected);
        $('#liveIndicator').lastChild.textContent = event.detail?.connected ? '实时连接' : '正在重连';
    });
    window.addEventListener('resize', () => {
        state.durationChart?.resize(); state.resourceChart?.resize();
        if (state.workspace) renderWorkflow(state.workspace);
    });

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
