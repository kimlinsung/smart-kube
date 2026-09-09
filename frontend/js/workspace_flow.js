/* Observable execution graph. The event cursor never changes server state. */
window.WorkspaceFlow = (() => {
    const stages = [
        ['intake','文档理解','Document Agent','FileText','config'],
        ['config','配置规划','Configuration Agent','Settings2','config'],
        ['gate','资源预检','Preflight Gate','ShieldCheck','schedule'],
        ['schedule','资源调度','Scheduler','Network','schedule'],
        ['code','代码生成','Code Agent','Code2','code'],
        ['execute','真实执行','Execution Engine','Terminal','run'],
        ['analysis','证据分析','Analysis Agent','ChartNoAxesCombined','analysis'],
        ['report','报告归档','Report Agent','FileCheck2','report'],
        ['retain','资源保留','Resource Lifecycle','Archive','schedule'],
    ];
    const names = Object.fromEntries(stages.map(row=>[row[0],row[1]]));
    const states = {pending:'等待',active:'执行中',completed:'完成',failed:'失败',warning:'需关注',skipped:'未启用',retained:'保留中',reclaimed:'已回收'};
    const failure = event => /failed|interrupted/.test(event.event_type);
    const duration = value => value == null ? '—' : value<60 ? `${Math.max(0,value).toFixed(1)} s` : `${Math.floor(value/60)} m ${Math.floor(value%60)} s`;
    const esc = value => escapeHtml(String(value ?? ''));
    function create(container,{onArtifact}) {
        let workspace=null, selected='intake', following=true, cursor=null, timer=null, lastTick=0, lastWorkspace=null;
        let frame=null, animation=0, branchCount=0;
        const $=id=>document.getElementById(id);
        const small=()=>container.clientWidth<480;
        function positions() {
            return stages.map((row,index)=>{
                const columns=small()?2:3, line=Math.floor(index/columns), offset=index%columns;
                return {x:110+(line%2 ? columns-1-offset : offset)*200,y:76+line*125};
            });
        }
        const icons=Object.fromEntries(stages.map(row=>{
            const data=window.lucide?.icons[row[3]];
            return [row[0], data ? 'data:image/svg+xml;base64,'+btoa(window.lucide.createElement(data,{width:18,height:18,stroke:'#5e7ca0','stroke-width':1.7}).outerHTML) : ''];
        }));
        const cy=cytoscape({container, elements:stages.map((row,i)=>({data:{id:row[0],label:row[1],icon:icons[row[0]]},position:positions()[i]})),
            layout:{name:'preset'}, minZoom:.35,maxZoom:2.2, wheelSensitivity:.15, boxSelectionEnabled:false,
            style:[
                {selector:'node',style:{width:166,height:78,shape:'round-rectangle','corner-radius':8,'background-color':'#ffffff','border-color':'#d9e1ed','border-width':1,label:'data(label)',color:'#526379','font-size':11,'font-family':'system-ui','text-wrap':'wrap','text-max-width':130,'text-valign':'center','text-halign':'center','line-height':1.65,'background-image':'data(icon)','background-width':16,'background-height':16,'background-position-x':10,'background-position-y':12,'text-margin-x':7,'overlay-opacity':0}},
                {selector:'node[state="completed"]',style:{'border-color':'#b2dece','background-color':'#f7fcfa',color:'#276a58'}},
                {selector:'node[state="active"]',style:{'border-color':'#548ae7','border-width':2,'background-color':'#edf4ff',color:'#28569b'}},
                {selector:'node[state="failed"]',style:{'border-color':'#e99aa3','background-color':'#fff4f5',color:'#b44253'}},
                {selector:'node[state="warning"]',style:{'border-color':'#e5c78f','background-color':'#fffaf0',color:'#9c742d'}},
                {selector:'node[state="skipped"]',style:{'border-style':'dashed','background-color':'#f7f8fa',color:'#a1adbc',opacity:.6}},
                {selector:'node[state="retained"]',style:{'background-color':'#fffaf0','border-color':'#ecd7a8',color:'#927133'}},
                {selector:'node.selected',style:{'underlay-color':'#4586e6','underlay-opacity':.09,'underlay-padding':7,'underlay-shape':'round-rectangle','border-width':2}},
                {selector:'node.hovered',style:{'border-width':2,'underlay-color':'#9bb3d2','underlay-opacity':.08,'underlay-padding':5,'underlay-shape':'round-rectangle'}},
                {selector:'edge',style:{width:1.5,'line-color':'#d1dae7','target-arrow-color':'#c1cedf','target-arrow-shape':'triangle','arrow-scale':.75,'curve-style':'round-taxi','taxi-direction':'auto','taxi-turn':30,'taxi-radius':12,'overlay-opacity':0}},
                {selector:'edge.done',style:{'line-color':'#74bea7','target-arrow-color':'#74bea7'}},
                {selector:'edge.current',style:{'line-color':'#4989e8','target-arrow-color':'#4989e8','line-style':'dashed','line-dash-pattern':[6,5],width:2}},
                {selector:'edge.retry',style:{'line-color':'#d19a3a','target-arrow-color':'#d19a3a','line-style':'dashed','line-dash-pattern':[5,4],width:2,'curve-style':'unbundled-bezier','control-point-distances':-90,'control-point-weights':.5,label:'data(label)','font-size':10,color:'#a87a2b','text-background-color':'#f8fafc','text-background-opacity':1,'text-background-padding':4,'text-rotation':'autorotate'}},
                {selector:'edge.retry:loop',style:{'curve-style':'bezier','loop-direction':'0deg','loop-sweep':'65deg'}},
            ]});
        cy.nodes().ungrabify();
        function events() {const all=workspace?.events||[];return cursor===null?all:all.slice(0,cursor+1);}
        function stageEvents(id) {return events().filter(event=>id==='gate' ? event.event_type==='preflight_failed'||event.event_type==='preflight' : event.phase===id);}
        function stageState(id) {
            if(!workspace) return 'pending';
            if(['code','execute','analysis'].includes(id)&&workspace.mode==='resources') return 'skipped';
            if(cursor===null && id==='retain') return workspace.resources_reclaimed?'reclaimed':workspace.schedule_json?.created>0?'retained':'pending';
            if(id==='execute' && (cursor===null ? (workspace.schedule_json?.executions||[]).some(run=>run.status!=='succeeded') : stageEvents(id).some(event=>event.event_type==='execution_failed'))) return 'warning';
            const list=events();
            const last=list[list.length-1];
            if(id==='gate') {
                const failed=list.filter(event=>event.event_type==='preflight_failed').slice(-1)[0];
                const passed=list.filter(event=>event.event_type==='preflight').slice(-1)[0];
                if(failed&&(!passed||passed.id<failed.id))return cursor!==null||workspace.status==='failed'?'failed':'warning';
            }
            let current=cursor===null?workspace.stage:last?.phase;
            if(last?.event_type==='preflight_failed' && (cursor!==null || workspace.stage==='config')) current='gate';
            const position=stages.findIndex(row=>row[0]===current);
            if(current==='completed') return 'completed';
            if(id===current) {
                if(cursor===null && ['failed','interrupted'].includes(workspace.status)) return 'failed';
                if(cursor!==null&&failure(last)) return 'failed';
                return 'active';
            }
            if(stages.findIndex(row=>row[0]===id)<position) return 'completed';
            if(stageEvents(id).some(event=>/agent_completed|succeeded/.test(event.event_type))) return 'completed';
            return 'pending';
        }
        function elapsed(id) {
            const list=stageEvents(id); if(!list.length) return null;
            const first=list[0].created_at;
            const end=stageState(id)==='active'&&cursor===null ? Date.now()/1000 : list[list.length-1].created_at;
            return Math.max(0,end-first);
        }
        function drawEdges() {
            cy.edges().remove();
            const active=stages.filter(row=>!(['code','execute','analysis'].includes(row[0])&&workspace.mode==='resources'));
            for(let i=0;i<active.length-1;i++) {
                const state=stageState(active[i+1][0]);
                cy.add({data:{id:'path-'+i,source:active[i][0],target:active[i+1][0]},classes:state==='active'?'current':['completed','warning','failed','retained','reclaimed'].includes(state)?'done':''});
            }
            const list=events(); branchCount=0;
            const preflight=list.filter(event=>event.event_type==='preflight_failed');
            const replans=preflight.filter(event=>list.some(later=>later.id>event.id && ['config','schedule'].includes(later.phase) && later.event_type!=='failed')).length;
            if(replans) {branchCount+=replans;cy.add({data:{id:'replan',source:'gate',target:'config',label:`预检失败 / 重规划 ×${replans}`},classes:'retry'});}
            const placements=cursor===null ? workspace.schedule_json?.placements||[] : list.filter(event=>event.event_type==='placement').map(event=>event.data||{scheduling:{relaxed:event.transition?.relaxed||[]}});
            const fallback=placements.filter(item=>item.scheduling?.relaxed?.length).length;
            if(fallback) {branchCount+=fallback;cy.add({data:{id:'fallback',source:'schedule',target:'schedule',label:`节点类型回退 ×${fallback}`},classes:'retry'});}
            const retries=list.filter(event=>event.event_type==='retry_requested');
            const count=cursor===null?Math.max(retries.length,workspace.retries||0):retries.length;
            if(count) {
                branchCount+=count;
                const groups=new Map();
                for(const event of retries) {let source=(event.data||event.transition)?.from;source=source==='completed'?'retain':names[source]?source:'analysis';groups.set(source,(groups.get(source)||0)+1);}
                if(count>retries.length)groups.set('analysis',(groups.get('analysis')||0)+count-retries.length);
                if(!groups.size)groups.set('analysis',count);
                for(const [source,total] of groups)cy.add({data:{id:'analysis-retry-'+source,source,target:'analysis',label:`返回分析 ×${total}`},classes:'retry'});
            }
        }
        function inspector() {
            if(!workspace) return;
            const row=stages.find(row=>row[0]===selected), list=stageEvents(selected);
            const status=stageState(selected), failures=list.filter(failure).length;
            $('stageInspector').innerHTML=`<div class="stage-icon"><i data-lucide="${row[3].replace(/([a-z])([A-Z])/g,'$1-$2').toLowerCase()}"></i></div><span class="agent-tag">${esc(row[2])}</span><h3>${esc(row[1])}</h3><dl class="stage-facts"><div><dt>状态</dt><dd>${states[status]||status}</dd></div><div><dt>记录跨度</dt><dd>${duration(elapsed(selected))}</dd></div><div><dt>事件</dt><dd>${list.length}</dd></div><div><dt>异常</dt><dd>${failures}</dd></div></dl><ol class="stage-trace">${list.slice(-4).reverse().map(event=>`<li class="${failure(event)?'error':''}"><time>${new Date(event.created_at*1000).toLocaleTimeString('zh-CN',{hour12:false})}</time>${esc(event.content)}</li>`).join('')||'<li>尚无此阶段的执行记录</li>'}</ol><button class="stage-artifact" data-flow-artifact="${row[4]}">查看阶段产物<i data-lucide="arrow-up-right"></i></button>`;
            window.lucide?.createIcons();
        }
        function draw() {
            if(!workspace) return;
            const list=events();
            if(following) {
                const id=cursor===null ? workspace.stage : list[list.length-1]?.phase;
                if(names[id]) selected=id;
                if(list[list.length-1]?.event_type==='preflight_failed' && (cursor!==null||workspace.stage==='config')) selected='gate';
            }
            cy.batch(()=>{
                stages.forEach(row=>{
                    const node=cy.getElementById(row[0]),status=stageState(row[0]);
                    node.data({state:status,label:`${row[1]}\n${row[2]}\n${states[status]} · ${duration(elapsed(row[0]))}`});
                    node.toggleClass('selected',row[0]===selected);
                });
                drawEdges();
            });
            container.dataset.nodeCount=String(cy.nodes().length);
            container.dataset.retryCount=String(cy.edges('.retry').length);
            container.dataset.selectedStage=selected;
            const total=workspace.finished_at||(['running','queued'].includes(workspace.status)?Date.now()/1000:workspace.updated_at||workspace.created_at);
            const runs=workspace.schedule_json?.executions||[];
            const elapsedTotal=cursor===null?total-workspace.created_at:(list[list.length-1]?.created_at||workspace.created_at)-workspace.created_at;
            $('flowSummary').innerHTML=`<div><small>总耗时</small><strong>${duration(elapsedTotal)}</strong></div><div><small>${cursor===null?'当前阶段':'回放阶段'}</small><strong>${esc(names[cursor===null?workspace.stage:list[list.length-1]?.phase]|| (workspace.status==='completed'?'已归档':'待开始'))}</strong></div><div><small>回退 / 重试记录</small><strong class="${branchCount?'warning':''}">${branchCount}</strong></div><div><small>运行成功 / 总数</small><strong>${cursor===null?`${runs.filter(r=>r.status==='succeeded').length} / ${runs.length}`:'—'}</strong></div>`;
            $('flowRunId').textContent='RUN / '+workspace.id.slice(0,12);
            $('stageNav').innerHTML=stages.map(row=>`<button type="button" data-flow-stage="${row[0]}" aria-pressed="${row[0]===selected}">${row[1]}</button>`).join('');
            const all=workspace.events||[];
            $('flowTimeline').max=Math.max(0,all.length-1);$('flowTimeline').value=cursor??Math.max(0,all.length-1);$('flowTimeline').disabled=!all.length;
            $('flowPlay').disabled=!all.length;
            $('flowEventPosition').textContent=`${all.length ? (cursor??all.length-1)+1 : 0} / ${all.length}`;
            $('flowLive').classList.toggle('active',cursor===null);
            $('flowEventCaption').textContent=(cursor===null?'最新记录 · ':'历史回放 · ')+(list[list.length-1]?.content||'等待流程事件');
            inspector();
        }
        function select(id) {
            selected=id;following=false;draw();
            if(!matchMedia('(prefers-reduced-motion: reduce)').matches)$('stageInspector').animate([{opacity:.4,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],{duration:180,easing:'ease-out'});
        }
        cy.on('tap','node',event=>select(event.target.id()));
        cy.on('mouseover','node',event=>{event.target.addClass('hovered');container.style.cursor='pointer';});
        cy.on('mouseout','node',event=>{event.target.removeClass('hovered');container.style.cursor='default';});
        cy.on('zoom',()=>{$('flowZoom').textContent=Math.round(cy.zoom()*100)+'%';});
        $('stageNav').onclick=event=>{const b=event.target.closest('[data-flow-stage]');if(b)select(b.dataset.flowStage);};
        $('stageInspector').onclick=event=>{const b=event.target.closest('[data-flow-artifact]');if(b)onArtifact(b.dataset.flowArtifact);};
        function fit() {cy.resize();cy.nodes().positions((node,i)=>positions()[i]);cy.fit(cy.elements(),30);}
        $('flowFit').onclick=fit;
        $('flowZoomIn').onclick=()=>cy.zoom({level:Math.min(2.2,cy.zoom()*1.2),renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
        $('flowZoomOut').onclick=()=>cy.zoom({level:Math.max(.35,cy.zoom()/1.2),renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
        $('flowFocus').onclick=()=>{const value=$('flowStudio').classList.toggle('flow-focused');$('flowFocus').setAttribute('aria-pressed',String(value));$('flowFocus').title=value?'退出专注模式':'专注模式';requestAnimationFrame(fit);};
        function stop() {clearInterval(timer);timer=null;$('flowPlay').setAttribute('aria-pressed','false');$('flowPlay').innerHTML='<i data-lucide="play"></i>';window.lucide?.createIcons();}
        $('flowTimeline').oninput=event=>{stop();cursor=Number(event.target.value);following=true;draw();};
        $('flowLive').onclick=()=>{stop();cursor=null;following=true;draw();};
        $('flowPlay').onclick=()=>{
            if(timer){stop();return;}
            cursor=0;following=true;draw();$('flowPlay').setAttribute('aria-pressed','true');$('flowPlay').innerHTML='<i data-lucide="pause"></i>';window.lucide?.createIcons();
            timer=setInterval(()=>{if(cursor>=workspace.events.length-1){stop();return;}cursor++;draw();},1100);
        };
        document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('flowStudio').classList.contains('flow-focused'))$('flowFocus').click();});
        document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
        const observer=new ResizeObserver(()=>{if(workspace)fit();});observer.observe(container);
        function tick(now) {
            if(workspace&&!document.hidden) {
                if(now-lastTick>1000) {lastTick=now;if(cursor===null&&['running','queued'].includes(workspace.status))draw();}
                if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&now-animation>100) {animation=now;cy.edges('.current').style('line-dash-offset',-now/80);}
            }
            frame=requestAnimationFrame(tick);
        }
        frame=requestAnimationFrame(tick);
        return {
            update(value) {workspace=value;if(lastWorkspace!==value.id){stop();cursor=null;following=true;selected='intake';lastWorkspace=value.id;draw();fit();}else draw();},
            clear() {workspace=null;stop();},
            dispose() {observer.disconnect();stop();cancelAnimationFrame(frame);cy.destroy();}
        };
    }
    return {create};
})();
