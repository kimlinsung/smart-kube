/* Run against a static frontend server with Playwright and pngjs installed. */
const {chromium} = require('playwright');
const {PNG} = require('pngjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const url = process.env.PREVIEW_URL || 'http://127.0.0.1:18765';
const output = fs.mkdtempSync('/tmp/smartkube-ui-');
const pngPixels = buffer => {
  const png=PNG.sync.read(buffer); let count=0;
  for(let i=0;i<png.data.length;i+=4) if(Math.min(...png.data.subarray(i,i+3))<170) count++;
  return count/(png.width*png.height);
};
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || undefined,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const errors=[];
  try {
    for(const width of [1280,390,320,1920]) {
      const page=await browser.newPage({viewport:{width,height:1000}});
      page.on('pageerror',error=>errors.push(error.message));
      await page.route('**/api/public/devices',route=>route.fulfill({json:{totals:{all:30,cloud:6,edge:18,iot:6}}}));
      await page.goto(url+'/welcome.html');
      await page.waitForSelector('#scene canvas');
      await page.locator('#phase-5').click();
      await page.locator('#scene').scrollIntoViewIfNeeded();
      const before=await page.locator('#scene canvas').screenshot();
      assert(pngPixels(before)>.01,'Blank canvas at '+width);
      await page.waitForTimeout(250);
      assert(!before.equals(await page.locator('#scene canvas').screenshot()),'Scene does not move');
      await page.locator('#retryDemo').click();
      assert.equal(await page.locator('#scene').getAttribute('data-phase'),'2');
      assert.equal(await page.locator('#retryStatus').isVisible(),true);
      assert.equal(await page.locator('#nextStep').isDisabled(),true);
      await page.locator('#retryDemo').click();
      assert.equal(await page.locator('#scene').getAttribute('data-phase'),'3');
      await page.locator('#phase-2').click();
      await page.keyboard.press('ArrowRight');
      assert.equal(await page.locator('#phase-3').getAttribute('aria-selected'),'true');
      await page.locator('[data-set-lang="zh"]').click();
      assert.match(await page.locator('#stepTitle').innerText(),/可执行程序/);
      await page.emulateMedia({reducedMotion:'reduce'});
      await page.waitForFunction(()=>document.getElementById('motion').getAttribute('aria-pressed')==='true');
      assert.equal(await page.locator('#motion').getAttribute('aria-pressed'),'true');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Overflow at '+width);
      await page.locator('#workflow').screenshot({path:output+'/workflow-'+width+'.png'});
      await page.screenshot({path:output+'/page-'+width+'.png',fullPage:true});
      if(width===1280) {
        await page.emulateMedia({reducedMotion:'no-preference'});
        const box=await page.locator('#scene').boundingBox();
        await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
        await page.mouse.down(); await page.mouse.move(box.x+box.width/2+80,box.y+box.height/2,{steps:8}); await page.mouse.up();
        await page.locator('#resetView').click();
        assert.equal(await page.locator('#scene').getAttribute('data-phase'),'0');
        if(process.env.CAPTURE==='1') {
          for(let i=0;i<7;i++) {
            await page.locator('#phase-'+i).click();
            await page.locator('#workflow').screenshot({path:output+'/frame-'+i+'.png'});
          }
          await page.locator('#retryDemo').click();
          await page.locator('#workflow').screenshot({path:output+'/frame-7.png'});
        }
      }
      await page.close();
    }
    const fallback=await browser.newPage();
    await fallback.route('**/js/welcome_scene.js',route=>route.abort());
    await fallback.goto(url+'/welcome.html');
    await fallback.waitForFunction(()=>document.getElementById('motion').disabled);
    assert(await fallback.locator('#sceneFallback').isVisible());
    await fallback.locator('#phase-6').click();
    assert.match(await fallback.locator('#stepCounter').innerText(),/07/);
    await fallback.close();

    // CRUD is mocked: browser verification must never remove production data.
    for(const width of [1280,390]) {
      const page=await browser.newPage({viewport:{width,height:900}});
      page.on('pageerror',error=>errors.push(error.message));
      const alerts=[];page.on('dialog',async dialog=>{alerts.push(dialog.message());await dialog.accept()});
      let experiments=[1,2,3].map(id=>({id,name:'实验 '+id,user_id:1,access_role:'admin',created_at:1,cloud_count:0,edge_count:0,device_count:0,total_count:0}));
      let workspaces=[1,2,3].map(id=>({id:String(id).padStart(32,'0'),experiment_id:id,user_id:1,name:'工作 '+id,goal:'验证复现',status:id===3?'running':'completed',access_role:'admin',mode:'full',stage:'completed',created_at:1,updated_at:1,config_json:{},schedule_json:{},files:[],events:[],tasks:[]}));
      await page.route('**/api/**',async route=>{
        const path=new URL(route.request().url()).pathname, data=route.request().postDataJSON();
        let json={};
        if(path==='/api/me') json={id:1,username:'test-admin',role:'admin',current_experiment_id:3};
        else if(path==='/api/models') json={models:[{id:'default',name:'Default'}],selected:'default'};
        else if(path==='/api/experiments/batch-delete') {
          json={results:data.ids.map(id=>({id,ok:id!==2,error:id===2?'任务执行中':undefined}))};
          experiments=experiments.filter(item=>!data.ids.includes(item.id)||item.id===2);
        } else if(path==='/api/experiments') json={experiments,current_experiment_id:3};
        else if(path==='/api/paper/workspaces/batch-delete') {
          json={results:data.ids.map(id=>({id,ok:true}))};
          workspaces=workspaces.filter(item=>!data.ids.includes(item.id));
        } else if(path==='/api/paper/workspaces') json={workspaces};
        else if(path.startsWith('/api/paper/workspaces/')) json={workspace:workspaces.find(item=>item.id===path.split('/')[4])};
        else if(path==='/api/tasks') json={tasks:[]};
        await route.fulfill({json});
      });
      await page.goto(url+'/experiments.html');
      await page.locator('[data-select="1"]').check();
      await page.locator('[data-select="2"]').check();
      await page.locator('#deleteSelected').click();
      await page.waitForFunction(()=>!document.querySelector('[data-select="1"]'));
      assert(await page.locator('[data-select="2"]').isChecked());
      assert(alerts.some(text=>text.includes('任务执行中')));
      await page.goto(url+'/paper_workspace.html');
      await page.waitForSelector('.history-row');
      assert(await page.locator('#deleteWorkspace').isVisible());
      assert(await page.locator('[data-select-workspace="'+workspaces[2].id+'"]').isDisabled());
      await page.locator('#selectWorkspaces').check();
      await page.locator('#deleteSelectedWorkspaces').click();
      await page.waitForFunction(()=>document.querySelectorAll('.history-row').length===1);
      assert(await page.locator('#deleteWorkspace').isDisabled());
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Workspace overflow');
      await page.screenshot({path:output+'/workspace-'+width+'.png',fullPage:true});
      await page.close();
    }
    assert.deepEqual(errors,[]);
    console.log('PASS: Agent canvas, motion, retry gate, keyboard, languages, reduced motion, fallback, responsive CRUD and partial failures');
    console.log('SCREENSHOTS '+output);
  } finally {await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
