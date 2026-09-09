/* Public workflow presentation. It never creates jobs or reads private cluster state. */
(() => {
  const copy = {
    zh: {
      navWorkflow:'Agent 工作流',navDevices:'异构设备',navEnter:'进入工作区',
      heroTitle:'端边云论文复现',heroDescription:'让论文中的方法，走向真实的异构计算。',start:'开始复现实验',
      tierDevice:'端侧感知',tierEdge:'近端推理',tierCloud:'集中计算',
      tierDefault:'从端侧数据到云端计算，在同一个实验中连接方法与证据。',
      concept:'架构概念演示 · 非实时集群状态',
      workflowTitle:'从一篇论文，到一条证据链。',
      workflowDescription:'每个 Agent 各司其职。先确认计算资源，再生成程序，最后用实际输出审视复现结果。',
      researchTitle:'同一方法，不同计算边界。',
      researchDescription:'面向端边云协同研究，把工作负载、运行环境与实验记录放在一起。',
      research1:'协同推理',research1Description:'探索模型与任务在云、边、端的分配方式，对照实际输出与耗时，检验论文中的协同路径。',
      research2:'异构计算',research2Description:'结合集群中就绪节点的架构、GPU、内存与容量规划实验。硬件约束可核验，调度回退有记录。',
      research3:'可追溯复现',research3Description:'保留原始输入、生成代码、运行输出与分析报告。复现范围与局限显式记录，结果以真实执行证据为依据。',
      closingTitle:'让研究，继续向前。',closingDescription:'上传论文或实验材料，开启你的端边云复现工作区。',
      browseDevices:'浏览设备清单',footer:'为科研与教学而构建',
      tiers:['DEVICE / 传感与数据采集，让实验从真实输入出发。','EDGE / ARM64 与 RISC-V 等异构节点，承载近端任务。','CLOUD / x86 与 GPU 计算资源，承载集中式实验负载。'],
      phases:[
        ['文档理解','DOCUMENT AGENT','读懂方法，也读懂边界。','从论文与输入材料中提取实验目标、方法步骤和验收依据。记录假设与缺失信息，明确本次复现的范围。','产物：实验目标 · 文档证据 · 范围与假设'],
        ['配置规划','CONFIGURATION AGENT','把研究问题，映射到资源。','结合文档证据与集群实时能力，规划架构、镜像、CPU、内存与 GPU 请求。配置不满足预检时，携带诊断重新规划。','产物：资源配置 · 运行环境 · 预检诊断'],
        ['资源调度','KUBERNETES SCHEDULING','先找到算力，再开始生成。','先尝试满足条件的就绪节点；必要时放宽节点类型，尝试其他可用节点。架构、GPU 等硬约束保留，全部资源调度成功后再进入代码生成。','产物：节点落位 · 资源实例 · 回退记录'],
        ['代码生成','CODE AGENT','让方法，成为可执行程序。','在调度成功后，根据正文与资源配置生成 Python 程序及逐 Unit 运行计划。代码作为工作区产物保存，支持预览与下载。','产物：生成代码 · 运行参数 · 预期观测'],
        ['真实执行','EXECUTION ENGINE','在容器里运行，在输出中求证。','等待运行实例就绪，上传并执行程序。收集标准输出、错误输出、退出码与实际耗时，保留失败和超时证据。','产物：运行输出 · 退出状态 · 实测耗时'],
        ['证据分析','ANALYSIS AGENT','让结论，接受证据检验。','分析 Agent 对照实验目标与真实运行输出，检查结果、识别风险并提出后续建议。执行成功不等同于科学结论被完整复现。','产物：检查结果 · 风险与局限 · 后续建议'],
        ['报告归档','REPORT AGENT','留下可继续研究的现场。','汇总输入、配置、调度、代码与执行证据，形成可下载的实验报告。资源由用户决定回收，实验产物可继续保留。','产物：Markdown 报告 · 完整实验档案']
      ]
    },
    en: {
      navWorkflow:'Agent workflow',navDevices:'Devices',navEnter:'Workspace',
      heroTitle:'Cloud–Edge–Device Paper Reproduction',heroDescription:'Bring research methods to real, heterogeneous compute.',start:'Start an experiment',
      tierDevice:'Sensing',tierEdge:'Near-field inference',tierCloud:'Central compute',
      tierDefault:'Connect methods and evidence, from device-side input to cloud compute.',
      concept:'Architecture demonstration · Not live cluster status',
      workflowTitle:'From a paper to a chain of evidence.',
      workflowDescription:'Specialized agents, one traceable workflow. Schedule resources first, generate programs next, then examine real execution results.',
      researchTitle:'One method. Different compute boundaries.',
      researchDescription:'Bring workloads, runtime environments and experiment records together for cloud–edge–device research.',
      research1:'Collaborative inference',research1Description:'Explore how models and tasks span cloud, edge and device tiers. Compare actual outputs and timings against the method described in a paper.',
      research2:'Heterogeneous compute',research2Description:'Plan against Ready nodes, architecture, GPU, memory and capacity. Hardware constraints remain verifiable; scheduling fallbacks are recorded.',
      research3:'Traceable reproduction',research3Description:'Keep source materials, generated code, execution outputs and analysis together. State the scope and limitations, and ground conclusions in execution evidence.',
      closingTitle:'Take your research further.',closingDescription:'Upload a paper or experiment materials to begin your reproduction workspace.',
      browseDevices:'Explore the device inventory',footer:'Built for research and education',
      tiers:['DEVICE / Sensors and data collection provide experiment inputs.','EDGE / ARM64, RISC-V and other architectures host near-field tasks.','CLOUD / x86 and GPU resources host centralized experiment workloads.'],
      phases:[
        ['Understand','DOCUMENT AGENT','Understand the method. And its limits.','Extract objectives, method steps and acceptance criteria from source materials. Record assumptions and missing information to establish the scope of reproduction.','Artifacts: objectives · source evidence · assumptions'],
        ['Plan','CONFIGURATION AGENT','Map the research question to resources.','Combine source evidence with live cluster capacity to plan architecture, images, CPU, memory and GPU requests. Feed preflight diagnostics into replanning.','Artifacts: resource configuration · runtime · diagnostics'],
        ['Schedule','KUBERNETES SCHEDULING','Secure compute before generating code.','Select eligible Ready nodes. When needed, relax node type to consider alternatives while preserving architecture and GPU constraints. All resources must be scheduled before code generation.','Artifacts: placements · resource instances · fallback records'],
        ['Generate','CODE AGENT','Turn the method into a program.','After scheduling succeeds, generate a Python program and per-Unit execution plan from the source and configuration. Save code as a previewable, downloadable artifact.','Artifacts: generated code · run parameters · observations'],
        ['Execute','EXECUTION ENGINE','Run in containers. Inspect real outputs.','Wait for runtime readiness, upload the program and execute it. Capture stdout, stderr, exit codes and elapsed time, including failure and timeout evidence.','Artifacts: execution outputs · exit status · elapsed time'],
        ['Analyze','ANALYSIS AGENT','Put conclusions to the evidence test.','Compare objectives with actual execution outputs, identify risks and suggest next steps. A successful run does not establish complete scientific reproduction.','Artifacts: checks · limitations · recommendations'],
        ['Report','REPORT AGENT','Keep a record you can build on.','Assemble source, configuration, placement, code and execution evidence into a downloadable report. Reclaim compute independently while retaining experiment artifacts.','Artifacts: Markdown report · experiment archive']
      ]
    }
  };
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let lang = window.I18N?.getLang() || 'zh', phase = 0, playing = false, timer = null, retry = false;
  let sceneApi = null, paused = reduced.matches;
  const $ = id => document.getElementById(id);
  const icons = () => window.lucide?.createIcons();
  function updatePhase() {
    const row = copy[lang].phases[phase];
    ['agentName','stepTitle','stepDescription','stepArtifact'].forEach((id,i) => { $(id).textContent = row[i+1]; });
    $('stepNumber').textContent = String(phase+1).padStart(2,'0');
    $('stepCounter').textContent = String(phase+1).padStart(2,'0') + ' / 07';
    $('pipelineProgress').style.width = ((phase+1)/7*100)+'%';
    $('previousStep').disabled = phase === 0;
    $('nextStep').disabled = phase === 6 || retry;
    $('playWorkflow').disabled = retry;
    document.querySelectorAll('.phase-tab').forEach((button,i) => {
      button.setAttribute('aria-selected', String(i === phase));
      button.tabIndex = i === phase ? 0 : -1;
    });
    $('stepPanel').setAttribute('aria-labelledby','phase-'+phase);
    sceneApi?.setPhase(phase);
    sceneApi?.setRetry(retry);
    $('retryDemo').setAttribute('aria-pressed',String(retry));
    $('retryDemo').title = retry ? '重试成功，继续 / Retry succeeded, continue' : '调度失败分支 / Scheduling failure branch';
    $('retryStatus').hidden = !retry;
    $('retryStatus').textContent = lang === 'zh' ? '调度未成功 → 返回配置规划 → 尝试其他就绪节点；代码生成等待调度成功。' : 'Scheduling failed → revise plan → try another Ready node. Code generation waits for successful placement.';
  }
  function renderCopy() {
    document.documentElement.lang = lang;
    document.title = 'Smart-Kube · ' + copy[lang].heroTitle;
    document.querySelectorAll('[data-copy]').forEach(el => { el.textContent = copy[lang][el.dataset.copy]; });
    $('phaseRail').innerHTML = copy[lang].phases.map((row,i) => '<button type="button" role="tab" class="phase-tab" id="phase-'+i+'" data-phase="'+i+'" aria-controls="stepPanel"><small>0'+(i+1)+'</small><span>'+row[0]+'</span></button>').join('');
    updatePhase();
    sceneApi?.setLabels(copy[lang].phases.map(row=>row[0]));
  }
  function stopPlayback() {
    playing = false;
    clearInterval(timer);
    $('playWorkflow').setAttribute('aria-pressed','false');
    $('playWorkflow').setAttribute('aria-label','Play workflow');
    $('playWorkflow').innerHTML = '<i data-lucide="play"></i>';
    icons();
  }
  function selectPhase(index) { stopPlayback(); retry = false; phase = Math.max(0,Math.min(6,index)); updatePhase(); }
  $('phaseRail').addEventListener('click',event => { const b = event.target.closest('[data-phase]'); if(b) selectPhase(Number(b.dataset.phase)); });
  $('phaseRail').addEventListener('keydown',event => {
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    selectPhase(event.key === 'Home' ? 0 : event.key === 'End' ? 6 : (phase + (event.key === 'ArrowRight' ? 1 : 6)) % 7);
    $('phase-'+phase).focus();
  });
  $('previousStep').onclick = () => selectPhase(phase-1);
  $('nextStep').onclick = () => selectPhase(phase+1);
  $('playWorkflow').onclick = () => {
    if(playing) { stopPlayback(); return; }
    playing = true;
    if(phase === 6) { phase = 0; updatePhase(); }
    $('playWorkflow').setAttribute('aria-pressed','true');
    $('playWorkflow').setAttribute('aria-label','Pause workflow');
    $('playWorkflow').innerHTML = '<i data-lucide="pause"></i>';
    icons();
    timer = setInterval(() => { if(phase < 6) { phase++; updatePhase(); } else stopPlayback(); },4200);
  };
  $('resetView').onclick = () => { selectPhase(0); sceneApi?.reset(); };
  $('retryDemo').onclick = () => { stopPlayback(); retry = !retry; phase = retry ? 2 : 3; updatePhase(); };
  function setMotion(value) {
    paused = value;
    $('motion').setAttribute('aria-pressed',String(paused));
    $('motion').setAttribute('aria-label',paused ? 'Resume motion' : 'Pause motion');
    $('motion').title = paused ? '继续动效 / Resume motion' : '暂停动效 / Pause motion';
    $('motion').innerHTML = '<i data-lucide="'+(paused ? 'play' : 'pause')+'"></i>';
    sceneApi?.setPaused(paused);
    icons();
  }
  $('motion').onclick = () => setMotion(!paused);
  window.I18N?.onChange(value => { lang = value; renderCopy(); });
  reduced.addEventListener('change',event => { setMotion(event.matches); if(event.matches) stopPlayback(); });
  document.addEventListener('visibilitychange',() => { if(document.hidden) stopPlayback(); });
  renderCopy();
  setMotion(paused);
  import('/js/welcome_scene.js').then(module => {
    sceneApi = module.createScene($('scene'), { onSelect:selectPhase, paused });
    sceneApi.setPhase(phase);
    sceneApi.setRetry(retry);
    sceneApi.setLabels(copy[lang].phases.map(row=>row[0]));
    $('sceneFallback').hidden = true;
  }).catch(error => {
    console.warn('3D presentation unavailable:',error.message);
    $('motion').disabled = true;
    $('resetView').disabled = true;
  });
})();
