(() => {
    const token = new URLSearchParams(location.search).get('token') || '';
    const state = { payload: null, tab: 'code', durationChart: null, resourceChart: null };
    const $ = selector => document.querySelector(selector);
    const STATUS = { queued: '排队中', running: '执行中', completed: '已完成', failed: '失败', interrupted: '已中断' };
    const PHASES = [
        ['intake', '文档理解'], ['config', '生成配置'], ['code', '生成代码'], ['schedule', '资源调度'],
        ['execute', '真实执行'], ['analysis', '结果分析'], ['report', '生成报告'], ['retain', '资源保留'],
    ];
    const PHASE_LABELS = { intake: '文档理解', config: '配置生成', code: '代码生成', schedule: '资源调度', execute: '真实执行', analysis: '证据分析', report: '报告生成', lifecycle: '生命周期', system: '系统' };

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
    }

    function fmtTime(timestamp) {
        if (!timestamp) return '-';
        return new Date(Number(timestamp) * 1000).toLocaleString('zh-CN', { hour12: false });
    }

    function fmtBytes(value) {
        const bytes = Number(value || 0);
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    function phaseState(workspace, id) {
        if (id === 'retain') return workspace.resources_reclaimed ? 'done' : (workspace.status === 'completed' ? 'active' : '');
        if (workspace.mode !== 'full' && ['code', 'execute', 'analysis'].includes(id)) return 'skipped';
        const order = ['intake', 'config', 'code', 'schedule', 'execute', 'analysis', 'report', 'completed'];
        const current = order.indexOf(workspace.stage);
        const target = order.indexOf(id);
        if (workspace.status === 'failed' && workspace.stage === id) return 'failed';
        if (workspace.status === 'completed' || current > target) return 'done';
        if (workspace.stage === id && ['queued', 'running'].includes(workspace.status)) return 'active';
        return '';
    }

    function derivedDurations(workspace) {
        const existing = workspace.analysis_json?.stage_durations;
        if (Array.isArray(existing) && existing.length) return existing;
        const groups = {};
        (workspace.events || []).forEach(event => {
            if (!PHASE_LABELS[event.phase]) return;
            const range = groups[event.phase] || [event.created_at, event.created_at];
            groups[event.phase] = [Math.min(range[0], event.created_at), Math.max(range[1], event.created_at)];
        });
        return Object.entries(groups).map(([phase, range]) => ({ phase, seconds: Math.max(1, range[1] - range[0] + 1) }));
    }

    function renderCharts(workspace) {
        if (!window.echarts) return;
        const durations = derivedDurations(workspace);
        const placements = workspace.schedule_json?.placements || [];
        state.durationChart = echarts.init($('#durationChart'));
        state.durationChart.setOption({
            animationDuration: 350,
            grid: { left: 70, right: 20, top: 14, bottom: 28 },
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
            xAxis: { type: 'value', name: '秒', nameTextStyle: { fontSize: 9 }, axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { color: '#edf0ee' } } },
            yAxis: { type: 'category', data: durations.map(item => PHASE_LABELS[item.phase] || item.phase), axisLabel: { fontSize: 9 }, axisLine: { show: false }, axisTick: { show: false } },
            series: [{ type: 'bar', data: durations.map(item => Number(item.seconds || 0)), barWidth: 13, itemStyle: { color: '#168557', borderRadius: [0, 3, 3, 0] } }],
        });
        const tiers = [['云', 'cloud'], ['边', 'edge'], ['端', 'device']];
        const resourceData = tiers.map(([name, tier]) => ({ name, value: placements.filter(item => item.node_type === tier).length }));
        if (!resourceData.some(item => item.value > 0)) resourceData.push({ name: '暂无资源', value: 1, itemStyle: { color: '#dfe5e1' } });
        state.resourceChart = echarts.init($('#resourceChart'));
        state.resourceChart.setOption({
            animationDuration: 350, color: ['#187c73', '#527d47', '#b36b18'],
            tooltip: { trigger: 'item' }, legend: { bottom: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 9 } },
            series: [{ type: 'pie', radius: ['43%', '68%'], center: ['50%', '43%'], label: { fontSize: 9, formatter: '{b} {c}' }, data: resourceData }],
        });
    }

    function renderArtifact() {
        const workspace = state.payload.paper_workspace;
        const body = $('#artifactBody');
        if (!workspace) { body.innerHTML = '<div class="artifact-empty">该实验没有论文工作区产物</div>'; return; }
        if (state.tab === 'code') {
            const program = workspace.config_json?.generated_program;
            body.innerHTML = program ? `<div class="code-meta"><span>${escapeHtml(program.runtime?.language || 'Python')} ${escapeHtml(program.runtime?.version || '')}</span><span>${escapeHtml(program.runtime?.image || '')}</span><span>${program.runs?.length || 0} 个运行目标</span></div><pre class="code-view"><code>${escapeHtml(program.code || '')}</code></pre>` : '<div class="artifact-empty">代码生成 Agent 尚未产出程序</div>';
            return;
        }
        if (state.tab === 'run') {
            const executions = workspace.schedule_json?.executions || [];
            body.innerHTML = executions.length ? executions.map(item => `<section class="run-result ${escapeHtml(item.status)}"><header><b>${escapeHtml(item.pod_name || item.run_id || 'Unit')}</b><span>${escapeHtml(item.status || '-')} · ${Number(item.duration_seconds || 0).toFixed(3)}s</span></header><small>${escapeHtml(item.node || '')} · exit ${escapeHtml(item.exit_code ?? 'unknown')} · ${escapeHtml((item.arguments || []).join(' '))}</small><label>stdout</label><pre>${escapeHtml(item.stdout || '无输出')}</pre>${item.stderr ? `<label>stderr</label><pre class="stderr">${escapeHtml(item.stderr)}</pre>` : ''}</section>`).join('') : '<div class="artifact-empty">尚未收集 Unit 运行输出</div>';
            return;
        }
        if (state.tab === 'report') {
            const report = workspace.report_md || '';
            body.innerHTML = report ? `<article class="report-view">${window.marked && window.DOMPurify ? DOMPurify.sanitize(marked.parse(report, { gfm: true, breaks: true })) : `<pre class="json-view">${escapeHtml(report)}</pre>`}</article>` : '<div class="artifact-empty">报告尚未生成</div>';
            return;
        }
        const value = state.tab === 'analysis' ? workspace.analysis_json : workspace.config_json;
        body.innerHTML = value && Object.keys(value).length ? `<pre class="json-view">${escapeHtml(JSON.stringify(value, null, 2))}</pre>` : '<div class="artifact-empty">暂无可展示内容</div>';
    }

    function render(payload) {
        state.payload = payload;
        const exp = payload.experiment;
        const workspace = payload.paper_workspace;
        $('#projectName').textContent = exp.name;
        $('#projectGoal').textContent = workspace?.goal || exp.description || '未填写项目说明';
        $('#projectStatus').textContent = workspace ? (STATUS[workspace.status] || workspace.status) : '实验归档';
        $('#projectMode').textContent = workspace ? (workspace.mode === 'full' ? '完整流程' : '执行至调度') : '普通实验';
        $('#projectOwner').textContent = `所有者 @${exp.owner_username || 'unknown'}`;
        $('#projectCreated').textContent = `创建于 ${fmtTime(exp.created_at)}`;
        $('#projectUpdated').textContent = `更新于 ${fmtTime(workspace?.updated_at || exp.created_at)}`;
        const placements = workspace?.schedule_json?.placements || [];
        const executions = workspace?.schedule_json?.executions || [];
        const checks = workspace?.analysis_json?.checks || [];
        $('#metricBand').innerHTML = [
            [exp.total_count || placements.length, '已调度 Units'],
            [(workspace?.files || []).filter(file => file.artifact_type !== 'generated_code').length, '输入文件'],
            [executions.filter(item => item.status === 'succeeded').length, `运行成功 / ${executions.length}`],
            [checks.filter(item => item.passed).length, `通过检查 / ${checks.length}`],
            [(workspace?.events || []).length, '过程记录'],
        ].map(([value, label]) => `<div class="metric"><b>${value}</b><small>${escapeHtml(label)}</small></div>`).join('');
        $('#resourceState').textContent = workspace?.resources_reclaimed ? '资源已回收，产物已保留' : '资源由所有者决定回收';
        $('#workflow').innerHTML = PHASES.map(([id, label], index) => `<div class="phase ${workspace ? phaseState(workspace, id) : 'skipped'}"><span class="phase-dot">${index + 1}</span><b>${label}</b></div>`).join('');
        const files = workspace?.files || [];
        $('#fileCount').textContent = `${files.length} 个文件`;
        $('#fileList').innerHTML = files.length ? files.map(file => `<div class="file-item"><span class="file-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 2h8l4 4v16H6zM14 2v5h5M9 13h6M9 17h4"/></svg></span><span class="file-copy"><b title="${escapeHtml(file.original_name)}">${escapeHtml(file.original_name)}</b><small>${file.artifact_type === 'generated_code' ? 'Agent 生成 · ' : ''}${fmtBytes(file.size)}</small></span><a class="file-download" href="/api/public/experiments/shared/${encodeURIComponent(token)}/files/${file.id}/download" title="下载" aria-label="下载 ${escapeHtml(file.original_name)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg></a></div>`).join('') : '<div class="artifact-empty">暂无归档文件</div>';
        const events = workspace?.events || [];
        $('#eventCount').textContent = `${events.length} 条`;
        $('#eventList').innerHTML = events.length ? [...events].reverse().map(event => `<li class="${escapeHtml(event.event_type)}"><span class="event-node"></span><time>${new Date(event.created_at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}</time><span class="event-copy"><b>${escapeHtml(PHASE_LABELS[event.phase] || event.phase)}</b><span>${escapeHtml(event.content)}</span></span></li>`).join('') : '<li><span class="event-node"></span><span></span><span class="event-copy"><span>暂无过程记录</span></span></li>';
        renderCharts(workspace || { events: [], schedule_json: {} });
        renderArtifact();
    }

    $('.artifact-tabs').addEventListener('click', event => {
        const button = event.target.closest('[data-tab]');
        if (!button) return;
        state.tab = button.dataset.tab;
        document.querySelectorAll('.artifact-tabs button').forEach(item => item.classList.toggle('active', item === button));
        renderArtifact();
    });
    window.addEventListener('resize', () => { state.durationChart?.resize(); state.resourceChart?.resize(); });

    (async () => {
        if (!token) {
            $('#loadingState').hidden = true; $('#errorState').hidden = false; $('#errorMessage').textContent = 'URL 中缺少分享 token';
            return;
        }
        try {
            const payload = await API.sharedExperiment(token);
            $('#loadingState').hidden = true; $('#projectView').hidden = false;
            render(payload);
        } catch (error) {
            $('#loadingState').hidden = true; $('#errorState').hidden = false; $('#errorMessage').textContent = error.message;
        }
    })();
})();
