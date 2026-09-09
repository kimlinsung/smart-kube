const {chromium} = require('playwright');
const {PNG} = require('pngjs');
const assert = require('node:assert/strict'), fs = require('node:fs');
const base = process.env.PREVIEW_URL || 'http://127.0.0.1:18766';
const output = fs.mkdtempSync('/tmp/research-console-');
const now = Math.floor(Date.now() / 1000), id = 'a'.repeat(32);
const workspace = {id, experiment_id:11, user_id:1, name:'异构推理性能对照', goal:'对照论文指标与执行结果', access_role:'owner', mode:'full', status:'completed', stage:'completed', created_at:now-300, updated_at:now, config_json:{}, schedule_json:{}, analysis_json:{}, files:[], events:[], tasks:[]};
const experiments = Array.from({length:24}, (_, i) => ({id:i+1, name:['异构推理性能对照','协同调度消融分析','多节点扩展性研究'][i%3]+' '+(i+1), user_id:i%4===0?2:1, owner_username:i%4===0?'collaborator':'researcher', access_role:i%4===0?'collaborator':'owner', created_at:now-i*1200, cloud_count:2, edge_count:1, device_count:0, total_count:3}));
const pods = Array.from({length:7}, (_,i)=>({name:'research-unit-'+i, owner_id:1, node:'node104', arch:i%2?'arm64':'amd64', image:'python:3.11', node_type:['cloud','edge','device'][i%3], phase:i===6?'Pending':'Running', kind:'ssh'}));
(async()=>{
    const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined});
    const errors=[];
    try {
        for(const width of [1440,390,320]) {
            const page=await browser.newPage({viewport:{width,height:960}});
            page.on('pageerror',e=>errors.push(e.message));
            page.on('dialog',d=>d.accept());
            let members=[], share={enabled:false}, candidateQueries=0, invites=0, entered=0;
            await page.route('**/api/**', async route=>{
                const request=route.request(), path=new URL(request.url()).pathname;
                let json={};
                if(path==='/api/me')json={id:1,username:'researcher',role:'admin',feishu_open_id:'test',password_generated:true,can_reset_with_feishu:true,current_experiment_id:11};
                else if(path==='/api/models')json={models:[{id:'a',label:'Research model',available:true}],selected:'a'};
                else if(path==='/api/experiments')json={experiments,current_experiment_id:11};
                else if(path==='/api/resources')json={pods};
                else if(path==='/api/paper/workspaces')json={workspaces:[workspace,{...workspace,id:'b'.repeat(32),name:'边缘节点吞吐测试',status:'running'}, {...workspace,id:'c'.repeat(32),name:'资源受限实验',status:'failed'}]};
                else if(path.startsWith('/api/paper/workspaces/'))json={workspace};
                else if(path.endsWith('/sharing'))json={collaborators:members,share};
                else if(path.endsWith('/collaborator-candidates')){candidateQueries++;json={candidates:[{id:8,username:'li_research',name:'李同学'},{id:9,username:'li_test',name:'李研究员'}]};}
                else if(path.endsWith('/collaborators')){invites++;members=[{user_id:8,username:request.postDataJSON().username,name:'李同学'}];json={collaborators:members};}
                else if(path.endsWith('/collaborators/8')){members=[];json={collaborators:[]};}
                else if(path.endsWith('/share')){share=request.method()==='DELETE'?{enabled:false}:{enabled:true,url:base+'/shared_experiment.html?token=fixture'};json=share;}
                else if(path.endsWith('/enter')){entered++;json={ok:true};}
                else if(path==='/api/tasks')json={tasks:[]};
                else if(path==='/api/experiments/11')json={experiment:experiments[10],access_role:'owner',pods,paper_workspace:workspace,is_current:true};
                else if(path==='/api/me/password')json={ok:true};
                await route.fulfill({json});
            });
            await page.goto(base+'/paper_workspace.html?id='+id);
            await page.locator('#manageSharing').click();
            assert(page.url().includes('/paper_workspace.html'));
            await page.locator('#candidateSearch').fill('李');
            await page.waitForTimeout(350); assert.equal(candidateQueries,0);
            await page.locator('#candidateSearch').fill('李同');
            await page.locator('[data-username="li_research"]').waitFor();
            await page.locator('#candidateSearch').press('ArrowDown');
            await page.keyboard.press('Enter');
            await page.waitForFunction(()=>document.querySelector('.person-row b')?.textContent==='李同学');
            assert.equal(invites,1);assert.equal(entered,0);
            await page.locator('[aria-label="开启公开分享"]').check();
            await page.waitForFunction(()=>document.querySelector('.share-address input')?.value.includes('token=fixture'));
            await page.locator('.collaboration-dialog').screenshot({path:output+'/sharing-'+width+'.png'});
            await page.locator('[aria-label="开启公开分享"]').uncheck();
            await page.waitForFunction(()=>document.querySelector('.share-address').hidden);
            await page.locator('[data-remove="8"]').click();
            await page.waitForFunction(()=>document.querySelector('.people-empty')?.textContent==='暂无协作者');
            await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('.collaboration-dialog'));
            await page.goto(base+'/experiments.html');
            await page.locator('.experiment-row').first().waitFor();
            await page.locator('#experimentSearch').fill('消融');
            assert.equal(await page.locator('.experiment-row').count(),8);
            await page.locator('#experimentSearch').fill('');
            await page.locator('#experimentScope').selectOption('shared');
            assert.equal(await page.locator('.experiment-row [data-act="share"]').count(),0);
            await page.locator('#experimentScope').selectOption('all');
            await page.locator('[data-act="share"]').first().click();
            await page.locator('.collaboration-dialog').waitFor();await page.keyboard.press('Escape');
            assert.equal(entered,0);
            await page.screenshot({path:output+'/experiments-'+width+'.png',fullPage:true});
            assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
            await page.goto(base+'/experiment_detail.html?id=11');
            await page.locator('#manageSharing').click();await page.locator('.collaboration-dialog').waitFor();await page.keyboard.press('Escape');
            await page.screenshot({path:output+'/detail-'+width+'.png',fullPage:true});
            await page.goto(base+'/dashboard.html');
            await page.waitForFunction(()=>document.getElementById('overviewTotal')?.textContent==='7');
            await page.waitForFunction(()=>document.querySelectorAll('.research-work').length===3);
            const first=await page.locator('#resourceCanvas').screenshot(), png=PNG.sync.read(first);
            assert(png.data.some((v,i)=>i%4!==3&&v<100),'Blank summary');
            await page.waitForTimeout(130);
            assert(!first.equals(await page.locator('#resourceCanvas').screenshot()),'Resource activity not animated');
            await page.emulateMedia({reducedMotion:'reduce'});
            await page.waitForFunction(()=>document.getElementById('resourceMotion')?.getAttribute('aria-pressed')==='true');
            assert.equal(await page.locator('#resourceMotion').getAttribute('aria-pressed'),'true');
            await page.screenshot({path:output+'/dashboard-'+width+'.png',fullPage:true});
            assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Dashboard overflow '+width);
            if(width<900)await page.locator('#menuToggle').click();
            await page.locator('#userBtn').click();await page.locator('#menuSecurity').click();
            await page.waitForFunction(()=>document.querySelector('.security-status')?.textContent.includes('飞书身份已验证'));
            assert(await page.locator('[data-current]').isHidden());
            await page.locator('[name=password]').fill('S7!Cobalt_ocean_2026');
            await page.locator('[name=confirm]').fill('S7!Cobalt_ocean_2026');
            await page.locator('.security-dialog').screenshot({path:output+'/security-'+width+'.png'});
            await page.locator('.security-dialog [type=submit]').click();
            await page.waitForFunction(()=>!document.querySelector('.security-dialog'));
            await page.close();
        }
        assert.deepEqual(errors,[]);
        console.log('PASS: workspace inline sharing, searchable candidates, keyboard invites, revoke/remove, experiment filters, account security, animated resource overview, desktop/mobile');
        console.log('SCREENSHOTS '+output);
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
