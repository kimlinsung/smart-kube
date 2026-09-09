const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
const output=fs.mkdtempSync('/tmp/testbed-ui-'),base=process.env.PREVIEW_URL||'http://127.0.0.1:18766';
const nodes=[{name:'node104',hostname:'compute-104',ready:'True',arch:'amd64',node_type:'cloud',internal_ip:'10.156.186.4'},
{name:'arm207',hostname:'research-arm',ready:'False',arch:'arm64',node_type:'edge',unschedulable:true}];
const pods=nodes.map((n,i)=>({...n,name:'unit-'+i,node:n.name,owner_username:'researcher',phase:i?'Pending':'Running',kind:'ssh'}));
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 try {
  for(const width of [1440,390,320]) {
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    let json={};
    if(path==='/api/me')json={id:1,username:'researcher',role:'admin'};
    if(path==='/api/models')json={models:[{id:'a',label:'Research model A',available:true},{id:'b',label:'Research model B',available:true}],selected:'a'};
    if(path==='/api/admin/nodes')json={nodes};
    if(path==='/api/admin/pods')json={pods};
    if(path==='/api/public/devices')json={devices:[{category:'edge',device:'Jetson AGX Orin',isa:'ARM64',count:2,has_online_status:false}],totals:{all:2,cloud:0,edge:2,iot:0}};
    return route.fulfill({json});
   });
   for(const name of ['welcome','devices']){
    await page.goto(base+'/'+name+'.html');
    await page.waitForFunction(()=>document.querySelector('.hardware-object img')?.naturalWidth>0);
    await page.locator('[data-board="2"]').click();
    assert.equal(await page.locator('.hardware-spec h3').innerText(),'Milk-V Meles');
    await page.locator('[data-board="0"]').click();
    if(name==='welcome'){
     await page.locator('[data-set-lang="zh"]').click();
     assert.doesNotMatch(await page.locator('body').innerText(),/smart-kube|kubernetes/i);
    }
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:output+'/'+name+'-'+width+'.png'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,name+' overflow '+width);
   }
   for(const name of ['admin','all_units']){
    await page.goto(base+'/'+name+'.html');
    await page.waitForSelector('.inventory-metrics b');
    assert.equal(await page.locator('.sidebar-brand').getAttribute('href'),'/welcome.html');
    await page.locator('[data-mode="grid"]').click();
    assert.equal(await page.locator('.inventory-item').count(),2);
    await page.locator('.inventory-toolbar select').selectOption('cloud');
    assert.equal(await page.locator('.inventory-item').count(),1);
    await page.locator('.inventory-toolbar input').fill('no-such-node');
    assert.equal(await page.locator('.inventory-item').count(),0);
    await page.locator('.inventory-toolbar input').fill('');
    await page.locator('.inventory-toolbar select').selectOption('');
    await page.locator('#topbar .model-menu summary').click();
    await page.locator('#topbar [data-model-id="b"]').click();
    assert.match(await page.locator('#topbar .model-current b').innerText(),/model B/);
    if(width<900)await page.locator('#menuToggle').click();
    await page.locator('#userBtn').click();
    const button=await page.locator('#menuLogout').boundingBox();
    assert(button.height<=36&&button.width<160,'Oversized logout');
    await page.locator('#userBtn').click();
    if(width<900)await page.locator('.sidebar-backdrop').click({position:{x:width-10,y:100}});
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:output+'/'+name+'-'+width+'.png',fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,name+' overflow '+width);
   }
   assert.deepEqual(errors,[]);await page.close();
  }
  console.log('PASS: hardware assets and switching, testbed branding, inventory views/filters, model menu, home link, compact logout, responsive layout');console.log('SCREENSHOTS '+output);
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
