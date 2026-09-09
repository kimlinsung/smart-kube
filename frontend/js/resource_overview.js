window.ResourceOverview = (() => {
    const root = document.getElementById('resourceOverview'), canvas = document.getElementById('resourceCanvas');
    const ctx = canvas.getContext('2d'), motion = document.getElementById('resourceMotion');
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const tiers = [['cloud', '云', '#3476cf'], ['edge', '边', '#1f9575'], ['device', '端', '#bb8432']];
    let pods = [], loaded = false, paused = reduced.matches, frame = 0, visible = true, last = 0;
    const $ = id => document.getElementById(id);
    function draw(time = 0) {
        if (!ctx) return;
        const width = canvas.clientWidth, height = canvas.clientHeight, ratio = Math.min(devicePixelRatio || 1, 2);
        if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, width, height);
        const compact = width < 360, x0 = compact ? 48 : 66, x1 = width - 28;
        tiers.forEach(([key, label, color], index) => {
            const items = pods.filter(pod => pod.node_type === key), y = 36 + index * 74;
            ctx.font = '12px system-ui'; ctx.textAlign = 'left'; ctx.fillStyle = '#405367'; ctx.fillText(label, 8, y - 2);
            ctx.font = '10px system-ui'; ctx.fillStyle = '#83909c'; ctx.fillText(loaded ? String(items.length) : '—', 8, y + 15);
            ctx.strokeStyle = '#e1e7ec'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
            const visibleItems = items.slice(0, 12), gap = (x1 - x0 - 24) / Math.max(visibleItems.length, 1);
            visibleItems.forEach((pod, i) => {
                const x = x0 + 10 + i * gap, running = pod.phase === 'Running';
                ctx.fillStyle = running ? color : '#e4b76b'; ctx.fillRect(x - 5, y - 5, 10, 10);
                if (running && !paused) {
                    const offset = ((time / 1800 + i * .19) % 1) * gap;
                    ctx.globalAlpha = .65; ctx.fillStyle = color; ctx.fillRect(x + offset, y - 1, 4, 2); ctx.globalAlpha = 1;
                }
            });
            if (!items.length) { ctx.font = '11px system-ui'; ctx.fillStyle = '#8795a1'; ctx.fillText(loaded ? '未分配' : '正在读取', x0 + 12, y - 10); }
            if (items.length > 12) { ctx.textAlign = 'right'; ctx.fillStyle = color; ctx.fillText('+' + (items.length - 12), x1, y - 14); }
        });
    }
    function animate(time) {
        if (time - last > 32) { draw(time); last = time; }
        frame = requestAnimationFrame(animate);
    }
    function syncMotion() {
        cancelAnimationFrame(frame); draw();
        const stopped = paused || reduced.matches;
        motion.setAttribute('aria-pressed', String(stopped)); motion.textContent = stopped ? '▷' : 'Ⅱ';
        motion.title = motion.ariaLabel = stopped ? '播放资源动效' : '暂停资源动效';
        if (!stopped && !document.hidden && visible && pods.some(pod => pod.phase === 'Running')) frame = requestAnimationFrame(animate);
    }
    motion.onclick = () => { paused = !paused; syncMotion(); };
    reduced.addEventListener('change', () => { paused = reduced.matches; syncMotion(); });
    document.addEventListener('visibilitychange', syncMotion);
    new ResizeObserver(() => draw()).observe(canvas);
    new IntersectionObserver(entries => { visible = entries[0].isIntersecting; syncMotion(); }).observe(root);
    async function loadResearch() {
        const [experiments, workspaces] = await Promise.allSettled([API.listExperiments(), API.paperWorkspaces()]);
        $('researchTotals').textContent = experiments.status === 'fulfilled' ? `${experiments.value.experiments.length} 个可访问实验` : '实验概览加载失败';
        if (workspaces.status !== 'fulfilled') { $('recentWork').textContent = '工作概览加载失败：' + workspaces.reason.message; return; }
        const work = [...workspaces.value.workspaces].sort((a, b) => b.updated_at - a.updated_at);
        const states = {queued: '排队中', running: '执行中', failed: '失败', interrupted: '已中断', completed: '已完成', scheduled: '已调度'};
        $('recentWork').innerHTML = work.slice(0, 3).map(item => `<a class="research-work" href="/paper_workspace.html?id=${encodeURIComponent(item.id)}"><i class="status-dot ${['running', 'queued'].includes(item.status) ? 'running' : item.status === 'failed' ? 'attention' : 'done'}"></i><span><b>${escapeHtml(item.name)}</b><small>${escapeHtml(states[item.status] || item.status)} · ${escapeHtml(fmtTime(item.updated_at))}</small></span><span>↗</span></a>`).join('') || '<p class="people-empty">暂无工作记录</p>';
    }
    window.addEventListener('chat:done', loadResearch);
    return {
        update(value) {
            pods = value; loaded = true;
            const running = pods.filter(pod => pod.phase === 'Running').length;
            $('overviewTotal').textContent = pods.length; $('overviewRunning').textContent = running; $('overviewAttention').textContent = pods.length - running;
            $('resourceDistribution').textContent = tiers.map(([key, label]) => `${label} ${pods.filter(pod => pod.node_type === key).length}`).join(' · ');
            canvas.setAttribute('aria-label', '已分配计算实例：' + $('resourceDistribution').textContent);
            syncMotion();
        },
        error(message) { $('resourceDistribution').textContent = '资源刷新失败：' + message; },
        loadResearch,
    };
})();
