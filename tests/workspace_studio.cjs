const {chromium}=require('playwright');
const {PNG}=require('pngjs');
const fs=require('node:fs'),assert=require('node:assert/strict');
const output=fs.mkdtempSync('/tmp/workspace-studio-');
const base=process.env.PREVIEW_URL||'http://127.0.0.1:18765';
const id='abc123'.padEnd(32,'0');
const now=Math.floor(Date.now()/1000);
const events=[
 ['intake','agent_started','文档理解 Agent 开始提取论文正文'],
 ['intake','agent_completed','已提取目标、方法与验收依据'],
 ['config','agent_started','结合实时集群容量规划配置'],
 ['config','preflight_failed','第 1/3 轮资源预检未通过，重新规划',{attempt:1}],
 ['config','agent_completed','调整资源配置后通过预检'],
 ['schedule','preflight','整批资源通过集群实时预检'],
 ['schedule','placement','unit-01 已落位到 node104，放宽 node-type',{scheduling:{relaxed:['node_type']}}],
 ['code','agent_started','根据已落位资源生成 Python 代码'],
 ['code','agent_completed','生成协同推理代码与两个 Unit 运行计划'],
 ['execute','execution_completed','node104 执行成功，耗时 1.250s'],
 ['execute','execution_failed','node106 推理超时，保留诊断输出'],
 ['analysis','agent_completed','结果需要关注：第二个 Unit 尚未通过验收'],
 ['report','agent_completed','已生成复现过程与局限报告'],
 ['analysis','retry_requested','返回分析阶段重新检查执行证据',{from:'report',to:'analysis',attempt:1}],
 ['analysis','agent_started','分析 Agent 重新核验失败记录'],
 ['analysis','failed','分析请求超时，已有配置、代码与运行输出仍然保留'],
].map(([phase,event_type,content,data],i)=>({id:i+1,phase,event_type,content,data:data||{},created_at:now-160+i*10}));
const previews={
  1:{filename:'research.pdf',kind:'pdf',url:'/preview-fixture.pdf',size:22000},
  2:{filename:'results.csv',kind:'spreadsheet',size:2800,sheets:[{name:'Latency',rows:[['node','p95 ms'],['node104','125']]},{name:'Throughput',rows:[['node','requests/s'],['node106','42']]}]},
  3:{filename:'report.md',kind:'markdown',size:2400,content:'# Reproduction report\n\n**Evidence first.**\n\n<script>window.previewAttack=true</script><img src=x onerror="window.previewAttack=true">'},
  4:{filename:'figure.png',kind:'image',size:2400,url:'/docs-image.png'},
  5:{filename:'paper.docx',kind:'document',size:4000,blocks:[{type:'paragraph',heading:true,text:'Methods and Evidence'},{type:'paragraph',text:'A reproducible experiment.'},{type:'table',rows:[['Node','Result'],['node104','Passed']]}]},
  6:{filename:'slides.pptx',kind:'slides',size:1000,slides:[['Results','Node 104 completed the experiment.'],['Limitations','GPU resource requirements remain unchanged.']]},
  7:{filename:'analysis.ipynb',kind:'notebook',size:600,cells:[{type:'markdown',source:'# Latency'},{type:'code',source:'print(1.25)',output:'1.25'}]},
};
const workspace={id,experiment_id:11,user_id:1,name:'端边云协同推理 · 论文复现实验',goal:'复现异构节点间的协同推理方法，对照延迟、吞吐与执行证据验证论文中的研究结论。',mode:'full',status:'failed',stage:'analysis',created_at:now-170,updated_at:now-10,finished_at:now-10,retries:1,access_role:'owner',events,
  files:Object.entries(previews).map(([id,p])=>({id:Number(id),original_name:p.filename,size:p.size,artifact_type:Number(id)<3?'input':'generated_code'})),
  config_json:{resources:[{tier:'cloud',arch:'amd64',gpu:1,count:2}],generated_program:{runtime:{language:'python',version:'3.11',image:'python:3.11'},code:'import time\nstart = time.perf_counter()\nprint({"latency": time.perf_counter() - start})',runs:[{},{}]}},
  schedule_json:{created:2,requested:2,placements:[{pod_name:'unit-01',node:'node104',node_type:'edge',arch:'amd64',scheduling:{relaxed:['node_type']}},{pod_name:'unit-02',node:'node106',node_type:'cloud',arch:'amd64'}],executions:[{pod_name:'unit-01',node:'node104',status:'succeeded',stdout:'{"latency":1.25}',exit_code:0,duration_seconds:1.25},{pod_name:'unit-02',node:'node106',status:'timed_out',stderr:'Inference timeout',exit_code:124,duration_seconds:30}]},
  analysis_json:{checks:[{name:'执行证据',passed:true},{name:'延迟验收',passed:false}],verdict:'needs_attention'},report_md:'# Reproduction report\n\nOne successful run; one timeout.',tasks:[]};
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const errors=[];
 try {
  for(const width of [1440,1280,390,320]) {
   const page=await browser.newPage({viewport:{width,height:1000}});page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;let json={};
    if(path==='/api/me')json={id:1,username:'researcher',role:'admin',current_experiment_id:11,current_experiment_name:workspace.name};
    else if(path==='/api/models')json={models:[{id:'default',name:'Research model',label:'Research model'}],selected:'default'};
    else if(path==='/api/paper/workspaces')json={workspaces:[workspace]};
    else if(path.endsWith('/content'))json=previews[Number(path.split('/')[6])];
    else if(path.startsWith('/api/paper/workspaces/'))json={workspace};
    else if(path==='/api/tasks')json={tasks:[]};
    return route.fulfill({json});
   });
   await page.route('**/docs-image.png',route=>route.fulfill({path:'docs/assets/smart-kube-cover.png',contentType:'image/png'}));
   if(process.env.PDF_PREVIEW_PATH)await page.route('**/preview-fixture.pdf',route=>route.fulfill({path:process.env.PDF_PREVIEW_PATH,contentType:'application/pdf'}));
   await page.goto(base+'/paper_workspace.html');
   await page.waitForFunction(()=>document.getElementById('workflowGraph').dataset.nodeCount==='9');
   assert.equal(await page.locator('#workflowGraph').getAttribute('data-retry-count'),'3');
   await page.locator('[data-flow-stage="code"]').click();
   assert.equal(await page.locator('#stageInspector h3').innerText(),'代码生成');
   await page.locator('#flowZoomIn').click();await page.locator('#flowFit').click();
   await page.locator('#flowFocus').click();assert(await page.locator('#flowStudio').evaluate(e=>e.classList.contains('flow-focused')));
   await page.keyboard.press('Escape');
   await page.locator('#flowTimeline').fill('3');
   assert.match(await page.locator('#flowEventCaption').innerText(),/预检未通过/);
   await page.locator('#flowLive').click();
   await page.locator('[data-panel="events"]').click();
   await page.locator('#eventFilter').selectOption('failure');
   assert.match(await page.locator('#workspaceEvents').innerText(),/超时/);
   assert(!(await page.locator('#workspaceEvents').innerText()).includes('node104 执行成功'));
   await page.locator('[data-panel="telemetry"]').click();
   await page.locator('#flowStudio').screenshot({path:output+'/flow-'+width+'.png'});
   await page.screenshot({path:output+'/workspace-'+width+'.png',fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+width);
   await page.locator('[data-panel="files"]').click();
   for(const fileId of [2,3,4,5,6,7,...(process.env.PDF_PREVIEW_PATH?[1]:[])]) {
    await page.locator('[data-preview-file="'+fileId+'"]').click();
    await page.waitForFunction(()=>document.getElementById('previewFilename').textContent!=='加载文件');
    if(fileId===2){await page.locator('#previewSheet').selectOption('1');assert.match(await page.locator('#filePreview').innerText(),/42/);}
    if(fileId===3){assert.equal(await page.evaluate(()=>Boolean(window.previewAttack)),false);await page.locator('#previewSource').click();assert.match(await page.locator('#filePreview').innerText(),/<script>/);}
    if(fileId===4)await page.waitForFunction(()=>document.querySelector('#filePreview img')?.naturalWidth>0);
    if(fileId===1){await page.waitForSelector('.preview-pdf-page');await page.locator('#pdfNext').click();await page.waitForFunction(()=>document.getElementById('pdfPageNumber').textContent==='2 / 2');await page.waitForTimeout(300);const png=PNG.sync.read(await page.locator('.preview-pdf-page').screenshot());assert(png.data.some((v,i)=>i%4!==3&&v<150),'PDF is blank');}
    await page.locator('.file-preview-dialog').screenshot({path:output+'/preview-'+fileId+'-'+width+'.png'});
    await page.keyboard.press('Escape');assert(await page.locator('#filePreviewBackdrop').isHidden());
   }
   await page.close();
  }
  assert.deepEqual(errors,[]);console.log('PASS: real-event graph, failure/retry paths, focus, event replay/filtering, seven preview formats, PDF pages, XSS isolation, mobile layout');console.log('SCREENSHOTS '+output);
 } finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
